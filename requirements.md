# Vitality: Requirements for Home Assistant

**Status:** Current requirements, revised 25 November 2026 to reflect the implemented dashboard and diary workflows. See the [README](README.md) for setup and the [architecture notes](ARCHITECTURE.md) for implementation decisions and verification limits.

## 1. Objective

Build a lightweight, single-user lifestyle diary that runs entirely within an existing Home Assistant OS installation. Its purpose is to discover associations between subjective energy/restedness, daily activities, caffeine consumption, exercise timing and available Garmin health metrics over multiple days.

Logging must be effortless. The user must be able to explicitly configure new activity types (e.g. Red Bull instead of Coffee) through the integration UI without changing code, adding API endpoints or restarting Home Assistant. The system must support reviewing and correcting historical entries.

## 2. Scope and architecture

- Implement a custom Python Home Assistant integration, named `vitality`, under `custom_components/vitality/`.
- Use Home Assistant config entries and a UI-based configuration flow. Support one diary instance initially.
- Use Home Assistant's existing authentication, frontend, Assist pipeline and Garmin integration. Do not require a separate server, add-on, Docker container, cloud account, ESPHome device or standalone mobile application.
- Store diary records in a dedicated SQLite file in Home Assistant's persistent configuration storage, separate from the recorder database. Do not modify or query recorder internals directly.
- Use asynchronous Home Assistant APIs; run blocking database and filesystem operations in an executor, serialize writes, use parameterized SQL, transactions and versioned schema migrations. Ensure safe shutdown and reload.
- Use standard Home Assistant dashboard cards where practical. Supply an installable dashboard example. If dynamic series, historical editing or analytics cannot be implemented adequately with native cards, provide a small bundled Lovelace custom card using authenticated Home Assistant WebSocket commands. Avoid external CDNs and mandatory HACS dependencies.
- Inspect the target Home Assistant version and existing repository before implementation. Use documented APIs compatible with the target version; do not invent Garmin entities or assume Assist supports arbitrary service calls.

## 3. Subjective check-ins

### Functional requirements

- Record perceived energy on a 1–10 integer scale (1 = completely exhausted, 10 = fully energised).
- Allow a separate optional 1–10 mood rating. Allow an optional note with each rating.
- Allow multiple timestamped energy and mood ratings at any time of day.
- Include previously recorded morning and evening scores in perceived energy trends at their original timestamps.
- Permit backdated entries, corrections and deletion. Preserve all check-ins unless explicitly deleted. Plot each energy or mood rating at its recorded time. Use the latest rating and arithmetic average for the daily summaries. Treat missing ratings as unknown.
- Provide a mobile-friendly slider or numeric input and a clear save action. Changing a slider alone must not create a record.
- Expose latest and average perceived energy and mood as optional Home Assistant sensors. Optionally expose helpers or a script for convenient Assist interaction.
- Optional reminders through ordinary Home Assistant automations; no mandatory notification schedule.

## 4. Configurable activity types and generic event logging

Maintain an explicit activity catalogue managed through the integration UI (config/options flow or bundled management card). No activity types are hardcoded. Example configuration, illustrative rather than mandatory defaults:

```yaml
activity_types:
  - id: coffee
    name: Coffee
    category: Caffeine
    unit: cup
  - id: red_bull
    name: Red Bull
    category: Caffeine
    unit: can
  - id: late_exercise
    name: Late exercise
    category: Exercise
  - id: sauna
    name: Sauna
    category: Recovery
```

- Each type has a stable unique ID, display name, optional category, optional default unit, optional aliases, archive status and a **Show in Quick Log** flag.
- Allow adding, renaming, editing and archiving types without restarting Home Assistant. Do not automatically create types from logging requests. Reject unknown or ambiguous types with a helpful error.
- Resolve names and aliases case-insensitively, trimming whitespace; enforce unambiguous matching. Preserve stable IDs when renaming. Archive rather than delete types referenced by history; archived types remain available in historical filters but cannot be used for new manual logs.
- Configuration changes must persist across restarts. The YAML above illustrates the logical model; YAML editing is not required. Store the catalogue in persistent integration-managed storage with schema migrations.
- Populate the manual picker with all unarchived types. Show Quick Log shortcuts for unarchived types with the flag enabled. Default the flag to enabled for new and existing types. Honor it independently of manual logging, history and entity exposure.

Provide one action `vitality.log_event` for all configured manual activities:

| Field | Required | Meaning |
|---|---|---|
| activity_type | Yes | Configured stable ID, name or alias |
| quantity | No | Positive finite numeric value, default 1 |
| unit | No | Defaults to configured unit; optional override |
| occurred_at | No | ISO 8601 timestamp with offset; defaults to now |
| notes | No | Optional context |
| duration_minutes | No | Non-negative duration where relevant |

```yaml
action: vitality.log_event
data:
  activity_type: coffee
```

- Each successful manual invocation creates a distinct event. Three coffee invocations produce three daily occurrences.
- Support occurrence count and quantity sum separately. One event with quantity 2 counts as one occurrence and two units. Never sum incompatible units.
- Group by stable activity type ID, not mutable display name. Retain historical quantities and units; configuration changes must not silently rewrite recorded facts.
- Support viewing, editing and deleting individual events, including backdating. Editing must not create duplicates.
- Do not infer caffeine dosage from beverage names.

## 5. Home Assistant actions and voice

Provide documented service/action schemas (`services.yaml`) with validation and appropriate selectors:

- `vitality.log_event`: generic event creation for a configured activity type.
- `vitality.log_checkin`: score, check-in type, optional timestamp and notes.
- `vitality.update_event`, `vitality.delete_event`: record-ID based changes.
- Equivalent update/delete operations for check-ins, via authenticated actions or WebSocket commands.

Use the existing Home Assistant Assist pipeline rather than building speech recognition, an LLM or a new conversation agent. Provide example scripts/custom sentences for simple requests such as “log coffee” and “log perceived energy 8”. Where the installed conversation agent supports exposed scripts or tools with arguments, document how to invoke the generic logging action. Do not assume that exposing an entity or script automatically enables arbitrary activity arguments. Provide a working non-voice dashboard fallback. Voice is a convenience, not a blocker for MVP delivery.

## 6. Garmin integration (required in MVP)

The user already has Garmin Connect connected to Home Assistant. Reuse that connection. No new Garmin credentials, API client, direct network requests, polling of Garmin servers, or additional account are required. Automatically populate daily records as data becomes available; no user action or morning check-in is required to trigger imports.

### 6.1 Verified source capabilities

A read-only inspection of the user's Home Assistant installation on 24 November 2026 confirmed the following entity IDs and attribute names. The listed sleep and Body Battery entities had available values at inspection. These are useful discovery defaults, not constants or mandatory entity IDs. The installed version, refresh cadence, exact source value semantics and historical coverage remain to be verified during development.

| Vitality metric | Observed Home Assistant entity (prefix `sensor.garmin_connect_`) | Import behaviour |
|---|---|---|
| Sleep score | `sleep_score` | Daily, wake date |
| Actual bedtime | `bedtime` (timestamp) | Daily, wake date; retain actual previous-day timestamp |
| Actual wake time | `wake_time` (timestamp) | Daily, wake date |
| Sleep duration | `sleep_duration` (minutes); `total_sleep_duration` also exists | Daily; verify semantics, avoid double counting |
| Body Battery | `body_battery` (%) | Timestamped samples, during the day |
| Body Battery summaries | `body_battery_charged`, `body_battery_drained`, `body_battery_highest`, `body_battery_lowest` | Daily snapshots; not cumulative across days |
| Overnight HRV | `hrv_last_night_average`; `hrv_status` has `calendarDate` | Daily, when available |
| Resting heart rate | `resting_heart_rate` | Daily, when available |
| Stress | `average_stress_level`, `max_stress_level`, other stress sensors | Daily snapshots, when available |
| Training readiness | `morning_training_readiness`, `training_readiness` (has `calendarDate` and timestamps) | Daily; distinguish morning and latest values |
| Recent workouts | `last_activities` attribute of `last_activities` | Import all available distinct activity records |
| Most recent workout | attributes of `last_activity` | Supplemental source; deduplicate against list |

The recent-activities attribute was a list containing 10 records at inspection. Both workout sources expose `activityId`, `activityName`, `activityType`, `startTime`, `duration`, `distance`, `averageHR`, `maxHR` and other fields. Do not infer from this that all historical activities or raw Body Battery samples are accessible. Never import GPS coordinates, route polylines, personal profile IDs or other unnecessary sensitive metadata by default.

### 6.2 Discovery and mappings

- Discover entities from the Garmin integration/entity registry and allow UI-based overrides, including selecting the state or an attribute as a source. Support entity ID renames, missing or disabled entities, and an explicit enable/disable setting per metric. Offer the verified metrics above as defaults where found. Do not hardcode a required entity prefix. Additional scalar metric mappings should be configurable with stable metric keys, value type (numeric or timestamp), units and collection mode (daily snapshot or time series); no code changes for ordinary additional scalar metrics. Workout extraction and date attribution may require a source-specific adapter.
- Validate mappings and provide a status view showing source availability, last successful import time, latest observation date and errors. Distinguish missing, stale and unavailable data from measured zero. Show whether each metric is Garmin-sourced, derived or manually recorded.
- Use Home Assistant state-change subscriptions, startup reconciliation and a local scheduled reconciliation (proposed every 15 minutes, reading cached HA states only) to recover from startup order, missed updates and reloads. Clean up listeners and timers when unloaded. Provide a manual resync action; it must not force external Garmin API requests.

### 6.3 Daily metrics and sleep

- Create or update the correct daily record as each metric becomes available. Store actual bedtime and wake time as offset-aware timestamps normalized to UTC; present them in the HA timezone, showing date offsets where needed. Do not use optimal/recommended bedtime or wake time as actual values.
- Attribute overnight sleep to the local date of actual wake time, even when bedtime is on the preceding date. Prefer authoritative source dates; use the actual wake timestamp as the sleep record anchor. Do not copy yesterday's sleep score or bedtime into today simply because an entity was read today. Stage/defer related fields when dates or freshness are ambiguous; document the adapter's pairing strategy for asynchronous updates and source fields that have no date. Late-arriving or corrected source data must update its original date without creating a duplicate. No midnight reset that overwrites history.
- Preserve sleep duration reported by Garmin; do not equate time between bedtime and wake time with actual sleep. If desired, show time in bed separately. Daily snapshots have stable uniqueness by local date, metric key and source; update an existing value only when the source observation is valid and appropriately dated. Never replace a valid observation with unknown/unavailable. For daily metrics with no reliable date, label inferred dates or skip ambiguous imports; do not silently assign stale values to a new day.
- Store timestamped Body Battery observations independently of the daily snapshots. Capture valid changes and, if necessary, periodic snapshots of freshly updated data; deduplicate repeated observations with the same source timestamp. Use source observation timestamp if present, otherwise label the HA receipt time as such. Do not fabricate readings for offline gaps or pretend the integration exposes the watch's original intraday samples. On restart, do not insert stale cached readings as fresh values. Display the timeline and derived daily first/last observed values (not necessarily wake/bedtime values); prefer Garmin's own dated high/low/charged/drained summaries when available. Any Body Battery comparison against a check-in must use a prior valid sample within a documented configurable tolerance, not a future sample.

### 6.4 Activities

- Import all records in the recent-activities list, not merely the newest workout. Use the single latest-activity sensor as a supplemental source. Preserve actual start time, duration, original type/name and stable activity ID; normalize distance/duration and other optional metrics only after verifying source units and timestamp semantics. Do not assume a naive timestamp is UTC or local without evidence.
- Upsert keyed by source account/profile mapping (local opaque ID, no raw personal identifier) and external activity ID. Repeated syncs or overlapping list/latest sensors must not duplicate workouts; prefer fresher or more complete data and do not overwrite known fields with null. Use a documented conservative fingerprint only if no ID exists and sufficient fields exist; otherwise report the limitation. Do not fabricate workouts from daily totals.
- Map Garmin activity types to configured catalogue IDs via the UI. Do not automatically create manual activity types. Preserve unmapped workouts with source labels, show them in the activity timeline and include them in overall workout totals; allow later mapping without duplication. A derived late-exercise flag applies to eligible workouts starting at or after a configurable local-time threshold (proposed 18:00). Make eligible workout types configurable; do not count the derived flag as an additional workout. Define whether changing the rule recomputes historical classifications (proposed: yes, and disclose in UI).
- Distinguish manual events from Garmin imports. Do not silently merge overlaps. Allow explicit reconciliation or exclusion from aggregate counts; keep raw source records separate from local annotations/overrides so sync cannot undo user corrections. Deleting/excluding an imported workout must persist across resync via an exclusion/tombstone keyed by source ID; provide a way to restore it. An activity disappearing from Garmin's rolling list is not evidence of deletion.
- Where history is available through supported HA APIs or existing exposed data, offer bounded backfill with provenance and the same upsert rules. At installation import all currently available recent workouts automatically. Earlier history, missed workouts outside the rolling window, and intraday Body Battery history before installation are best-effort only. Show limitations clearly, not as zero activity. The diary must continue working without Garmin.

## 7. Data model and persistence

Suggested schema (implementation may refine names):

- `activity_types`: stable ID, display name, category, default unit, aliases, archive status and Quick Log visibility.
- `events`: ID, activity type ID, quantity, unit, occurrence timestamp, duration, notes and creation/update timestamps. Store imported activities separately in `workouts` and combine them with manual records at query time.
- `checkins`: id, kind (energy/mood; morning/evening/other for existing records and callers), score, occurred_at_utc, notes, created_at_utc, updated_at_utc.
- `daily_observations`: id, local_date, metric_key, typed value (numeric or timestamp), unit, source, observed_at_utc, imported_at_utc, date/observation provenance; unique by local_date, metric_key and source.
- `metric_samples`: metric_key, source, typed numeric value, unit, observed_at_utc, timestamp provenance, imported_at_utc; unique by source, metric key and observation timestamp; index by metric/time.
- `import_exclusions` and local overrides/annotations: stable source/external ID, exclusion status and user-supplied corrections. Imported source facts must not be overwritten by user edits or vice versa.
- `metric_mappings` and source status (may be stored in HA config entries or dedicated storage): stable keys, source selectors, units, collection policy, last successful sync and provenance. Keep user configuration durable and separate from transient state.
- Schema version and indexes on timestamps, activity type ID and source/external ID. Enforce unique source/external ID for imported events where present.

Store timestamps in UTC, convert using Home Assistant's configured timezone (expected Europe/Zurich). Aggregate by local calendar date, including 23/25-hour daylight-saving days. Use half-open date intervals. Reject invalid or ambiguous user-supplied timestamps without silently guessing offsets. Use the source's actual event time rather than import time where available.

Retain diary history indefinitely by default, independent of recorder purge settings. Document storage location, backup/restore, schema migration and removal behaviour. Verify inclusion in the applicable Home Assistant backup workflow or provide a documented consistent database export. Integration reload, restart and upgrade must not erase records. Removal must not silently delete history. Provide CSV export for events, check-ins, daily observations and time-series samples, and document how to retrieve it securely. No automatic external transmission of diary data.

## 8. Dashboard and historical queries

Provide a usable dashboard with:

- Provide separate **Log**, **Day**, **Stats** and **Settings** views in the example dashboard. **Log** contains the rating forms, manual activity picker and configurable shortcuts. **Settings** contains catalogue management, Garmin mappings and CSV export.
- Display today's latest perceived energy and mood in **Day**. Show timestamps at the top right of history and timeline rows, above right-aligned actions. Confirm deletions.
- Plot perceived energy and mood as two 1–10 line series at their recorded times in the selected range. Cap the chart at 1,500 ratings per series and keep the full history available through CSV.
- Provide activity counts through optional native sensors and activity counts or compatible-unit quantities through exploratory comparisons.
- Today's automatically populated Garmin overview: actual bedtime, wake time, sleep duration and score; Body Battery latest value and intraday chart; recent workouts with time, duration and optional distance; optional HRV, resting heart rate, stress and training readiness. Daily detail must also work for earlier dates. Show last sync, stale/missing states and gaps; a perceived energy or mood rating remains subjective, never automatically filled from Garmin.
- Garmin overlays or aligned charts for workouts, late exercise, sleep and available recovery metrics; keep scales and units explicit. Allow selecting Garmin metrics for the same range as energy and mood. Use activity counts as comparison inputs. Add a daily timeline combining manual logs, check-ins and Garmin workouts.
- Handle edits and deletions with the imported-record override/exclusion rules above. Provide a convenient undo or confirmation for accidental quick logging; display a success acknowledgement only after persistence. Do not require navigation through the configuration flow to log an event.
- Offer **Stats** presets for 1, 7, 30 and 90 days plus custom ranges up to 366 days. Default to seven days and full section width in a Sections view. Align charts to the selected range and distinguish unavailable imported workout or metric coverage from known zero values.
- Event history filters by name, category, source and date. Support pagination or bounded queries.
- Readable mobile layout, standard Home Assistant theme support, accessible labels and non-colour-only series identification.

Provide authenticated, validated historical query interfaces for daily aggregates, event/check-in lists and configured activity types. Prefer Home Assistant WebSocket APIs if a custom card is needed. Bound query ranges and page sizes; never expose an unauthenticated endpoint or return arbitrary filesystem paths.

## 9. Analytics

MVP: visual comparison and daily aggregation are mandatory. Add a simple quantitative comparison after the core diary is stable (phase 2, included in the overall project but not a prerequisite for initial deployment).

- Compare event counts or quantities on day D against average perceived energy or mood on day D or D+1.
- Compare days with versus without a selected logged event (e.g. late exercise), showing sample sizes, mean scores and differences.
- Support the same comparisons for sleep score/duration, actual sleep timing, Body Battery and other numeric daily metrics, using their correctly attributed dates. Sleep bedtime clock-time analysis must handle midnight (e.g. minutes relative to a configurable evening anchor); do not correlate raw clock strings or treat 23:55 and 00:05 as far apart.
- For numeric comparisons, calculate Pearson correlation using paired observations; optionally add Spearman correlation later. Return unavailable for insufficient samples or constant series. Proposed minimum: 7 paired days for a displayed coefficient, labelled exploratory; warn when fewer than 30 pairs.
- Exclude missing scores/metrics, do not impute them. Explain that zero logged events may reflect incomplete logging. Show the date range, lag, sample size and metric definitions.
- Never claim causality, predict medical outcomes or give medical recommendations. Sleep, illness, work stress and other confounders may explain observed associations.
- No AI-generated insights or predictive models required.

## 10. Security, reliability and quality

- Use existing Home Assistant authentication and authorization. Treat diary data as private. Home Assistant entity states may be visible to other authenticated household users; do not assume custom API authorization hides exposed sensors. Document this trade-off and allow optional sensor exposure. Document access for household users; restrict history, export and mutation to authorized users (admin-only is acceptable for this single-user MVP if compatible with the intended dashboard and Assist setup).
- Validate scores, finite quantities, timestamps, identifiers, field lengths and query bounds. Use safe rendering of user-entered text and parameterized SQL. Never log sensitive diary notes or credentials unnecessarily.
- Handle database failures explicitly; do not report success before commit. Provide useful errors and diagnostics without leaking private data.
- Follow Home Assistant integration conventions for config flow, setup/unload, entity unique IDs, translations, service registration and cleanup. Avoid polling when state-change subscriptions suffice.
- Keep dependencies minimal and compatible with Home Assistant OS. No mandatory internet access beyond the existing Garmin/Assist setup.

## 11. Testing and acceptance criteria

Use pytest and suitable Home Assistant test fixtures. Include automated tests for storage, validation, aggregation, migration, import deduplication and integration lifecycle; include frontend tests where custom UI is introduced. Run available linting and tests and report actual results.

Acceptance scenarios:

1. Install via custom integration files, restart Home Assistant, configure through UI without an external server.
2. Configure Coffee and log it three times. With statistics sensors enabled, verify three occurrences in the Coffee today entity. Add Red Bull from Settings and log it without a restart. Turn off its Quick Log flag and verify that its shortcut disappears while manual logging still works. Verify that renaming preserves historical grouping and archiving prevents new manual logs while preserving history.
3. Log one event with quantity 2; occurrence count is 1 and quantity total is 2. Configured name/alias case and whitespace variants resolve correctly; incompatible units are not summed.
4. Save perceived energy 8, mood 5, and a second energy rating of 6. Verify each appears at its own timestamp.
5. Backdate, edit and delete a record; all affected aggregates update correctly.
6. Restart/reload and simulate recorder history purge; diary history remains intact. Verify migration and backup/restore procedure.
7. Import overlapping list/latest Garmin workout fixtures repeatedly; one record per ID, actual source time preserved. Import all distinct recent workouts, not only the newest. Updated source facts update the record without removing user overrides. Excluded/deleted imported workouts stay excluded after resync and can be restored. Missing Garmin data does not block manual logging.
8. Automatically populate sleep score, bedtime, wake time and duration on the wake date without a manual check-in. Test previous-day bedtime, staggered updates, stale previous-night values after midnight, late sync and corrected records. Test missing and invalid values; no zero substitution.
9. Capture a series of Body Battery changes, retain samples and daily summaries separately, and show gaps during outages. Verify deduplication after restart, no stale samples imported as fresh, and the graph for today and earlier days. Verify configurable optional Garmin metric mappings and availability status.
10. A workout starting at or after the configured threshold is classified as late without doubling workout totals. Verify local midnight and both Swiss DST transitions.
11. Select the one-day and multi-day ranges and verify both rating series use the selected times. On narrow and wide viewports, verify history timestamps appear above the right-aligned actions.
12. Verify an existing Assist pipeline can invoke at least one documented logging example where supported; otherwise document the exact limitation and demonstrate the dashboard/action fallback.
13. Export data and verify records, units and timestamps. Verify unauthorized history/export access is denied.
14. Phase 2: use deterministic fixtures to verify same-day and next-day pairing, missing data handling, constant series, minimum sample handling and known correlation results.

## 12. Deliverables and implementation order

Deliver source code, integration manifest, config flow, service definitions, storage/migrations, sensors, Garmin adapter, dashboard configuration and any required bundled card, tests, and a README with installation, configuration, Assist examples, Garmin mapping, backup/export, upgrade and troubleshooting instructions.

Suggested repository layout:

```text
custom_components/vitality/
  manifest.json
  __init__.py
  config_flow.py
  const.py
  storage.py
  sensor.py
  services.yaml
  garmin.py
  analytics.py
  strings.json
  translations/en.json
  ...
dashboard/
tests/
README.md
requirements.md
```

Implement in this order:

1. Inspect repository and target Home Assistant capabilities; document assumptions and unknowns.
2. Build integration lifecycle, storage, activity catalogue management, generic actions, check-ins and tests.
3. Build daily aggregation, historical queries and dashboard with editing/export.
4. Add required MVP Garmin ingestion, daily snapshots, Body Battery sample history, source mappings, reconciliation and deduplication; provide fixtures if live data is unavailable. Validate the automatic daily overview and timeline before declaring MVP complete.
5. Document Assist integration and verify supported commands.
6. Implement phase 2 analytics, test and document limitations.

Do not deploy to or modify the user's live Home Assistant instance without explicit permission. Do not claim live verification when only fixtures or local tests were used. Prefer the smallest maintainable implementation that meets acceptance criteria.

## 13. Delivery guardrails and non-goals

- Inspect the existing repository and preserve its existing conventions where compatible. Do not initialize a new repository, change unrelated files, add credentials or push/deploy without authorization. Keep this requirements document in the repository root. Document implementation decisions or deviations from requirements; do not silently relax acceptance criteria.
- Use a supported Home Assistant WebSocket/custom card registration and resource-loading approach; verify on the target version and document installation/reload steps. Prefer native cards only if they truly satisfy dynamic selection, long-term history and editing. If a small custom card is needed, keep it self-contained and versioned with the integration. Do not load arbitrary JavaScript from remote CDNs. Do not expose long arbitrary history in sensor attributes or rely on recorder retention for the dashboard.
- Distinguish completion of MVP (core logging, persistent history, usable dashboard, automatic Garmin imports and visual comparison) from phase 2 (quantitative analytics). A partial mockup is not a completed MVP. No medical advice, automated lifestyle recommendations, account system, multi-user diaries, cloud hosting, or separate app in scope.
- Include a read-only diagnostic/fixture guide for obtaining Garmin entity structure and verifying actual import semantics without exporting health values, coordinates or credentials unnecessarily. Do not use undocumented private coordinator internals as the default integration contract.

## 14. Proposed defaults and open decisions

Confirmed decisions are marked below; other items are proposed implementation defaults. Keep defaults configurable where practical.

- Confirmed integration name: Vitality (`vitality`).
- Confirmed: activity types must be explicitly configured, not hardcoded or automatically created by logging. Proposed configuration interface: Home Assistant UI.
- Single user, one subjective score per check-in, optional quantities and notes.
- Dedicated SQLite storage, indefinite retention, no separate server.
- Late exercise threshold: 18:00 local time.
- Default range: seven days in Stats, today in Day, and 30 days in Settings export.
- Confirmed: Garmin automatic import is part of MVP, including sleep score, actual bedtime/wake time, Body Battery and activities. The live source entities and recent-activity list were inspected read-only; source schemas/units, update cadence, exact Home Assistant/integration versions and Assist capabilities still require verification. No claim of tested import behaviour yet.
- Proposed: 15-minute local reconciliation, all currently visible recent workouts on first setup, no guarantees of full historical backfill. Optional Garmin metrics enabled when available; user can configure them. No external Garmin polling.
- Proposed: phase 2 quantitative analytics after MVP visual comparisons, optional quantities, single-user access, admin-only sensitive history if compatible with intended Assist/dashboard use.
- Native dashboard first; bundled custom card only if needed to satisfy the dynamic chart and editing requirements.
- No mandatory HACS, ESPHome, external database, standalone app or new voice pipeline.
