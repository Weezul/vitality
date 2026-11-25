"""Administrator actions and authenticated WebSocket commands."""

from datetime import UTC, datetime

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .analytics import analyze
from .const import DOMAIN, SIGNAL
from .garmin_data import backfill_battery, override
from .queries import (
    daily,
    export,
    history,
    import_status,
    mood_readings,
    range_args,
    samples,
)
from .validation import Invalid, only

EVENT = {
    "activity_type": str,
    "quantity": vol.Any(int, float),
    "unit": str,
    "duration_minutes": vol.Any(int, float, None),
    "occurred_at": str,
    "notes": str,
}
CHECKIN = {"kind": str, "score": vol.Any(int, float), "occurred_at": str, "notes": str}
ACTIONS = {}
for name, table, fields, required in (
    ("event", "events", EVENT, {"activity_type"}),
    ("checkin", "checkins", CHECKIN, {"kind", "score"}),
):
    ACTIONS[f"log_{name}"] = (
        table,
        "save",
        vol.Schema(
            {
                (vol.Required if k in required else vol.Optional)(k): v
                for k, v in fields.items()
            }
        ),
    )
    ACTIONS[f"update_{name}"] = (
        table,
        "update",
        vol.Schema(
            {vol.Required("id"): str, **{vol.Optional(k): v for k, v in fields.items()}}
        ),
    )
    ACTIONS[f"delete_{name}"] = (table, "delete", vol.Schema({vol.Required("id"): str}))


def active(hass):
    if (runtime := hass.data.get(DOMAIN)) is None or runtime.closing:
        raise HomeAssistantError("Set up Vitality in Devices & services first.")
    return runtime


async def mutate(hass, runtime, operation, data):
    table, method, schema = ACTIONS[operation]
    data = schema(data)
    record_id = data.pop("id", None)
    if method == "delete":
        await runtime.run(runtime.diary.delete_record, table, record_id)
    else:
        record_id = await runtime.run(runtime.diary.save_record, table, data, record_id)
    async_dispatcher_send(hass, SIGNAL)
    return {"id": record_id}


async def authorize(hass, context):
    if context.user_id is not None:
        user = await hass.auth.async_get_user(context.user_id)
        if user is None or not user.is_admin:
            raise Unauthorized(context=context)


def register(hass):
    def handler(operation):
        async def call(service):
            await authorize(hass, service.context)
            await mutate(hass, active(hass), operation, dict(service.data))

        return call

    for name, (_, _, schema) in ACTIONS.items():
        hass.services.async_register(DOMAIN, name, handler(name), schema=schema)

    async def resync(service):
        await authorize(hass, service.context)
        await active(hass).garmin.sync()

    hass.services.async_register(DOMAIN, "resync_garmin", resync, schema=vol.Schema({}))
    websocket_api.async_register_command(hass, websocket)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "vitality/diary",
        vol.Required("operation"): str,
        vol.Optional("data", default=dict): dict,
    }
)
@websocket_api.async_response
async def websocket(hass, connection, msg):
    if connection.user is None or not connection.user.is_admin:
        connection.send_error(
            msg["id"], "unauthorized", "Vitality requires an administrator."
        )
        return
    try:
        runtime = active(hass)
        operation, data = msg["operation"], msg["data"]
        if operation in ACTIONS:
            result = await mutate(hass, runtime, operation, data)
        elif operation == "types":
            only(data)
            result = await runtime.run(runtime.diary.types)
        elif operation == "save_type":
            result = await runtime.run(runtime.diary.save_type, data)
        elif operation == "info":
            only(data)
            result = {
                "timezone": str(runtime.zone),
                "checkin_scale": [1, 10],
                "mood": True,
            }
        elif operation in ("daily", "history", "export", "samples", "analyze", "mood"):
            query = {
                "daily": daily,
                "history": history,
                "export": export,
                "samples": samples,
                "analyze": analyze,
                "mood": mood_readings,
            }[operation]
            result = await runtime.run(query, runtime.diary, runtime.zone, data)
        elif operation == "garmin":
            only(data)
            result = runtime.garmin.describe()
            result["imports"] = await runtime.run(
                import_status, runtime.diary, runtime.zone
            )
        elif operation == "save_metric":
            result = await runtime.garmin.save_metric(data)
        elif operation == "save_workouts":
            result = await runtime.garmin.save_workouts(data)
        elif operation == "resync_garmin":
            only(data)
            result = await runtime.garmin.sync()
        elif operation == "backfill":
            result = await runtime.garmin.sync(backfill=range_args(runtime.zone, data))
        elif operation == "backfill_battery":
            bounds = range_args(runtime.zone, data, "entity", "readings")
            source = runtime.garmin.describe()["metrics"]["body_battery"]
            if (
                data["start"] != data["end"]
                or not source["enabled"]
                or source["attribute"]
            ):
                raise Invalid(
                    "Choose one day and a Body Battery mapping that reads the entity state."
                )
            if not source["entity"] or data.get("entity") != source["entity"]:
                raise Invalid(
                    "The Body Battery mapping changed. Refresh and try again."
                )
            result = await runtime.run(
                backfill_battery,
                runtime.diary,
                bounds,
                data.get("readings"),
                datetime.now(UTC),
            )
        elif operation == "workout_override":
            result = await runtime.run(override, runtime.diary, data)
        else:
            raise Invalid("Unknown Vitality operation.")
    except (Invalid, HomeAssistantError, vol.Invalid) as err:
        connection.send_error(
            msg["id"],
            "vitality_error",
            "Check the requested fields." if isinstance(err, vol.Invalid) else str(err),
        )
    else:
        if operation in ("save_type", "backfill_battery", "workout_override"):
            async_dispatcher_send(hass, SIGNAL)
        connection.send_result(msg["id"], result)
