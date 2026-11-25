# Vitality architecture

The target inspected read-only is Home Assistant OS with Core 2026.11.3, Python 3.14 and Europe/Zurich. Garmin Connect is loaded. Vitality is a single config entry with one database in the HA configuration directory. Actions and authenticated WebSocket commands share validation and storage. Bundled Lovelace cards separate logging, daily and weekly review, and setup. Opt-in sensors expose latest scores and calendar summaries.

## Decisions before implementation

- SQLite uses short executor jobs and explicit transactions. Import upserts, manual edits and exports do not rely on Recorder or its retention. UTC timestamps and half-open local date ranges handle clock changes. The HA timezone is the diary timezone.
- The observed sleep score and duration states have no date metadata. Actual wake time anchors the night. Separate undated updates require conservative pairing, so identical or stale values may be skipped. Source date or observation attributes can be configured when available.
- Garmin data is read from cached HA entities. Registry identity survives entity renames. Installation can see only the rolling workout list and any current dated observations. Automatic Body Battery collection starts at installation. A separate one-day import uses the documented HA History API when the mapped sensor was recorded. There is no guarantee of earlier coverage.
- The observed workout start time includes an offset. The UI exposes the duration and distance source units so alternate Garmin versions can be mapped without guessing. Workout profiles use an HA entry ID, never a Garmin profile identifier.
- Admin access is required for diary actions and WebSocket data. Trusted userless HA automations can invoke actions and must be configured by an administrator. Optional sensors can be visible to other HA users.
- Assist sentence examples use HA automations. Live sentence execution requires installing the integration and enabling the examples first. A conversation action exists on the target, but which voice pipeline handles a particular sentence requires an installation check.
- Charts use a bundled card and authenticated WebSocket calls. The resource is installed through the supported Lovelace resource UI. There are no external assets or runtime dependencies.

See the [Home Assistant config entry guide](https://contributors.home-assistant.io/core/integrations/config-entries/), [WebSocket API guide](https://developers.home-assistant.io/docs/frontend/extending/websocket-api), [custom card guide](https://contributors.home-assistant.io/frontend/custom-ui/card/) and [Garmin integration sensor definitions](https://github.com/cyberjunky/home-assistant-garmin_connect/blob/main/custom_components/garmin_connect/sensor.py).
