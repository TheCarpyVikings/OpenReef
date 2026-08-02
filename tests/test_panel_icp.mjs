/**
 * Unified ICP dashboard: how imported lab results are summarised (panel-only).
 *
 * icp.py is the authority on values — it parses, normalises units and flags each
 * element (tests/test_icp.py covers that). Everything below is the panel's job:
 * turn one backend payload into the numbers, pills, colours and chart a reefer
 * actually reads. The failure modes here are quiet ones — a below-detection
 * copper drawn as a hard zero, an alarming pill on a non-result, a chart that
 * blanks the whole tab on a one-point series — so these pin the promises rather
 * than the markup.
 *
 * The payload shapes below mirror icp.py's _dashboard_point / _build_series
 * output exactly (including "" for absent lab strings and null for absent
 * numbers); guessing that shape is the main way this suite would go wrong.
 *
 * Run standalone:  node tests/test_panel_icp.mjs
 */

import { assert, assertEqual, freezeTime, makePanel, runTests, test } from "./_panel_harness.mjs";

const DAY = 86400000;
const T0 = Date.UTC(2026, 0, 1);

/** One dashboard point, shaped like icp.py's _dashboard_point. */
function point(dayOffset, value, lab, extra = {}) {
  const time = T0 + dayOffset * DAY;
  return {
    reportId: `icp:${lab.toLowerCase()}:${dayOffset}`,
    date: new Date(time).toISOString().slice(0, 10),
    time,
    lab,
    value,
    unit: "ppm",
    bdl: false,
    threshold: null,
    status: "ok",
    labName: "",
    labResult: "",
    labUnit: "",
    sampleType: "tank",
    ...extra,
  };
}

/** One series, shaped like icp.py's _build_series entries. */
function series(overrides = {}) {
  return {
    symbol: "Ca",
    name: "Calcium",
    category: "major",
    unit: "ppm",
    points: [],
    bdlPoints: [],
    reportCount: 0,
    labs: [],
    ...overrides,
  };
}

function payloadFor(selected, overrides = {}) {
  const symbol = selected ? selected.symbol : "Ca";
  return {
    settings: { includedLabs: [], range: "all", group: "core", symbol },
    labs: [
      { lab: "ATI", count: 2, tankCount: 2, latest: "2026-01-11" },
      { lab: "Triton", count: 2, tankCount: 2, latest: "2026-01-01" },
    ],
    groups: [{ id: "core", label: "Core", symbols: selected ? [symbol] : [] }, { id: "trace", label: "Trace", symbols: [] }],
    series: selected ? { [symbol]: selected } : {},
    selectedSeries: selected,
    summary: { reports: 4, tankReports: 4, filteredTankReports: 4, elements: selected ? 1 : 0, points: selected ? selected.points.length : 0, latest: "2026-01-11" },
    analysisCards: [],
    ...overrides,
  };
}

const SOME_REPORTS = [{ id: "icp:triton:1", lab: "Triton", sampleType: "tank", sampleDate: "2026-01-01", elements: [] }];

/**
 * Render the dashboard from a payload. The clock is frozen even though today's
 * render maths is payload-driven: a "3 days ago" label added later must not turn
 * this suite flaky before anyone notices.
 */
async function renderDashboard({ reports = SOME_REPORTS, payload = null, loading = false, error = "" } = {}) {
  const panel = await makePanel({ icpReports: reports });
  panel._icpDashboard = { payload, loading, error, requestId: 0 };
  const restore = freezeTime("2026-02-01T00:00:00Z");
  try {
    return panel._icpRenderDashboard(reports);
  } finally {
    restore();
  }
}

/** Body rows of the point table (the header <tr> carries a style attribute). */
function tableRows(html) {
  const start = html.indexOf("icp-dashboard-table");
  if (start < 0) return [];
  return [...html.slice(start).matchAll(/<tr>([\s\S]*?)<\/tr>/g)]
    .map((match) => [...match[1].matchAll(/<td>([\s\S]*?)<\/td>/g)].map((cell) => cell[1].trim()));
}

/**
 * Plotted points in series order, as the browser would place them: [{ x, y, fill }].
 * Coordinates are captured loosely on purpose — a point the panel positioned at
 * "NaN" must show up here as a broken point, not vanish from the count.
 */
function chartCircles(svg) {
  return [...svg.matchAll(/<circle cx="([^"]*)" cy="([^"]*)" r="[^"]*" fill="([^"]*)"/g)]
    .map(([, x, y, fill]) => ({ x: Number(x), y: Number(y), fill }));
}

/** [colour, label] pairs from any icp-lab-dot run — the chart legend and the table's lab cell share it. */
function labDots(html) {
  return [...html.matchAll(/<span class="icp-lab-dot"><span style="background:([^"]*)"><\/span>([^<]*)<\/span>/g)]
    .map(([, colour, label]) => [colour, label]);
}

function chartLegend(svg) {
  const block = svg.match(/<div class="icp-lab-legend">([\s\S]*?)<\/div>/);
  return block ? labDots(block[1]) : [];
}

/** The four summary tiles as [label, value, note]. */
function metricCards(html) {
  return [...html.matchAll(/<div class="metric-card"><span class="hint">([^<]*)<\/span><strong>([^<]*)<\/strong><small>([^<]*)<\/small><\/div>/g)]
    .map(([, label, value, note]) => [label, value, note]);
}

/** data-ids of one filter row's buttons; `onlyActive` keeps the ones drawn as selected. */
function filterButtons(html, kind, onlyActive = false) {
  return [...html.matchAll(/<button class="([^"]*)" data-action="icp-dashboard-([a-z]+)" data-id="([^"]*)"/g)]
    .filter(([, cls, action]) => action === kind && (!onlyActive || cls.split(/\s+/).includes("active")))
    .map(([, , , id]) => id);
}

function analysisCards(html) {
  return [...html.matchAll(/<article class="icp-analysis-card ([^"]*)">([\s\S]*?)<\/article>/g)].map(([, severity, body]) => ({
    severity,
    kind: (body.match(/<span class="hint">([^<]*)<\/span>/) || [])[1],
    title: (body.match(/<strong>([^<]*)<\/strong>/) || [])[1],
    summary: (body.match(/<p>([^<]*)<\/p>/) || [])[1],
  }));
}

function noPlaceholders(html, what) {
  assert(!/undefined|NaN|\[object |null /.test(html), `${what} leaked a placeholder into the page`);
}

test("test_a_below_detection_point_is_shown_as_bdl_not_as_zero", async () => {
  // The whole reason parse_value returns (None, True, threshold) instead of 0.0:
  // "we could not see any" is not "there is none". A copper of 0.0000 reads as a
  // clean tank; "<0.5" reads as "under the lab's limit", which is the truth.
  const panel = await makePanel({});
  const rec = series({ symbol: "Cu", name: "Copper", unit: "µg/l" });
  const shown = panel._icpDashboardValue(point(0, null, "ATI", { bdl: true, threshold: 0.5, unit: "µg/l" }), rec);
  assertEqual(shown, "<0.5 µg/l", "a below-detection point must show the lab's limit, not a number");
  assert(!/^0/.test(shown), `below detection must never render as a zero: "${shown}"`);
  // Some labs print no limit at all — still an absence, still not a number.
  assertEqual(panel._icpDashboardValue(point(0, null, "ATI", { bdl: true, threshold: null, unit: "µg/l" }), rec),
    "<LOD µg/l", "with no stated limit the point is still below detection, not zero");
  // And the "<" must reach the page escaped, or the browser eats the cell.
  const html = await renderDashboard({
    payload: payloadFor(series({ symbol: "Cu", name: "Copper", unit: "µg/l", bdlPoints: [point(0, null, "ATI", { bdl: true, threshold: 0.5, unit: "µg/l" })] })),
  });
  assert(html.includes("&lt;0.5 µg/l"), "the BDL value must be HTML-escaped into the table");
  assert(!html.includes("<0.5"), "an unescaped < would swallow the rest of the row");
});

test("test_the_value_column_keeps_the_labs_own_wording_and_unit", async () => {
  // "Value shown by lab" is a promise: if the report said "n.n." or printed µg/l
  // where OpenReef stores mg/l, the table shows the lab's words. OpenReef's own
  // normalised number belongs to the trend line, not to this column.
  const panel = await makePanel({});
  const rec = series({ symbol: "Cu", name: "Copper", unit: "mg/l" });
  assertEqual(panel._icpDashboardValue(point(0, 0.0024, "Fauna Marin", { labResult: "n.n.", labUnit: "µg/l" }), rec),
    "n.n. µg/l", "the lab's own wording and unit win over the normalised number");
  assertEqual(panel._icpDashboardValue(point(0, 0.0024, "Fauna Marin", { labUnit: "µg/l" }), rec),
    "0.0024 µg/l", "the lab's unit wins even when only the number came through");
  assertEqual(panel._icpDashboardValue(point(0, 0.0024, "Fauna Marin", { unit: "" }), rec),
    "0.0024 mg/l", "with no per-point unit the series unit is used");
  // A below-detection marker outranks the lab's printed result too.
  assertEqual(panel._icpDashboardValue(point(0, null, "ATI", { bdl: true, threshold: 0.5, labResult: "0", labUnit: "µg/l" }), rec),
    "<0.5 µg/l", "a BDL flag must not be overridden by a lab result string of 0");
});

test("test_numeric_precision_follows_the_magnitude", async () => {
  // Trace metals live below 1 µg/l and calcium lives above 400 ppm. One shared
  // decimal count would either round a trace element to nothing or print calcium
  // to four meaningless places.
  const panel = await makePanel({});
  const rec = series({ unit: "ppm" });
  const cases = [[0.03, "0.0300 ppm"], [0.9999, "0.9999 ppm"], [8.25, "8.25 ppm"], [19.999, "20.00 ppm"], [20, "20.0 ppm"], [420.4567, "420.5 ppm"]];
  for (const [value, expected] of cases) {
    assertEqual(panel._icpDashboardValue(point(0, value, "Triton"), rec), expected, `${value} formatted wrong`);
  }
  assertEqual(panel._icpDashboardValue(null, rec), "—", "no point at all is an em dash, not a number");
  assertEqual(panel._icpDashboardValue(point(0, undefined, "Triton"), rec), "— ppm",
    "a point whose number did not survive the import is an em dash, not a formatter stub");
});

test("test_bdl_and_measured_points_share_one_newest_first_table_capped_at_twelve", async () => {
  // Two backend lists (points / bdlPoints), one table: below-detection results
  // must appear in date order among the measured ones, not be filed at the end
  // or dropped because they have no y-coordinate.
  const measured = Array.from({ length: 15 }, (_, i) => point(i, 400 + i, "Triton"));
  const belowLimit = point(20, null, "ATI", { bdl: true, threshold: 1 });
  const html = await renderDashboard({ payload: payloadFor(series({ points: measured, bdlPoints: [belowLimit] })) });
  const rows = tableRows(html);
  assertEqual(rows.length, 12, "the point table is capped at 12 rows so the tab stays readable");
  const dates = rows.map((row) => row[0]);
  assertEqual(dates[0], belowLimit.date, "the newest point leads the table even when it is below detection");
  const sorted = [...dates].sort().reverse();
  assertEqual(dates, sorted, "point rows must run newest first");
  assert(rows[0][2].includes("&lt;1"), "the below-detection row keeps its limit in the value column");
  noPlaceholders(html, "the point table");
});

test("test_every_point_row_is_attributed_to_the_lab_that_produced_it", async () => {
  // Triton's 430 and ATI's 430 are not the same measurement. A row without its
  // lab (or with the wrong swatch) is a number nobody can act on, and it is the
  // one column no other test reads.
  const panel = await makePanel({});
  const points = [point(0, 400, "Triton"), point(1, 410, "ATI"), point(2, 405, "")];
  const html = await renderDashboard({ payload: payloadFor(series({ points })) });
  const rows = tableRows(html);
  assertEqual(rows.length, 3, "one row per point");
  const attributions = rows.map((row) => labDots(row[1])[0] || ["", ""]);
  assertEqual(attributions.map(([, lab]) => lab), ["Unknown", "ATI", "Triton"],
    "newest first, and every row names its lab — an unnamed lab reads as Unknown, not as blank");
  assertEqual(attributions.map(([colour]) => colour), ["Unknown", "ATI", "Triton"].map((lab) => panel._icpLabColor(lab)),
    "the row swatch must be the same colour that lab gets on the chart");
  // The column is "Date". A lab that dated its sample to the second must not
  // widen the table with a timestamp nobody asked for.
  const stamped = await renderDashboard({
    payload: payloadFor(series({ points: [point(0, 400, "Triton", { date: "2026-01-01T04:05:06+00:00" })] })),
  });
  assertEqual(tableRows(stamped)[0][0], "2026-01-01", "the date column shows a date, whatever precision the lab sent");
  // The lab name is a string from an imported file, and it reaches the page in
  // three places (row, legend, tooltip) without ever being re-checked.
  const punctuated = await renderDashboard({
    payload: payloadFor(series({ points: [point(0, 400, "Reef & Co <Ltd>")] })),
  });
  assert(punctuated.includes("Reef &amp; Co &lt;Ltd&gt;"), "a lab name carrying markup characters is escaped");
  assert(!punctuated.includes("Reef & Co"), "an unescaped ampersand or bracket must not reach the page");
});

test("test_the_summary_cards_count_what_was_actually_imported", async () => {
  // Four tiles are the whole "how much do I have" answer. Hard-coded or stale
  // numbers here are invisible: they look exactly like a real count.
  const rec = series({ points: [point(0, 420, "Triton")] });
  const withCounts = (settings, summary) => payloadFor(rec, {
    settings: { includedLabs: [], range: "all", group: "core", symbol: "Ca", ...settings },
    labs: [{ lab: "ATI", tankCount: 2 }, { lab: "Triton", tankCount: 1 }],
    summary,
  });
  const html = await renderDashboard({
    payload: withCounts({}, { reports: 7, tankReports: 5, elements: 3, points: 9, latest: "2026-01-11T04:05:06" }),
  });
  assertEqual(metricCards(html), [
    ["Reports", "7", "5 tank-water"],
    ["Labs", "2", "all included"],
    ["Trend points", "9", "3 elements"],
    ["Latest", "2026-01-11", "tank ICP"],
  ], "the tiles must echo the payload's own counts, and Latest is a date not a timestamp");
  // With a lab filter on, the Labs tile must stop claiming everything is included.
  const filtered = await renderDashboard({
    payload: withCounts({ includedLabs: ["ATI"] }, { reports: 7, tankReports: 5, elements: 3, points: 9, latest: "2026-01-11" }),
  });
  assertEqual(metricCards(filtered).find(([label]) => label === "Labs"), ["Labs", "2", "1 included"],
    "a filtered dashboard must say how many labs it is showing");
  // A backend that sent no summary at all still gets readable zeroes.
  const bare = await renderDashboard({ payload: withCounts({}, {}) });
  assertEqual(metricCards(bare), [
    ["Reports", "0", "0 tank-water"],
    ["Labs", "2", "all included"],
    ["Trend points", "0", "0 elements"],
    ["Latest", "—", "tank ICP"],
  ], "a missing summary reads as zero and an em dash, never as undefined");
  noPlaceholders(bare, "the summary cards");
});

test("test_the_filter_buttons_show_the_filter_that_is_actually_applied", async () => {
  // Every one of these is a stored setting rendered back as a highlight. If the
  // highlight and the filter disagree, the user is looking at a subset of their
  // data believing it is all of it.
  const cu = series({ symbol: "Cu", name: "Copper", unit: "µg/l", points: [point(0, 2, "ATI")] });
  const groups = [{ id: "core", label: "Core", symbols: ["Ca"] }, { id: "trace", label: "Trace", symbols: ["Cu", "Fe"] }];
  const filtered = await renderDashboard({
    payload: payloadFor(cu, { groups, settings: { includedLabs: ["ATI"], range: "180d", group: "trace", symbol: "Cu" } }),
  });
  assertEqual(filterButtons(filtered, "lab", true), ["ATI"], "only the included lab is lit, and not the All button");
  assertEqual(filterButtons(filtered, "range", true), ["180d"], "the stored range is the lit range");
  assertEqual(filterButtons(filtered, "group", true), ["trace"], "the stored group is the lit group");
  assertEqual(filterButtons(filtered, "symbol", true), ["Cu"], "the charted element is the lit element");
  assertEqual(filterButtons(filtered, "symbol"), ["Cu", "Fe"],
    "the element row offers the selected group's elements, not the first group's");
  // Empty includedLabs means ALL — which is the All button lighting up, not every lab.
  const all = await renderDashboard({ payload: payloadFor(cu, { groups }) });
  assertEqual(filterButtons(all, "lab", true), ["__all"], "'no filter' must light All labs and leave the lab buttons alone");
  assertEqual(filterButtons(all, "lab"), ["__all", "ATI", "Triton"], "every lab in the payload still gets a button");
  assertEqual(filterButtons(all, "range", true), ["all"], "the default range is lit");
  // The chart panel has to name the element the filters landed on, or the reader
  // has one number and no idea what it is a number of.
  assert(filtered.includes("<h3>Copper trend</h3>"), "the trend panel names the selected element");
  assert(filtered.includes("Cu · µg/l"), "and states the symbol and unit it is plotting");
  // A filter can legitimately hide every point of the selected element; that has
  // to read as "your filter did this", not as a blank table.
  const nothingLeft = await renderDashboard({
    payload: payloadFor(series({ symbol: "Cu", name: "Copper", unit: "µg/l" }), { groups }),
  });
  assert(/No point details in this filter/i.test(nothingLeft), "an element with no points left says so in the table");
  assert(/No line-chart points yet/i.test(nothingLeft), "and in the chart, rather than drawing an empty axis");
});

test("test_a_dashboard_that_could_not_load_says_so_instead_of_showing_nothing", async () => {
  // This is the ICP tab's default view. A silent failure here is indistinguishable
  // from "your reef has nothing worth reporting".
  const html = await renderDashboard({ payload: null, error: "websocket died" });
  assert(html.includes("websocket died"), "the backend's reason must reach the page");
  assert(html.includes('data-action="icp-dashboard-refresh"'), "and a retry must be one click away");
  assert(!html.includes("<svg") && !html.includes("icp-dashboard-table"), "a failed load must not also draw a chart");
  const stale = await renderDashboard({ payload: payloadFor(series({ points: [point(0, 420, "Triton")] })), error: "websocket died" });
  assert(stale.includes("websocket died") && !stale.includes("icp-dashboard-table"),
    "a payload from the previous load must not paper over a failed refresh");
  const nasty = await renderDashboard({ payload: null, error: '<img src=x onerror="boom">' });
  assert(nasty.includes("&lt;img") && !nasty.includes("<img"), "an error string from the server is escaped");
  const loading = await renderDashboard({ payload: null, loading: true });
  assert(/loading/i.test(loading) && !/import your first/i.test(loading),
    "a load still in flight is not an account with nothing imported");
});

test("test_analysis_cards_come_from_the_payload_rather_than_being_invented", async () => {
  // OpenReef Analysis is the opinionated half of the tab. Dropping the backend's
  // cards for the friendly "nothing found" card would hide the one contaminant
  // clue the dashboard exists to surface.
  const rec = series({ points: [point(0, 420, "Triton")] });
  const html = await renderDashboard({
    payload: payloadFor(rec, {
      analysisCards: [
        { kind: "trend", severity: "warning", title: "Copper climbing", summary: "Up across 3 reports", detail: "since 1 Jan" },
        { kind: "spike", severity: "critical", title: "Aluminium <spike>", summary: "New in this report" },
      ],
    }),
  });
  const cards = analysisCards(html);
  assertEqual(cards.length, 2, "both payload cards must render");
  assertEqual(cards[0], { severity: "warning", kind: "trend", title: "Copper climbing", summary: "Up across 3 reports" },
    "a card keeps its own severity, kind, title and summary");
  assertEqual(cards[1].severity, "critical", "a contaminant card must keep the severity that colours it red");
  assert(html.includes("<small>since 1 Jan</small>"), "the optional detail line is shown when the backend sent one");
  assert(html.includes("Aluminium &lt;spike&gt;"), "card text is escaped");
  assert(!/No dashboard concerns/.test(html), "with real cards the reassuring placeholder must not appear");
  const none = await renderDashboard({ payload: payloadFor(rec) });
  const fallback = analysisCards(none);
  assertEqual(fallback.length, 1, "with nothing found the grid still explains itself rather than sitting empty");
  assertEqual(fallback[0].title, "No dashboard concerns", "and says so in words");
});

test("test_a_below_detection_row_is_pilled_as_absent_not_as_a_range_failure", async () => {
  // BDL is the absence of a reading. Painting it amber/red would have people
  // chasing a "problem" their lab never reported.
  const html = await renderDashboard({
    payload: payloadFor(series({ symbol: "Cu", name: "Copper", unit: "µg/l", bdlPoints: [point(0, null, "ATI", { bdl: true, threshold: 0.5, status: "bdl", unit: "µg/l" })] })),
  });
  const [row] = tableRows(html);
  assertEqual(row[3], "<span class='pill unknown'>BDL</span>", "below detection gets the neutral pill and the BDL label");
  assert(!/pill (warning|critical)/.test(row[3]), "below detection must not be dressed up as a warning");
});

test("test_each_openreef_status_gets_its_own_pill_class", async () => {
  // These four classes are the tab's whole traffic-light system: ok is green,
  // low/high are the same amber "out of range", contaminant is the red one that
  // means something is in the water that should not be.
  const expected = { ok: "ok", low: "warning", high: "warning", contaminant: "critical", unknown: "unknown", "": "unknown" };
  const points = Object.keys(expected).map((status, i) => point(i, 1 + i, "ATI", { status }));
  const html = await renderDashboard({ payload: payloadFor(series({ symbol: "Cu", name: "Copper", unit: "µg/l", points })) });
  const rows = tableRows(html);
  for (const [status, cls] of Object.entries(expected)) {
    const cell = rows.find((row) => row[3].includes(`>${status || "—"}<`));
    assert(cell, `no pill rendered for status "${status}"`);
    assert(cell[3].includes(`class="pill ${cls}"`), `status "${status}" must use the ${cls} pill, got ${cell[3]}`);
  }
  const classes = new Set(rows.map((row) => (row[3].match(/pill (\w+)/) || [])[1]));
  assertEqual([...classes].sort(), ["critical", "ok", "unknown", "warning"],
    "ok / out-of-range / contaminant / no-verdict must stay four visually different pills");
});

test("test_report_view_pills_escalate_a_labs_own_verdict", async () => {
  // The report view shows the LAB's verdict when it printed one (ATI does).
  // OpenReef re-uses its own pill colours so one page does not mix vocabularies:
  // a lab saying "critically high" must look like OpenReef's critical.
  const panel = await makePanel({});
  const cls = (html) => (html.match(/icp-status-pill (\w+)/) || [])[1];
  assertEqual(cls(panel._icpStatusPill("ok")), "ok");
  assertEqual(cls(panel._icpStatusPill("low")), "warning");
  assertEqual(cls(panel._icpStatusPill("high")), "warning");
  assertEqual(cls(panel._icpStatusPill("contaminant")), "critical");
  assertEqual(cls(panel._icpStatusPill("unknown")), "unknown");
  // A below-detection element is an absence, so its base class is the neutral
  // one — visible as soon as the lab's own wording is used ("n.n." is how ATI
  // and Fauna Marin print "nicht nachweisbar").
  assertEqual(cls(panel._icpStatusPill("bdl", "n.n.")), "unknown",
    "below detection is an absence in the report view too, not an amber finding");
  assert(panel._icpStatusPill("bdl").includes(">Below detection<"), "and it says which absence it is");
  // PINNED QUIRK, not an endorsement: with no lab wording the label is the words
  // "Below detection", and the escalation below matches "below" (there for
  // "Below optimum"), so this one pill comes out amber while the dashboard table
  // paints the same result neutral. Whoever reconciles the two should see this
  // line go red rather than discover the mismatch from a user.
  assertEqual(cls(panel._icpStatusPill("bdl")), "warning",
    "report-view BDL currently escalates on its own label — change this deliberately, not by accident");
  assertEqual(cls(panel._icpStatusPill("ok", "Critically high")), "critical",
    "a lab's contaminant-grade wording must not be painted green because the map said ok");
  assertEqual(cls(panel._icpStatusPill("ok", "Above optimum")), "warning",
    "a lab saying the element is above its range is a warning");
  assertEqual(cls(panel._icpStatusPill("contaminant", "Elevated")), "critical",
    "a contaminant keeps the red pill even when the lab's own wording is mild");
  assert(panel._icpStatusPill("high", '<img src=x onerror="boom">').includes("&lt;img"),
    "lab-supplied status text is escaped");
});

test("test_degenerate_series_still_draw_a_chart", async () => {
  // One import is the normal starting state, and a parameter you are holding
  // steady produces a flat line. Both give a zero range; neither may blank the
  // tab or leak NaN coordinates into the SVG.
  const single = series({ points: [point(0, 420, "Triton")] });
  const flat = series({ points: [point(0, 420, "Triton"), point(30, 420, "ATI")] });
  for (const [name, rec] of [["single-point", single], ["flat", flat]]) {
    const panel = await makePanel({});
    const svg = panel._icpDashboardChart(rec, "all");
    const circles = [...svg.matchAll(/<circle cx="([\d.]+)" cy="([\d.]+)"/g)];
    assertEqual(circles.length, rec.points.length, `${name} series lost a point off the chart`);
    noPlaceholders(svg, `${name} series chart`);
    assert(svg.includes("icp-trend-chart"), `${name} series must still render the chart element`);
  }
  const panel = await makePanel({});
  const soloSvg = panel._icpDashboardChart(single, "all");
  assert(!soloSvg.includes("<polyline"), "one point is not a trend — no line may be drawn through it");
  const [, cx] = soloSvg.match(/<circle cx="([\d.]+)"/);
  assertEqual(cx, "360.0", "a lone sample is centred, not pinned to an edge of an invented time window");
});

test("test_the_trend_chart_runs_time_left_to_right_and_value_bottom_to_top", async () => {
  // The two axes ARE the claim. An inverted y or a mirrored x still produces a
  // plausible SVG full of dots — it just tells a reefer their copper is falling
  // while it climbs, which is worse than drawing nothing at all.
  const panel = await makePanel({});
  const rec = series({ points: [point(0, 400, "Triton"), point(10, 460, "ATI"), point(20, 430, "Triton")] });
  const svg = panel._icpDashboardChart(rec, "all");
  const [oldest, peak, newest] = chartCircles(svg);
  assertEqual(chartCircles(svg).length, 3, "every measured point is plotted");
  assert(oldest.x < peak.x && peak.x < newest.x, `older samples must be drawn left of newer ones: ${JSON.stringify([oldest.x, peak.x, newest.x])}`);
  assert(oldest.x <= 30 && newest.x >= 690, "the oldest and newest samples anchor the ends of the time axis");
  assert(peak.y < newest.y && newest.y < oldest.y, `a higher reading must sit higher up the chart: ${JSON.stringify([oldest.y, peak.y, newest.y])}`);
  assert(oldest.y - peak.y > 150, "the value axis must use the chart's height, not squash the series into a band");
  assert(chartCircles(svg).every((dot) => dot.y >= 27 && dot.y <= 233 && dot.x >= 27 && dot.x <= 693),
    "no point may be drawn outside the padded plot area");
  // Line and dots are built from two separate passes in the panel; they must agree.
  const line = svg.match(/<polyline points="([^"]*)"/)[1].split(" ").map((pair) => pair.split(",").map(Number));
  assertEqual(line.length, 3, "the trend line must join every point");
  line.forEach(([x, y], i) => assert(Math.abs(x - chartCircles(svg)[i].x) < 0.1 && Math.abs(y - chartCircles(svg)[i].y) < 0.1,
    `the trend line leaves the dots at point ${i}: line ${x},${y} vs dot ${chartCircles(svg)[i].x},${chartCircles(svg)[i].y}`));
});

test("test_chart_dots_and_legend_carry_the_lab_that_ran_the_sample", async () => {
  // Cross-brand trends are the tab's reason to exist, and colour is the only
  // thing on the chart saying which brand a dot came from. One colour for every
  // dot silently turns three labs into one line of "results".
  const panel = await makePanel({});
  const rec = series({ points: [point(0, 400, "Triton"), point(5, 410, "ATI"), point(9, 405, "Triton"), point(12, 402, "")] });
  const svg = panel._icpDashboardChart(rec, "all");
  const fills = chartCircles(svg).map((dot) => dot.fill);
  assertEqual(fills, ["Triton", "ATI", "Triton", "Unknown"].map((lab) => panel._icpLabColor(lab)),
    "each dot must be painted with the colour of the lab that produced it");
  assertEqual(new Set(fills).size, 3, "two named labs and an unnamed one must not collapse into one colour");
  const legend = chartLegend(svg);
  assertEqual(legend.map(([, lab]) => lab), ["Triton", "ATI", "Unknown"],
    "the legend names each lab exactly once, however many samples it contributed");
  assertEqual(legend.map(([colour]) => colour), legend.map(([, lab]) => panel._icpLabColor(lab)),
    "a legend swatch must match the dots it is explaining");
  // The tooltip is the only way to read an exact value off the chart — an SVG of
  // bare dots is a shape, not a result.
  const titles = [...svg.matchAll(/<title>([^<]*)<\/title>/g)].map((match) => match[1]);
  assertEqual(titles.length, 4, "every plotted point must be hoverable");
  assertEqual(titles[0], "Triton 400.0 ppm 2026-01-01", "a tooltip names the lab, the value with its unit, and the sample date");
  assertEqual(titles[1], "ATI 410.0 ppm 2026-01-06", "and follows the point it belongs to");
});

test("test_one_unreadable_value_does_not_take_the_whole_chart_with_it", async () => {
  // icp.py should never put a non-number in points[], so this is the belt to the
  // backend's braces: if one ever slips through, the samples either side of it
  // must still land in the right place instead of the series scale going NaN and
  // silently erasing every dot.
  const panel = await makePanel({});
  const rec = series({ points: [point(0, 400, "Triton"), point(5, "n.n.", "ATI"), point(10, 460, "Triton")] });
  const svg = panel._icpDashboardChart(rec, "all");
  const plotted = chartCircles(svg).filter((dot) => Number.isFinite(dot.y));
  assertEqual(plotted.length, 2, "the readable points must still be plotted");
  assert(plotted[0].y > plotted[1].y, "and still ranked by value — a bad row must not flatten the scale");
  assert(plotted[0].y - plotted[1].y > 150, "the scale must come from the readable values, not collapse to nothing");
  assert(svg.includes("<strong>460.00 ppm</strong>"), "the headline peak must ignore the unreadable value rather than become '--'");
});

test("test_the_chart_headline_quotes_the_series_peak_with_its_unit", async () => {
  // The one number printed above the chart. Quoting the minimum (or the last
  // point) there would understate exactly the elements people watch for spikes.
  const panel = await makePanel({});
  const labels = (rec) => (panel._icpDashboardChart(rec, "all").match(/<div class="chart-labels">([\s\S]*?)<\/div>/) || [])[1];
  const major = labels(series({ points: [point(0, 400, "Triton"), point(10, 460, "ATI"), point(20, 430, "Triton")] }));
  assert(major.includes("<strong>460.00 ppm</strong>"), `the headline must be the series peak with its unit: ${major}`);
  const trace = labels(series({ symbol: "Cu", name: "Copper", unit: "µg/l", points: [point(0, 0.42, "ATI"), point(9, 0.11, "Triton")] }));
  assert(trace.includes("<strong>0.4200 µg/l</strong>"), `a sub-1 peak keeps four decimals: ${trace}`);
  // Both ends of the time axis are labelled. The wording is locale/timezone
  // formatted, so this pins that they exist and are not placeholders.
  const ends = [...major.matchAll(/<span>([^<]*)<\/span>/g)].map((match) => match[1].trim());
  assertEqual(ends.length, 2, "the time axis is labelled at both ends");
  assert(ends.every((end) => end.length > 0), `an unlabelled time axis: ${JSON.stringify(ends)}`);
  noPlaceholders(major, "the chart labels");
});

test("test_a_series_with_only_below_detection_points_says_where_they_went", async () => {
  // Nothing plottable, but the user did import results. The empty chart has to
  // say so, or a tank full of "<0.5" trace metals looks like a broken import.
  const panel = await makePanel({});
  const rec = series({ symbol: "Cu", name: "Copper", unit: "µg/l", points: [], bdlPoints: [point(0, null, "ATI", { bdl: true, threshold: 0.5 })] });
  const svg = panel._icpDashboardChart(rec, "all");
  assert(svg.includes("empty-chart"), "no plottable points means the empty-chart note, not a broken axis");
  assert(/below-detection/i.test(svg), `the note must point at the table: "${svg}"`);
  assert(!svg.includes("<circle"), "a below-detection point must not be plotted as a value");
});

test("test_lab_colours_are_stable_case_insensitive_and_distinct", async () => {
  // The point colour IS the lab attribution — legend, swatch, table dot and
  // chart dot all call this. If it drifted between calls, two dots from the same
  // lab would look like two labs.
  const panel = await makePanel({});
  const other = await makePanel({ icpReports: SOME_REPORTS });
  const named = ["Triton", "ATI", "Fauna Marin", "Oceamo", "Aquaforest", "ReefZlements", "Unknown"];
  const colours = named.map((lab) => panel._icpLabColor(lab));
  assertEqual(new Set(colours).size, named.length, "every lab OpenReef names must be distinguishable at a glance");
  for (const lab of [...named, "Some Small Lab", ""]) {
    const colour = panel._icpLabColor(lab);
    assert(typeof colour === "string" && /^(#[0-9a-f]{6}|hsl\(\d+, \d+%, \d+%\))$/.test(colour),
      `"${lab}" must resolve to a CSS colour, got ${JSON.stringify(colour)}`);
    assertEqual(panel._icpLabColor(lab), colour, `"${lab}" changed colour between calls`);
    assertEqual(other._icpLabColor(lab), colour, `"${lab}" changed colour between panels`);
  }
  assertEqual(panel._icpLabColor("triton"), panel._icpLabColor("Triton"), "lab casing must not fork the colour");
  assertEqual(panel._icpLabColor(""), panel._icpLabColor("Unknown"), "an unnamed lab is the Unknown lab");
  // Labs OpenReef has no swatch for are still separate labs on the same chart,
  // so the generated colour has to be derived from the name, not a house colour.
  const unlisted = ["Some Small Lab", "Reef Chem Ltd", "Aquarium Analytics", "Blue Water Labs", "ICP Analysis UK"];
  assertEqual(new Set(unlisted.map((lab) => panel._icpLabColor(lab))).size, unlisted.length,
    "labs without a fixed swatch must still be told apart from each other");
  assert(!unlisted.some((lab) => colours.includes(panel._icpLabColor(lab))),
    "a generated colour must not land on top of a named lab's colour");
});

test("test_no_reports_offers_an_import_instead_of_an_empty_chart", async () => {
  // First-run state. A dashboard of zeroed axes would look like a tank with
  // nothing in it rather than an account with nothing imported.
  const html = await renderDashboard({ reports: [], payload: payloadFor(series({ points: [point(0, 420, "Triton")] })) });
  assert(/import your first/i.test(html), "the empty state must ask for the first report");
  assert(html.includes('data-action="icp-subview"') && html.includes('data-id="import"'), "and hand the user a way to get there");
  assert(!html.includes("<svg") && !html.includes("icp-dashboard-table"),
    "a stale payload must not paint a chart for a user with no reports");
  noPlaceholders(html, "the empty state");
});

test("test_reports_without_tank_water_series_never_fake_a_chart", async () => {
  // RO/DI reports are deliberately excluded from trends by icp.py, so a user who
  // has only imported source-water tests has reports but no series. Say that,
  // rather than drawing an axis with nothing on it.
  const html = await renderDashboard({ payload: payloadFor(undefined) });
  assert(html.includes("No element selected."), "with no series there is nothing to trend");
  assert(/no tank-water values in this filter/i.test(html), "and the element row must explain why it is empty");
  assert(!html.includes("<svg"), "no series means no chart");
  assert(!html.includes("icp-dashboard-table"), "no series means no point table either");
  noPlaceholders(html, "the no-series dashboard");
});

test("test_the_lab_filter_never_leaves_the_dashboard_with_nothing_selected", async () => {
  // "Included labs" is stored as an exclusion-free list where empty means ALL.
  // The trap is the round trip: unticking your last lab, or ticking every lab,
  // both have to land back on "all" rather than on a dashboard showing nothing.
  const labs = ["ATI", "Fauna Marin", "Triton"];
  const toggle = async (includedLabs, clicked) => {
    const panel = await makePanel({ icpDashboard: { includedLabs, range: "all", group: "core", symbol: "Ca" } });
    panel._icpDashboard = { payload: { labs: labs.map((lab) => ({ lab })) }, loading: false, error: "", requestId: 0 };
    // Side effects of a filter change: a refetch, a config save and a re-render.
    // All three need hass/DOM; the selection maths does not.
    panel._loadIcpDashboard = () => {};
    panel._icpDashboardPersist = () => {};
    panel._render = () => {};
    panel._icpDashboardToggleLab(clicked);
    return panel._config.icpDashboard.includedLabs;
  };
  assertEqual(await toggle([], "Triton"), ["Triton"], "the first click narrows from all labs to that one lab");
  assertEqual(await toggle(["Triton"], "ATI"), ["Triton", "ATI"], "a second click adds a lab rather than replacing it");
  assertEqual(await toggle(["Triton"], "Triton"), [], "unticking your only lab returns to all labs, never to none");
  assertEqual(await toggle(["ATI", "Fauna Marin"], "Triton"), [], "ticking every lab is stored as 'all', so the All button lights up");
  assertEqual(await toggle(["Triton"], "__all"), [], "the All labs button clears the filter");
  assertEqual(await toggle(["Ghost Lab", "Triton"], "ATI"), ["Triton", "ATI"],
    "a lab whose reports were deleted is dropped from the filter instead of hiding everything");
});

test("test_corrupt_dashboard_filters_are_repaired_rather_than_crashing_the_tab", async () => {
  // These settings round-trip through stored config, so they can come back as
  // anything. The dashboard has to open regardless — this is the ICP tab's
  // default view.
  for (const stored of [undefined, {}, { includedLabs: "Triton" }, { includedLabs: [], range: "", group: null, symbol: "" }]) {
    const panel = await makePanel(stored === undefined ? {} : { icpDashboard: stored });
    const cfg = panel._icpDashboardConfig();
    assertEqual(cfg, { includedLabs: [], range: "all", group: "core", symbol: "Ca" },
      `stored filters ${JSON.stringify(stored)} were not repaired to the defaults`);
    assert(Array.isArray(panel._config.icpDashboard.includedLabs), "the repair must be written back to the config, not just returned");
  }
});

await runTests();
