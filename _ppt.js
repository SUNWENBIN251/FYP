// FYP Progress Report Presentation (English)
const pptxgen = require("pptxgenjs");
const path = require("path");

const IMG = (f) => path.resolve(__dirname, "iot_monitor", f);

const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE";            // 13.33 x 7.5 in
pptx.author = "Sun WenBin";
pptx.title = "FYP Progress Report - IoT Environmental Monitoring System";

// ---------------- palette (dark control-room theme) ----------------
const BG      = "0B1220";   // near-black navy
const PANEL   = "131C2E";   // card
const PANEL2  = "1A2540";
const NAVY    = "7FA8D9";
const TEAL    = "35E0A1";   // accent green (monitor "OK")
const AMBER   = "FFC857";
const RED     = "FF6B6B";
const WHITE   = "F5F8FD";
const MUTED   = "9FB0CC";
const GRID    = "2A3A5C";
const CRIT    = "FF8A8A";

const L = 0.55, R = 13.33 - 0.55, CW = 13.33 - 1.1;   // content box
const TITLE_Y = 0.4, TITLE_H = 0.75;

function base(slide) {
  slide.background = { color: BG };
}

function titleBar(slide, kicker, title) {
  slide.addText(kicker, { x: L, y: TITLE_Y, w: CW, h: 0.3, fontFace: "Arial",
    fontSize: 12, color: TEAL, bold: true, charSpacing: 2, align: "left" });
  slide.addText(title, { x: L, y: TITLE_Y + 0.28, w: CW, h: 0.62, fontFace: "Arial",
    fontSize: 26, color: WHITE, bold: true, align: "left" });
}

function footer(slide, n) {
  slide.addText("COMP4299/CSAI4299 Final Year Project  ·  Sun WenBin P2321251  ·  " + n,
    { x: L, y: 7.12, w: CW, h: 0.25, fontFace: "Arial", fontSize: 8.5,
      color: MUTED, align: "left" });
}

function card(slide, x, y, w, h, fill) {
  slide.addShape(pptx.ShapeType.roundRect, { x, y, w, h, fill: { color: fill || PANEL },
    rectRadius: 0.06, line: { color: GRID, width: 0.75 } });
}

// ============================================================ 1 TITLE
let s = pptx.addSlide();
base(s);
s.addShape(pptx.ShapeType.roundRect, { x: 0, y: 0, w: 13.33, h: 0.12, fill: { color: TEAL }, rectRadius: 0 });
s.addText("SERVER ROOM / DATA CENTER ENVIRONMENT", { x: L, y: 1.0, w: CW, h: 0.35,
  fontFace: "Arial", fontSize: 14, color: TEAL, bold: true, charSpacing: 3, align: "center" });
s.addText("A Low-Cost IoT Environmental Monitoring System\nfor Server Rooms Using Raspberry Pi and DHT22 Sensors",
  { x: 0.9, y: 1.5, w: 11.5, h: 2.0, fontFace: "Arial", fontSize: 36, color: WHITE,
    bold: true, align: "center", lineSpacing: 44 });
s.addText("PROGRESS REPORT  ·  ACADEMIC YEAR 2026/27", { x: 1.5, y: 3.9, w: 10.3, h: 0.4,
  fontFace: "Arial", fontSize: 16, color: AMBER, bold: true, charSpacing: 2, align: "center" });
s.addShape(pptx.ShapeType.line, { x: 3.0, y: 4.5, w: 7.3, h: 0, line: { color: GRID, width: 1 } });
s.addText("Sun WenBin   (P2321251)\nBSc in Computing / Artificial Intelligence",
  { x: 2.0, y: 4.7, w: 9.3, h: 1.0, fontFace: "Arial", fontSize: 15, color: MUTED,
    align: "center", lineSpacing: 22 });
s.addText("Supervisor:  TBD", { x: 2.0, y: 5.7, w: 9.3, h: 0.35, fontFace: "Arial",
  fontSize: 12, color: MUTED, align: "center" });

// ============================================================ 2 AGENDA
s = pptx.addSlide(); base(s);
titleBar(s, "OVERVIEW", "Presentation Outline");
const agenda = [
  ["01", "Problem & Motivation", "Why small server rooms need affordable environmental monitoring"],
  ["02", "Aim & SMART Objectives", "Measurable targets the project is built against"],
  ["03", "System Architecture", "Raspberry Pi + DHT22 → Flask/SQLite → dashboard & alerts"],
  ["04", "Completed Work", "Sensing, ingestion, dashboard, Telegram alerts"],
  ["05", "Big-Data Layer", "Spark + Hive batch aggregation"],
  ["06", "Project Progress & Risk", "Schedule status, risks and mitigations"],
];
agenda.forEach((a, i) => {
  const y = 1.35 + i * 0.88;
  card(s, L, y, CW, 0.72, PANEL);
  s.addText(a[0], { x: L + 0.2, y: y + 0.10, w: 0.9, h: 0.5, fontFace: "Arial",
    fontSize: 22, color: TEAL, bold: true, align: "center" });
  s.addText(a[1], { x: L + 1.35, y: y + 0.08, w: 4.2, h: 0.32, fontFace: "Arial",
    fontSize: 16, color: WHITE, bold: true, align: "left" });
  s.addText(a[2], { x: L + 1.35, y: y + 0.40, w: 10.6, h: 0.28, fontFace: "Arial",
    fontSize: 11, color: MUTED, align: "left" });
});
footer(s, "2");

// ============================================================ 3 PROBLEM
s = pptx.addSlide(); base(s);
titleBar(s, "CONTEXT", "Problem & Motivation");
card(s, L, 1.35, CW, 2.35, PANEL);
s.addText("Server rooms concentrate heat-generating IT equipment in a confined space. "
  + "Temperature or humidity excursions silently accelerate hardware ageing and are among the "
  + "most common causes of failure in small facilities.", { x: L + 0.35, y: 1.6, w: CW - 0.7,
    h: 1.0, fontFace: "Arial", fontSize: 15, color: WHITE, align: "left", lineSpacing: 22 });
s.addText("Commercial BMS / DCIM platforms are accurate but expensive and closed — "
  + "out of reach of universities, clinics and small businesses. Most open hardware projects stop "
  + "at logging and plotting; few add alerting, an operator dashboard or durable, exportable history.",
  { x: L + 0.35, y: 2.5, w: CW - 0.7, h: 1.0, fontFace: "Arial", fontSize: 13.5,
    color: MUTED, align: "left", lineSpacing: 20 });

const stats = [
  ["~70%", "of IT failures in small rooms traced to heat / humidity conditions"],
  ["<1s", "target response for any 30-day query window"],
  ["100%", "no commercial platform targeted at the small-room budget"],
];
stats.forEach((st, i) => {
  const x = L + i * ((CW - 0.6) / 3 + 0.3);
  card(s, x, 3.95, (CW - 0.6) / 3, 1.5, PANEL2);
  s.addText(st[0], { x: x, y: 4.15, w: (CW - 0.6) / 3, h: 0.7, fontFace: "Arial",
    fontSize: 30, color: TEAL, bold: true, align: "center" });
  s.addText(st[1], { x: x + 0.2, y: 4.95, w: (CW - 0.6) / 3 - 0.4, h: 0.55,
    fontFace: "Arial", fontSize: 10.5, color: MUTED, align: "center", lineSpacing: 14 });
});
s.addText("Proposed response: an affordable, integrated system combining proven low-cost building blocks.",
  { x: L, y: 5.7, w: CW, h: 0.4, fontFace: "Arial", fontSize: 13.5, color: AMBER,
    bold: true, align: "left" });
footer(s, "3");

// ============================================================ 4 OBJECTIVES
s = pptx.addSlide(); base(s);
titleBar(s, "AIM & TARGETS", "SMART Objectives");
const objs = [
  ["Data collection", "Read temp (±0.5 °C) & humidity (±2 %RH) from DHT22 sensors at 1-min intervals, capture rate ≥ 99 %."],
  ["Web dashboard", "Real-time gauges + 24 h trends with Chart.js; page refresh under 2 seconds."],
  ["Alerting", "Configurable thresholds → Telegram within 10 s of a crossing, with recovery notices."],
  ["Persistence", "SQLite time-series store; any 30-day window queried in under 1 second."],
  ["Export & analytics", "CSV export of any range in <5 s; Spark/Hive batch layer for history aggregation."],
];
objs.forEach((o, i) => {
  const x = L + (i % 2) * (CW / 2 + 0.25);
  const y = 1.4 + Math.floor(i / 2) * 1.85;
  card(s, x, y, CW / 2, 1.65, PANEL);
  s.addText("0" + (i + 1), { x: x + 0.22, y: y + 0.18, w: 0.9, h: 0.6, fontFace: "Arial",
    fontSize: 30, color: TEAL, bold: true, align: "left" });
  s.addText(o[0], { x: x + 1.15, y: y + 0.22, w: (CW / 2) - 1.4, h: 0.4, fontFace: "Arial",
    fontSize: 17, color: WHITE, bold: true, align: "left" });
  s.addText(o[1], { x: x + 0.25, y: y + 0.78, w: (CW / 2) - 0.5, h: 0.8, fontFace: "Arial",
    fontSize: 12, color: MUTED, align: "left", lineSpacing: 16 });
});
footer(s, "4");

// ============================================================ 5 ARCHITECTURE
s = pptx.addSlide(); base(s);
titleBar(s, "DESIGN", "System Architecture");
card(s, L, 1.3, CW, 4.35, "FFFFFF");
s.addImage({ path: IMG("logic_design.png"), x: L + 0.35, y: 1.55, w: CW - 0.7,
  h: 3.9, sizing: { type: "contain", w: CW - 0.7, h: 3.9 } });
s.addText("Raspberry Pi + DHT22 sensing nodes → Flask REST API → SQLite (WAL) + CSV → Chart.js dashboard, "
  + "Telegram alerts, CSV export, and a Spark/Hive batch-analysis path.", { x: L, y: 5.75, w: CW,
    h: 0.7, fontFace: "Arial", fontSize: 12.5, color: MUTED, align: "left", lineSpacing: 17 });
footer(s, "5");

// ============================================================ 6 COMPLETED - pipeline
s = pptx.addSlide(); base(s);
titleBar(s, "COMPLETED WORK", "From Sensor to Dashboard");
const steps = [
  ["1  Sensing", "collector.py reads DHT22 every 60 s; invalid reads retried; offline buffer + CSV re-send guards the ≥99 % capture target."],
  ["2  Ingestion", "Flask POST /api/reading validates, writes SQLite (WAL, indexed), appends CSV, evaluates thresholds inline."],
  ["3  Dashboard", "Chart.js gauges + 24 h trend with ASHRAE-informed threshold bands; 2 s polling; CSV export per range & sensor."],
  ["4  Alerting", "Telegram via background thread; per-condition suppression (10 min) + recovery notification when back to normal."],
];
steps.forEach((st, i) => {
  const x = L + (i % 2) * (CW / 2 + 0.25);
  const y = 1.45 + Math.floor(i / 2) * 2.1;
  card(s, x, y, CW / 2, 1.9, PANEL);
  s.addText(st[0], { x: x + 0.3, y: y + 0.25, w: (CW / 2) - 0.6, h: 0.45, fontFace: "Arial",
    fontSize: 17, color: TEAL, bold: true, align: "left" });
  s.addText(st[1], { x: x + 0.3, y: y + 0.8, w: (CW / 2) - 0.6, h: 1.0, fontFace: "Arial",
    fontSize: 12.5, color: WHITE, align: "left", lineSpacing: 17 });
});
footer(s, "6");

// ============================================================ 7 LIVE DASHBOARD (screenshot)
s = pptx.addSlide(); base(s);
titleBar(s, "COMPLETED WORK", "Live Dashboard (running system)");
card(s, L, 1.35, 6.6, 5.5, "FFFFFF");
s.addImage({ path: IMG("pptcontent.png"), x: L + 0.25, y: 1.6, w: 6.1, h: 5.0,
  sizing: { type: "contain", w: 6.1, h: 5.0 } });
const feats = [
  ["Real-time view", "Current temp & humidity per sensor with status strip."],
  ["24-hour trends", "Overlay of both sensors vs. threshold bands."],
  ["Health indicators", "Connection, sensor count, nominal / alarm state."],
  ["Threshold control", "Live-editable min/max values on the same page."],
];
feats.forEach((f, i) => {
  const y = 1.4 + i * 1.15;
  card(s, 7.4, y, 5.35, 1.0, PANEL);
  s.addShape(pptx.ShapeType.ellipse, { x: 7.62, y: y + 0.28, w: 0.42, h: 0.42,
    fill: { color: i === 0 || i === 2 ? TEAL : NAVY } });
  s.addText(f[0], { x: 8.25, y: y + 0.1, w: 4.3, h: 0.34, fontFace: "Arial",
    fontSize: 14.5, color: WHITE, bold: true, align: "left" });
  s.addText(f[1], { x: 8.25, y: y + 0.48, w: 4.35, h: 0.5, fontFace: "Arial",
    fontSize: 10.5, color: MUTED, align: "left", lineSpacing: 13.5 });
});
footer(s, "7");

// ============================================================ 8 ALERTING
s = pptx.addSlide(); base(s);
titleBar(s, "COMPLETED WORK", "Threshold Alerting via Telegram");
const alertSteps = [
  ["Read", "Sensor value arrives at ingestion"],
  ["Evaluate", "Compare temp/humidity against thresholds"],
  ["Notify", "Telegram within 10 s (background send, retries)"],
  ["Recover", "Separate message when back inside limits"],
];
alertSteps.forEach((st, i) => {
  const x = L + i * (CW / 4 + 0.28);
  card(s, x, 1.5, CW / 4, 2.1, PANEL);
  s.addShape(pptx.ShapeType.ellipse, { x: x + 0.55, y: 1.78, w: 0.75, h: 0.75,
    fill: { color: i === 2 ? RED : i === 3 ? TEAL : NAVY } });
  s.addText("0" + (i + 1), { x: x + 0.55, y: 1.86, w: 0.75, h: 0.6, fontFace: "Arial",
    fontSize: 20, color: "FFFFFF", bold: true, align: "center" });
  s.addText(st[0], { x: x + 0.2, y: 2.75, w: CW / 4 - 0.4, h: 0.4, fontFace: "Arial",
    fontSize: 15, color: WHITE, bold: true, align: "center" });
  s.addText(st[1], { x: x + 0.25, y: 3.15, w: CW / 4 - 0.5, h: 0.6, fontFace: "Arial",
    fontSize: 10.5, color: MUTED, align: "center", lineSpacing: 14 });
});
card(s, L, 4.0, CW, 1.35, PANEL2);
s.addText("Verified behaviour", { x: L + 0.35, y: 4.15, w: 3.0, h: 0.35, fontFace: "Arial",
  fontSize: 13, color: AMBER, bold: true, align: "left" });
s.addText("Manual threshold excursion fired a Telegram message on a phone inside the target latency, "
  + "and a second message arrived automatically when conditions returned to normal — no message flooding "
  + "thanks to per-condition suppression.", { x: L + 0.35, y: 4.55, w: CW - 0.7, h: 0.7,
    fontFace: "Arial", fontSize: 12.5, color: WHITE, align: "left", lineSpacing: 16 });
footer(s, "8");

// ============================================================ 9 SPARK/HIVE
s = pptx.addSlide(); base(s);
titleBar(s, "BIG-DATA LAYER", "Spark + Hive Batch Analysis (WSL2, single-node cluster)");
const stacks = [
  ["Environment", "Hadoop 3.4.1 (HDFS) + Hive 4.2.1 metastore + Spark 4.0.4 (YARN), Java 21, on Ubuntu in WSL2."],
  ["Pipeline", "readings.csv → hourly aggregates (avg/max/min temp & humidity per sensor) via PySpark → HDFS."],
  ["Query", "Hive external table over the aggregated output — SQL access to long-run history."],
  ["Role", "Complements the real-time Flask/SQLite path for semester-length analytics & reporting."],
];
stacks.forEach((st, i) => {
  const x = L + (i % 2) * (CW / 2 + 0.25);
  const y = 1.45 + Math.floor(i / 2) * 1.7;
  card(s, x, y, CW / 2, 1.5, PANEL);
  s.addText(st[0], { x: x + 0.3, y: y + 0.2, w: 2.2, h: 0.4, fontFace: "Arial",
    fontSize: 15, color: TEAL, bold: true, align: "left" });
  s.addText(st[1], { x: x + 0.3, y: y + 0.62, w: (CW / 2) - 0.6, h: 0.8, fontFace: "Arial",
    fontSize: 12, color: WHITE, align: "left", lineSpacing: 16 });
});
footer(s, "9");

// ============================================================ 10 PDM
s = pptx.addSlide(); base(s);
titleBar(s, "PROJECT TIME MANAGEMENT", "Precedence Network (PDM) — 28 weeks, critical path in red");
card(s, L, 1.35, CW, 3.9, "FFFFFF");
s.addImage({ path: IMG("pdm_diagram.png"), x: L + 0.3, y: 1.5, w: CW - 0.6, h: 3.6,
  sizing: { type: "contain", w: CW - 0.6, h: 3.6 } });
s.addText("A1 → A3 → A4 → A5 → A7 → A9 → A11 → A12 → A13 → A14 is the critical path (28 weeks); "
  + "each node shows ES / EF / LS / LF and total float.", { x: L, y: 5.35, w: CW, h: 0.4,
    fontFace: "Arial", fontSize: 12, color: MUTED, align: "left" });
footer(s, "10");

// ============================================================ 11 GANTT
s = pptx.addSlide(); base(s);
titleBar(s, "PROJECT TIME MANAGEMENT", "Schedule — Gantt across two semesters");
card(s, L, 1.4, CW, 4.2, "FFFFFF");
s.addImage({ path: IMG("gantt.png"), x: L + 0.3, y: 1.55, w: CW - 0.6, h: 3.9,
  sizing: { type: "contain", w: CW - 0.6, h: 3.9 } });
s.addText("Semester 1 (W1-15) covers sensing, backend, dashboard and the progress report; Semester 2 "
  + "(S2 W1-13) covers integration, validation and final delivery.", { x: L, y: 5.7, w: CW,
    h: 0.4, fontFace: "Arial", fontSize: 12, color: MUTED, align: "left" });
footer(s, "11");

// ============================================================ 12 RISKS
s = pptx.addSlide(); base(s);
titleBar(s, "RISK MANAGEMENT", "Top Risks & Mitigations");
const risks = [
  ["Network link (Med/High)", "Buffer on the Pi + retransmit; local CSV fallback."],
  ["Server downtime / SQLite (Low/High)", "WAL mode, scheduled backups, CSV as secondary record."],
  ["Sensor accuracy (Med/Med)", "Validate & retry reads, reject out-of-range, calibrate."],
  ["Alert delay (Low/Med)", "Evaluate at ingestion; retry with backoff; SMTP backup."],
  ["Query / export targets (Low/Med)", "Index ts, pre-aggregate, paginate large exports."],
];
risks.forEach((r, i) => {
  const x = L + (i % 2) * (CW / 2 + 0.25);
  const y = 1.45 + Math.floor(i / 2) * 1.5;
  card(s, x, y, CW / 2, 1.3, PANEL);
  s.addText(r[0], { x: x + 0.3, y: y + 0.18, w: (CW / 2) - 0.6, h: 0.4, fontFace: "Arial",
    fontSize: 14, color: AMBER, bold: true, align: "left" });
  s.addText(r[1], { x: x + 0.3, y: y + 0.62, w: (CW / 2) - 0.6, h: 0.6, fontFace: "Arial",
    fontSize: 11.5, color: WHITE, align: "left", lineSpacing: 15 });
});
footer(s, "12");

// ============================================================ 13 NEXT / SUMMARY
s = pptx.addSlide(); base(s);
s.background = { color: "0A2E2A" };
s.addText("Current Status & Next Steps", { x: L, y: 0.9, w: CW, h: 0.7, fontFace: "Arial",
  fontSize: 30, color: "FFFFFF", bold: true, align: "center" });
const statusRows = [
  ["Complete", "Sensing, Flask ingestion, SQLite persistence, dashboard, CSV export, Telegram alerts, Spark/Hive layer."],
  ["In progress", "7-day continuous validation of capture-rate and latency targets; calibration against a reference sensor."],
  ["Next", "Formal SMART verification, final-report writing, demo video and poster for the final presentation."],
];
statusRows.forEach((st, i) => {
  const y = 2.0 + i * 1.35;
  card(s, 1.9, y, 9.5, 1.15, "123F37");
  const col = i === 0 ? TEAL : i === 1 ? AMBER : NAVY;
  s.addText(st[0].toUpperCase(), { x: 2.25, y: y + 0.35, w: 2.4, h: 0.45, fontFace: "Arial",
    fontSize: 14, color: col, bold: true, align: "left" });
  s.addText(st[1], { x: 4.85, y: y + 0.12, w: 6.3, h: 0.95, fontFace: "Arial", fontSize: 13,
    color: "E7F6F0", align: "left", lineSpacing: 18 });
});
s.addText("Thank you — Questions welcome.", { x: 1.5, y: 6.4, w: 10.3, h: 0.5, fontFace: "Arial",
  fontSize: 20, color: "FFFFFF", bold: true, align: "center" });

const out = "FYP_Progress_Presentation_SunWenBin.pptx";
pptx.writeFile({ fileName: out }).then(() => console.log("wrote", out));
