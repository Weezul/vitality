import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

const module = await readFile(new URL("../../dashboard/vitality-card.js", import.meta.url), "utf8");

async function mount(page) {
  await page.route("https://vitality.test/**", async (route) => {
    if (route.request().url().endsWith(".js")) {
      await route.fulfill({ contentType: "text/javascript", body: module });
    } else {
      await route.fulfill({ contentType: "text/html", body: "<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'><script type='module' src='/card.js'></script>" });
    }
  });
  await page.goto("https://vitality.test/");
  await page.evaluate(async () => {
    await customElements.whenDefined("vitality-card");
    const { calendarDay, shiftDay } = await import("/card.js");
    const today = calendarDay("Europe/Zurich");
    const types = [{ id: "coffee", name: "Coffee", category: "Caffeine", aliases: [], archived: false, unit: "cup" }];
    const metrics = {
      bedtime: { value: shiftDay(today, -1) + "T22:03:00Z", value_type: "timestamp", unit: "", source: "garmin", provenance: "paired actual bedtime" },
      sleep_score: { value: 83, value_type: "numeric", unit: "score", source: "garmin", provenance: "source date" },
    };
    const time = today + "T12:00:00Z";
    let records = [
      { id: "workout_1", source: "garmin", name: "Local workout", original_name: "Fixture run",
        original_type: "running", occurred_at: time, duration_minutes: 37, late: true, distance_m: 5000 },
      { id: "checkin_1", source: "checkin", kind: "morning", score: 80, occurred_at: time,
        notes: "<img src=x onerror='window.injected=true'>" },
    ];
    window.calls = [];
    const card = document.createElement("vitality-card");
    card.setConfig({});
    card.hass = {
      async callApi(method, path) {
        window.calls.push([method, path]);
        return [[{ state: "71", last_changed: time }, { state: "unavailable", last_changed: time }]];
      },
      async callWS({ operation, data }) {
        window.calls.push([operation, data]);
        if (operation === "info") return { timezone: "Europe/Zurich" };
        if (operation === "types") return types;
        if (operation === "garmin") return {
          workflows: {}, workouts: { late_types: [], type_map: {}, sleep_anchor: "18:00" },
          metrics: { body_battery: { unit: "%", mode: "sample", type: "numeric", enabled: true,
            entity: "sensor.battery_fixture" } }, imports: {}, status: {},
        };
        if (operation === "samples") return { samples: [{ value: 70, value_type: "numeric", unit: "%", observed_at: time }],
          bounds: [today + "T00:00:00Z", shiftDay(today, 1) + "T00:00:00Z"], truncated: false };
        if (operation === "daily") {
          const results = [];
          for (let day = data.start; day <= data.end; day = shiftDay(day, 1)) {
            const current = day === today;
            results.push({ date: day, morning: current ? records.find((r) => r.kind === "morning")?.score : null,
              evening: current ? 45 : null, count: current ? records.filter((r) => r.source === "manual").length : 0,
              quantities: {}, workout_count: current ? 1 : null, late_workouts: current ? 1 : null,
              metrics: current ? metrics : {} });
          }
          return results;
        }
        if (operation === "history") return { records: data.end >= today ? records : [], next: null };
        if (operation === "log_event") {
          records.push({ id: "manual_1", source: "manual", name: "Coffee", activity_type_id: "coffee",
            occurred_at: time, quantity: 1, unit: "cup" });
          return { id: "manual_1" };
        }
        if (operation === "delete_event") records = records.filter((row) => row.id !== data.id);
        if (operation === "update_checkin") records = records.map((row) => row.id === data.id ? { ...row, ...data } : row);
        if (operation === "save_type") { types.push(data); return data.id; }
        if (operation === "analyze") return { start: data.start, end: data.end, outcome: "Evening score on day D",
          n: 8, r: 0.45, warning: true };
        if (operation === "export") return { csv: "id\r\ncheckin_1\r\n", next: null };
        if (operation === "backfill_battery") return { inserted: data.readings.length };
        return {};
      },
    };
    document.body.append(card);
  });
  await expect(page.getByRole("heading", { name: "Vitality diary" })).toBeVisible();
  await expect(page.getByText("Morning 80 / 100 · Evening 45 / 100")).toBeVisible();
}

test("mobile charts, date presets, Garmin detail and text escaping", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mount(page);
  await expect(page.getByRole("heading", { name: "Today's Garmin overview" })).toBeVisible();
  await expect(page.getByText("sleep score · 83 score · garmin · source date")).toBeVisible();
  await expect(page.getByRole("img", { name: "Body Battery (%) · intraday" })).toBeVisible();
  await expect(page.getByText(/5 km · Late exercise/).first()).toBeVisible();
  await expect(page.getByText("<img src=x onerror='window.injected=true'>").first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
  for (const days of [7, 90, 30]) {
    const button = page.getByRole("button", { name: days + " days", exact: true });
    await button.click();
    await expect(button).toHaveAttribute("aria-pressed", "true");
    const last = await page.evaluate(() => window.calls.filter(([name]) => name === "daily").at(-3)[1]);
    expect((Date.parse(last.end) - Date.parse(last.start)) / 86400000 + 1).toBe(days);
  }
  expect(errors).toEqual([]);
});

test("catalogue, quick log undo, persisted edit, analysis and CSV", async ({ page }) => {
  await mount(page);
  await page.getByText("Manage activity types").click();
  await page.getByLabel("Stable ID").fill("red_bull");
  await page.getByLabel("Name", { exact: true }).fill("Red Bull");
  await page.getByRole("button", { name: "Save", exact: true }).last().click();
  await expect(page.getByRole("button", { name: "+ Red Bull" })).toBeVisible();
  await page.getByRole("button", { name: "+ Coffee" }).click();
  await expect(page.getByRole("status")).toHaveText("Logged Coffee.");
  await page.getByRole("button", { name: "Undo last log" }).click();
  await expect(page.getByRole("status")).toHaveText("Log undone.");
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
  const editor = page.getByRole("article").filter({ hasText: "morning · 80/100" }).first();
  await editor.getByLabel("Score (0–100)").fill("82");
  await editor.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Morning 82 / 100 · Evening 45 / 100")).toBeVisible();
  await page.getByText("Exploratory comparisons", { exact: true }).click();
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await expect(page.getByText(/Exploratory Pearson r = 0.45/)).toBeVisible();
  await page.getByText("Export selected dates").click();
  const downloadPromise = page.waitForEvent("download");
  await page.getByLabel("Export table").selectOption("checkins");
  await page.getByRole("button", { name: "Download CSV" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^vitality-checkins-/);
});

test("series paths preserve missing readings and time gaps", async ({ page }) => {
  await mount(page);
  const result = await page.evaluate(async () => {
    const { paths } = await import("/card.js");
    return paths([0, null, 30, 25], (i) => i, (v) => v, [0, 1, 2, 10], 5);
  });
  expect(result).toEqual([[[0, 0]], [[2, 30]], [[3, 25]]]);
});

test("optional Body Battery backfill sends valid states from the HA history API", async ({ page }) => {
  await mount(page);
  await page.getByRole("button", { name: "Import HA history for this day" }).click();
  await expect(page.getByRole("status")).toHaveText("Imported 1 Body Battery change(s) from HA history.");
  const requests = await page.evaluate(() => window.calls.filter(([operation]) =>
    operation === "GET" || operation === "backfill_battery"));
  expect(requests[0][1]).toContain("filter_entity_id=sensor.battery_fixture");
  expect(requests[0][1]).toContain("skip_initial_state=");
  expect(requests[1][1].readings).toHaveLength(1);
  expect(requests[1][1].readings[0].value).toBe(71);
});
