"""Exercise the integration against a local Home Assistant Core instance."""

import asyncio
from datetime import UTC, datetime, timedelta
from inspect import unwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest
import yaml
from hassil import Intents, recognize
from homeassistant import loader
from homeassistant.bootstrap import async_load_base_functionality
from homeassistant.config_entries import ConfigEntries
from homeassistant.const import EVENT_HOMEASSISTANT_START
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.helpers import entity_registry
from homeassistant.helpers.template import Template

from custom_components.vitality import (
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.vitality.validation import iso


def test_registry_state_events_services_and_websocket_reload(tmp_path):
    async def exercise():
        hass = HomeAssistant(str(tmp_path))
        hass.config_entries = ConfigEntries(hass, {})
        loader.async_setup(hass)
        assert await async_load_base_functionality(hass)
        hass.config.time_zone = "Europe/Zurich"
        hass.auth = SimpleNamespace(
            async_get_user=AsyncMock(
                side_effect=lambda user: SimpleNamespace(is_admin=user == "admin")
            )
        )
        entry = SimpleNamespace(options={}, data={}, entry_id="vitality_fixture")
        registry = entity_registry.async_get(hass)

        def garmin_state(name, value, attributes=None):
            row = registry.async_get_or_create(
                "sensor",
                "garmin_connect",
                name,
                suggested_object_id=f"fixture_{name}",
                translation_key=name,
            )
            hass.states.async_set(row.entity_id, value, attributes)
            return row

        def connection(admin):
            return SimpleNamespace(
                user=SimpleNamespace(is_admin=admin),
                send_error=Mock(),
                send_result=Mock(),
            )

        now = datetime.now(UTC)
        # Ensure the synthetic wake and updates land on the same Swiss calendar day.
        today = now.astimezone(ZoneInfo("Europe/Zurich"))
        if today.hour == 0:
            wake = today.replace(
                minute=max(0, today.minute - 1), second=0, microsecond=0
            )
        else:
            wake = today.replace(minute=0, second=0, microsecond=0)
        garmin_state("wake_time", iso(wake))
        garmin_state("bedtime", iso(wake - timedelta(hours=8)))
        garmin_state("sleep_score", "84")
        garmin_state("sleep_duration", "440")
        battery = garmin_state("body_battery", "80")
        workout_at = now - timedelta(hours=1)
        garmin_state(
            "last_activities",
            "2",
            {
                "last_activities": [
                    {
                        "activityId": 1,
                        "activityName": "Run",
                        "startTime": iso(workout_at),
                        "duration": 1800,
                    },
                    {
                        "activityId": 2,
                        "activityName": "Walk",
                        "startTime": iso(workout_at),
                        "duration": 900,
                    },
                ]
            },
        )
        assert await async_setup(hass, {})
        assert await async_setup_entry(hass, entry)
        hass.bus.async_fire(EVENT_HOMEASSISTANT_START)
        await hass.async_block_till_done()

        handler, schema = hass.data["websocket_api"]["vitality/diary"]

        async def ws(operation, data, admin=True):
            client = connection(admin)
            await unwrap(handler)(
                hass,
                client,
                schema(
                    {
                        "id": 1,
                        "type": "vitality/diary",
                        "operation": operation,
                        "data": data,
                    }
                ),
            )
            return client

        dates = {"start": today.date().isoformat(), "end": today.date().isoformat()}
        client = await ws("daily", dates)
        day = client.send_result.call_args.args[1][0]
        assert day["metrics"]["sleep_score"]["value"] == 84
        assert day["metrics"]["sleep_duration"]["value"] == 440
        assert "body_battery.last" not in day["metrics"]
        assert len(await entry.runtime_data.run(entry.runtime_data.diary.types)) == 0
        for operation, data in (
            ("history", dates),
            ("export", dict(dates, table="checkins")),
        ):
            denied = await ws(operation, data, False)
            denied.send_error.assert_called_once_with(
                1, "unauthorized", "Vitality requires an administrator."
            )
        with pytest.raises(Unauthorized):
            await hass.services.async_call(
                "vitality",
                "log_checkin",
                {"kind": "morning", "score": 20},
                blocking=True,
                context=Context(user_id="non_admin"),
            )
        await ws("save_type", {"id": "coffee", "name": "Coffee", "unit": "cup"})
        examples = yaml.safe_load(
            (
                Path(__file__).parents[1] / "dashboard/assist-automations.yaml"
            ).read_text()
        )
        for automation, utterance in zip(
            examples, ("log coffee", "log morning energy 80"), strict=True
        ):
            command = automation["triggers"][0]["command"]
            intents = Intents.from_dict(
                {
                    "language": "en",
                    "intents": {
                        "VitalityExample": {"data": [{"sentences": [command]}]}
                    },
                }
            )
            match = recognize(utterance, intents)
            assert match is not None
            slots = {key: entity.value for key, entity in match.entities.items()}
            action = automation["actions"][0]
            action_data = {
                key: Template(value, hass).async_render({"trigger": {"slots": slots}})
                if "{{" in value
                else value
                for key, value in action["data"].items()
            }
            await hass.services.async_call(
                "vitality",
                action["action"].split(".")[1],
                action_data,
                blocking=True,
                context=Context(user_id="admin"),
            )
        assert (await ws("daily", dates)).send_result.call_args.args[1][0]["count"] == 1
        old = entry.runtime_data
        await old.garmin.save_metric(
            {"key": "body_battery", "entity": battery.entity_id}
        )
        hass.states.async_set(battery.entity_id, "76")
        await hass.async_block_till_done()
        assert (
            old.garmin.describe()["metrics"]["body_battery"]["entity"]
            == battery.entity_id
        )
        renamed = "sensor.fixture_battery_new_name"
        registry.async_update_entity(battery.entity_id, new_entity_id=renamed)
        hass.states.async_remove(battery.entity_id)
        hass.states.async_set(renamed, "73")
        await hass.async_block_till_done()
        assert old.garmin.describe()["metrics"]["body_battery"]["entity"] == renamed
        chart = (await ws("samples", dates)).send_result.call_args.args[1]
        assert [row["value"] for row in chart["samples"]] == [76, 73]
        assert await async_unload_entry(hass, entry)
        assert old.garmin.stopped and not old.garmin.tasks
        with pytest.raises(HomeAssistantError, match="Set up Vitality"):
            await hass.services.async_call(
                "vitality", "resync_garmin", {}, blocking=True
            )
        assert await async_setup_entry(hass, entry)
        await entry.runtime_data.garmin.sync()
        chart = (await ws("samples", dates)).send_result.call_args.args[1]
        assert len(chart["samples"]) == 2
        assert (await ws("daily", dates)).send_result.call_args.args[1][0][
            "morning"
        ] == 80
        workout_date = workout_at.astimezone(entry.runtime_data.zone).date().isoformat()
        workout_dates = {"start": workout_date, "end": workout_date}
        assert (await ws("daily", workout_dates)).send_result.call_args.args[1][0][
            "workout_count"
        ] == 2
        assert await async_unload_entry(hass, entry)

    asyncio.run(exercise())
