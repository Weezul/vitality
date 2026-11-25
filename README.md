# Vitality

Vitality is a single-user diary for Home Assistant. Log subjective energy, restedness and activities, then compare them with your existing Garmin Connect data. The diary, dashboard, analysis and database all run inside Home Assistant.

## Install on Home Assistant OS

The target is Home Assistant Core **2026.11.3**. Use an administrator account. The Garmin Connect integration is optional for manual logging.

1. Copy the repository’s entire `custom_components/vitality/` directory into `/config/custom_components/vitality/` on Home Assistant, using your existing configuration file access. Keep its subdirectories. Restart Home Assistant.
2. Go to **Settings → Devices & services → Add integration**, search for **Vitality**, and finish the setup. Leave the sensor options off if diary statistics should stay visible only to administrators.
3. Copy `dashboard/vitality-card.js` to `/config/www/vitality-card.js`, creating `www` if needed. Restart if this is the first time you created `www`.
4. Open **Settings → Dashboards → Resources** and add `/local/vitality-card.js?v=7` as a **JavaScript module**. Enable **Advanced mode** in your HA profile if the Resources menu is hidden.
5. Add the cards to the dashboards of your choice using the card picker or manual card YAML below. For a single dashboard with four views, paste `dashboard/vitality-dashboard.yaml` into **Edit dashboard → ⋮ → Raw configuration editor**.
6. Open **Vitality Settings → Manage activity types**. For example, create `coffee` named **Coffee**, category **Caffeine**, default unit `cup`, alias `espresso`. Stable IDs preserve historical grouping after a rename. Archiving hides the type from new logs and preserves its history.

[Home Assistant dashboard resources and custom cards](https://contributors.home-assistant.io/frontend/custom-ui/card/)

For an existing installation, copy the supplied `brand/` folder to `/config/custom_components/vitality/brand/` to add the Vitality icon. Restart Home Assistant and refresh **Settings → Devices & services**. Home Assistant Core 2026.3 and later loads these images automatically. [Home Assistant integration branding](https://contributors.home-assistant.io/core/integrations/brands/)

## Choose your dashboard cards

Add each YAML block as its own manual card. The Vitality Stats card opens to the last seven local calendar days and supports a one-day view, longer ranges, and custom dates. The daily card opens to today and lets you pick another date.

```yaml
type: custom:vitality-log-card
```

```yaml
type: custom:vitality-stats-card
period: day
```

```yaml
type: custom:vitality-stats-card
period: week
```

```yaml
type: custom:vitality-config-card
```

In a **Sections** view, Vitality Stats defaults to the full width of its section. If an existing card has a saved width, edit its layout or set the width in its card YAML:

```yaml
type: custom:vitality-stats-card
period: week
grid_options:
  columns: full
  rows: auto
```

## Use Vitality with built-in cards

Open **Settings → Devices & services → Vitality → Configure** and enable **Expose daily and weekly statistics as Home Assistant sensors**. Find the resulting entities by searching for **Vitality** in the entity picker. Add them to an Entities, Tile, or other compatible card.

- Manual activity counts for today and the last seven days, both overall and for each activity type. For example, look for **Vitality Coffee today** once you create Coffee. Counts measure occurrences.
- Latest and average perceived energy for today, plus the seven-day average of daily perceived energy averages. Days without ratings are omitted.
- Latest and average mood for today, plus the seven-day average of daily mood averages. Days without ratings are omitted.
- Garmin workout counts for today and the last seven days, today's sleep score, and today's latest observed Body Battery. The weekly workout count reports the number of days with recorded workout data in its attributes.

The seven-day window includes today in Home Assistant's timezone. Entities with a missing reading show **Unknown**. The separate latest-score option exposes the last morning and evening check-ins, with their timestamps, even when they were logged on a previous date. Other Home Assistant users may be able to read enabled entities.

### Upgrade from the 0–100 scale

Back up the database before upgrading. Vitality converts saved subjective scores by dividing by 10, rounding to the nearest whole number with halves rounded up, and applying a minimum of 1. For example, 0 becomes 1, 45 becomes 5, and 100 becomes 10. Update automations or scripts that send scores, and replace the existing Assist energy example if you use it. Recorder history for existing latest-score entities can contain earlier 0–100 values.

If a form still asks for a score out of 100, update both the integration directory and the dashboard JavaScript. Restart Home Assistant, edit the existing dashboard resource to use `/local/vitality-card.js?v=7`, and reload the dashboard. For Assist, replace the old morning-energy sentence automation with the supplied perceived-energy version and reload automations.

## Log, review and compare

- Use **Perceived Energy** to log a whole number from 1 (exhausted) to 10 (fully energised) any time. Each rating has its own timestamp. **Day** and **Stats** plot each rating alongside mood at its recorded time. Existing morning and evening ratings appear in both charts at their original timestamps.
- Use **Rate mood** to log a whole number from 1 (very low) to 10 (very good) whenever you like. Every rating has its own timestamp. **Day** shows the intraday chart and individual ratings in the timeline. **Stats** plots both rating series across the selected dates.
- To log an activity, choose a type and save the form, or use a quick-log button and **Undo last log** if needed. Each save is one occurrence. Quantities are grouped by unit. Backdating and time corrections require a timestamp such as `2026-11-24T08:00:00+01:00`, including the offset for ambiguous clock times.
- Use the timeline date to review a single day or the history filters to search a range. Edit a record in place or confirm its deletion. Day boundaries and displayed times use the HA timezone. The dashboard shows chart ranges of 1, 7, 30 or 90 days or a custom range up to 366 days.
- Choose an activity or category and a count or single-unit quantity under **Exploratory comparisons**. Choose a Garmin series to see it in a separate chart for the same date range.
- **Exploratory comparisons** supports same- or next-day averages of perceived energy and mood. It excludes missing pairs and keeps both dates within the chosen range. Quantity comparisons exclude days with activity in other units and no selected unit. Timestamp metrics use local minutes relative to the configurable evening anchor, so 23:55 and 00:05 remain ten minutes apart. An optional threshold shows group counts, means and their difference. Pearson correlation requires at least seven pairs with variation in both values and is flagged below 30 pairs. Logging gaps, sleep, illness and work stress can affect the result. Associations do not establish cause.

## Garmin configuration and coverage

Open **Configure Garmin** to see mappings and **Source and import status**. Defaults are discovered from Garmin Connect’s HA entity registry; a renamed device or entity can still match through registry metadata. Confirm the selected entities if several Garmin accounts or similarly named sensors exist. Explicit overrides accept a sensor entity ID and persist its registry identity when available. Disable individual metrics, switch between state and a named attribute, or configure more scalar metrics with type, unit and collection mode. A date attribute must contain an ISO calendar date. A timestamp attribute must be an offset-aware ISO timestamp or an HA datetime. Use mappings only for Garmin data you want copied into the diary.

| Source | What Vitality records |
| --- | --- |
| Actual wake time and bedtime | Wake’s local calendar date, with the original bedtime and wake timestamps. An undated bedtime must be before wake and within 20 hours. Actual time sensors should be selected, rather than Garmin’s recommended times. |
| Sleep score and duration | The published value in score units or minutes. A source date is preferred. Without one, the HA update must be on the wake date, at or after actual wake and within two hours of the wake entity update. Matching the previous day’s undated value is deferred on a new day. Equal consecutive values, updates outside this window and late undated corrections can leave gaps. The time in bed is separate from sleep duration. |
| Body Battery | Separate timestamped samples. Explicit source timestamps take priority; otherwise changes observed after startup use HA receipt time. A cached start value does not create a new sample. Chart gaps longer than two hours are disconnected. Daily first/last values describe observed samples. A check-in may show the latest prior sample within the configured tolerance (120 minutes by default). |
| Daily Body Battery summaries, HRV, heart rate, stress and readiness | A dated source observation where available. Defaults without source dates can infer a date from a fresh HA change and carry that provenance. A cached value at midnight or startup does not fill a new day. Optional sensors can be disabled or remapped when their semantics differ. |
| Recent and latest workouts | All distinct IDs exposed in the cached list plus the supplemental latest sensor. The defaults interpret offset-aware `startTime` (or explicitly named `startTimeGMT`), duration in seconds and distance in meters. Confirm source units in HA and set the source unit or **Ignore** when uncertain. Raw fields retained locally are limited to identifiers, source name/type, timestamps, duration, distance and heart-rate summaries. |

Vitality reads the HA state cache on startup, on source updates, and every 15 minutes. **Resync cached states** and `vitality.resync_garmin` do the same manually. **Backfill visible workouts in range** reads the existing rolling list and supplemental source for the selected range. The target exposed ten list entries during inspection, so older workouts outside that list may be missing. Missing workout coverage is shown as unknown. For a state-based Body Battery mapping, **Import HA history for this day** can copy up to 1,500 state changes still available through HA History. Those samples carry HA history provenance and cannot recover readings that HA did not record or has purged. [HA History REST API](https://developers.home-assistant.io/docs/api/rest/#get-apihistoryperiodtimestamp)

In **Workout sources and rules**, pair a Garmin type with a catalogue ID using entries such as `running=run, cycling=ride`. Unmapped workouts retain their Garmin label. Set the late-exercise threshold and eligible types there. The threshold uses HA local time and includes workouts starting exactly at the threshold. Changing the rule or mapping recomputes historical classifications. The late flag is part of the workout, so it does not add an occurrence. Use **Edit workout** to add a local timestamp or duration correction, notes, or an explicit link to a manual log. Use **Exclude from totals** to reconcile duplicates in your counts. Excluded workouts remain visible and can be restored. Garmin resyncs preserve local edits and exclusions.

To inspect sources without exporting personal data, use **Developer tools → States** locally with the mapped sensor IDs. Check device class, state availability, units, whether a date/timestamp attribute exists, and whether `last_activities` is a list with a stable ID and offset-aware start in each item. Compare one known activity’s duration and distance against the Garmin display to confirm units. For a bug report, share only attribute names, types, list length and a synthetic record shaped like `tests/fixtures/garmin_workouts.json`. Keep diary values, profile IDs, activity IDs and routes on your own machine. [Garmin integration source](https://github.com/cyberjunky/home-assistant-garmin_connect/blob/main/custom_components/garmin_connect/sensor.py) · [Garmin timestamp normalization source](https://github.com/cyberjunky/ha-garmin/blob/main/src/ha_garmin/client.py)

## Actions and Assist

Users can call the actions from **Developer tools → Actions**. Example data for a coffee, assuming `coffee` already exists in the catalogue:

```yaml
action: vitality.log_event
data:
  activity_type: coffee
  quantity: 1
```

Use `vitality.log_checkin` with `kind: energy` and `score: 8`. Both log actions accept optional `occurred_at` and `notes`. Activity logs also accept `unit` and `duration_minutes`. `vitality.update_event`, `vitality.delete_event`, `vitality.update_checkin` and `vitality.delete_checkin` accept `id` from the record’s CSV export. For updates, send only the fields to replace.

To use the built-in Home Assistant conversation agent, open `dashboard/assist-automations.yaml`. Create the example automations individually in **Settings → Automations & scenes** using **Edit in YAML** (paste one mapping at a time without its list marker), or append the entries to `automations.yaml` and reload automations. As an administrator, open Assist using a pipeline with the built-in agent and say or type **log coffee**, **log perceived energy 8**, or **log mood 6**. Then check the diary timeline. **Developer tools → Assist** can check sentence matching without creating logs. Use the dashboard or Actions tab if your pipeline lacks conversation triggers. For an agent that exposes argument-bearing HA scripts as tools, create and expose a script with a required text field `activity_type` and call `vitality.log_event` with `activity_type: "{{ activity_type }}"`. Configure the agent according to its tool support before relying on arbitrary activity names. The examples are checked locally; live pipeline execution must be verified after installation. [Home Assistant sentence triggers](https://www.home-assistant.io/triggers/conversation/) · [Assist developer tools](https://www.home-assistant.io/docs/tools/dev-tools/#assist-tab)

## Permissions, export and recovery

- History, configuration, export and diary changes through the card require an HA administrator. Actions also enforce admin status on user calls. Trusted userless Home Assistant automations can log, so review who can activate your Assist pipeline or exposed scripts. Optional latest-score and statistics sensors may be readable by other HA users. You can turn them off in the integration’s **Configure** dialog.
- **Export selected dates** downloads CSV for events (including workouts and corrections), check-ins, daily observations or samples. The browser receives data over the existing authenticated connection. CSV is for analysis, and cells starting with spreadsheet formula characters are escaped. Store downloads privately.
- The history, catalogue and mappings live in `/config/vitality.sqlite`, separate from Recorder. The DB is migrated transactionally when the integration starts. Removing the integration entry leaves the file for reinstall or manual recovery.
- For a consistent standalone backup, stop HA Core using your normal HAOS management access, copy `/config/vitality.sqlite` to a private backup location, then start Core. To restore, stop Core, retain the current file as a separate backup, replace it with the saved file, and start Core. A Home Assistant backup that includes its configuration is also useful. Check that an extracted backup contains the database before depending on it. Restoring to a different HA instance may require remapping sensors because their registry IDs can differ. [Home Assistant backups](https://www.home-assistant.io/common-tasks/general/#backups)
- Before upgrading, save the database. Replace the integration directory and card asset with the matching release, restart Core and bump the dashboard resource URL’s version parameter. Keep the old database copy if you need to roll back a migrated schema.

## Troubleshooting and validation

| Symptom | Check |
| --- | --- |
| Vitality is missing from Add integration | Check `/config/custom_components/vitality/manifest.json`, case of the directory name, and HA logs after restarting. |
| Custom element does not exist | Check the file in `/config/www`, open `/local/vitality-card.js?v=7` as an administrator and check that it serves JavaScript. Confirm the resource uses the JavaScript module type and hard refresh. |
| Administrator required | Sign in as an HA administrator and confirm that the dashboard connection uses that account. |
| Garmin metric is missing, deferred or stale | Check **Configure Garmin → Source and import status**, verify the value/date/observation mappings and HA entity availability, then resync. Bedtime and sleep score may arrive at different times. |
| Database error | Check available disk space, HA configuration directory write access and HA logs. If the file came from a newer Vitality version, restore a compatible backup or use the newer version. |

For local validation using Python 3.14 and Node.js, run:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
python -m ruff check
npm ci
npx playwright install chromium
npm test
```

The backend tests use synthetic Garmin fixtures, temporary SQLite databases and Home Assistant Core. The card tests use Chromium and a fixture WebSocket client at 360 px and 1280 px. After installation, open **Vitality Day**, confirm workout units against the Garmin app, watch a fresh Body Battery change appear, and test the optional Assist examples. [Architecture decisions](ARCHITECTURE.md)
