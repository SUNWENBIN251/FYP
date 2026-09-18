# Progress Presentation — Speaker Script

**A Low-Cost IoT Environmental Monitoring System for Server Rooms**
Sun WenBin · P2321251 · COMP4299/CSAI4299 Final Year Project

> 用法：每页先念「English script」，中文是给你理解的要点提示（不用念）。
> 总时长约 8–10 分钟。⏱ 标注建议用时。

---

## Slide 1 — Title

**English script**

> Good morning. My name is Sun WenBin, and my Final Year Project is a low-cost IoT environmental monitoring system for server rooms, using a Raspberry Pi and DHT22 sensors. This presentation reports on the progress of the project.

**中文提示**：开场，报名字 + 项目名 + 这是进度汇报。
⏱ 约 15 秒

---

## Slide 2 — Presentation Outline

**English script**

> I will cover six areas: first the problem and motivation, then the aim and SMART objectives, the system architecture, the work completed so far, the big-data layer built with Spark and Hive, and finally the project schedule and risk management.

**中文提示**：报目录，让听众知道结构。可以快速带过。
⏱ 约 20 秒

---

## Slide 3 — Problem & Motivation

**English script**

> Server rooms concentrate heat-generating equipment in a confined space, so temperature and humidity must be controlled. Excursions silently accelerate hardware ageing and are a common cause of failure in small facilities. Commercial monitoring platforms exist, but they are expensive and closed — out of reach for universities, clinics and small businesses. Most open hardware projects, on the other hand, stop at logging and plotting. So the goal is a low-cost, integrated system that small organisations can actually afford and operate.

**中文提示**：机房温湿度失控 → 硬件损坏；商业方案太贵、开源项目不完整 → 引出"低成本 + 集成"的目标。
⏱ 约 40 秒

---

## Slide 4 — SMART Objectives

**English script**

> The project is built against five SMART objectives. First, data collection: read temperature and humidity from DHT22 sensors every minute, with a capture rate of at least 99 percent. Second, a web dashboard with real-time gauges and 24-hour trends, refreshing within two seconds. Third, threshold alerting through Telegram within ten seconds. Fourth, data persistence in a SQLite database, where any 30-day query returns in under one second. And fifth, CSV export within five seconds, plus a Spark and Hive layer for longer-term analysis.

**中文提示**：5 个可量化目标，逐个点名（采集率 99% / 2 秒刷新 / 10 秒告警 / 1 秒查询 / 5 秒导出）。这些数字后面答辩要拿实测数据呼应。
⏱ 约 45 秒

---

## Slide 5 — System Architecture

**English script**

> Here is the overall architecture. Two DHT22 sensors are connected to a Raspberry Pi node, which reads them every minute and sends the readings over the local network to a central server. The server is a Flask application that stores data in SQLite and appends to a CSV file, checks thresholds, and drives a Chart.js dashboard and Telegram alerts. On top of this, a batch layer built with Spark and Hive analyses the accumulated history. The key point is the design decision: the Pi is a lightweight sensing node, and the server is the central hub.

**中文提示**：指图讲数据流——传感器 → 树莓派 → 服务器（Flask/SQLite）→ 仪表盘/告警 → Spark/Hive。强调"树莓派只采集，服务器做中心"这个分工。
⏱ 约 45 秒

---

## Slide 6 — Completed Work: From Sensor to Dashboard

**English script**

> This slide summarises the four components that are working. First, sensing: the collector script reads both sensors every 60 seconds, retries invalid reads, and buffers locally if the network fails, so the 99 percent capture target is protected. Second, ingestion: a Flask API endpoint validates each reading, writes it to SQLite in WAL mode, appends to CSV, and evaluates thresholds inline. Third, the dashboard: Chart.js gauges and a 24-hour trend with threshold bands, polling every two seconds, with per-range CSV export. And fourth, alerting: Telegram messages sent in a background thread, with a ten-minute suppression window and an automatic recovery notice.

**中文提示**：四个模块——采集（含离线缓冲）、入库（WAL）、仪表盘、告警（抑制+恢复）。都是**已实现、在真机上跑通**的。
⏱ 约 60 秒

---

## Slide 7 — Live Dashboard (running system)

**English script**

> This is a screenshot of the dashboard taken from the running system. On the left you can see the live view for each sensor, with a status strip, the current temperature and humidity, and health indicators showing the connection state and sensor count. The 24-hour trend overlays both sensors against the threshold bands. And on the same page, the operator can adjust the thresholds live — no restart needed.

**中文提示**：这是**真机截图**（重点强调"真实运行"）。讲：实时视图、24h 趋势、健康指示、阈值可在线改。
⏱ 约 35 秒

---

## Slide 8 — Threshold Alerting via Telegram

**English script**

> Alerting works in four steps: the value arrives, it is evaluated against the thresholds, a Telegram message is sent within ten seconds, and a separate recovery message is sent when conditions return to normal. We verified this on the real hardware: a manual excursion produced a Telegram message on the phone, and the recovery notice arrived automatically. Per-condition suppression prevents the operator from being flooded with repeated messages.

**中文提示**：告警流程 + **真机验证结果**（手机收到告警和恢复通知）。这是关键成果之一。
⏱ 约 35 秒

---

## Slide 9 — Spark + Hive Batch Analysis

**English script**

> Beyond real-time monitoring, I built a batch-analysis layer. It runs a single-node Hadoop, Hive and Spark cluster inside WSL. The pipeline reads the accumulated CSV, uses PySpark to compute hourly aggregates — average, maximum and minimum temperature and humidity per sensor — and writes the result to HDFS, where Hive exposes it as an external table. This lets us answer questions the real-time system cannot: how many hours exceeded the safe range, how the environment trends day by day, and whether the capture rate target was met.

**中文提示**：这是**超出基本要求的亮点**。讲：WSL 单机集群、PySpark 小时聚合、Hive 外部表、能回答"历史规律"类问题。
⏱ 约 45 秒

---

## Slide 10 — Precedence Network (PDM)

**English script**

> For project time management, this is the precedence network. The project totals 28 weeks, and the critical path — shown in red — runs from literature review through hardware, backend and dashboard development, integration and testing, to the final submission. Each node shows the four dates — early start, early finish, late start and late finish — as well as the total float, so non-critical activities can be identified.

**中文提示**：PDM 图。讲：总工期 28 周、红色关键路径、每个节点的 ES/EF/LS/LF 和浮动。
⏱ 约 30 秒

---

## Slide 11 — Gantt Chart

**English script**

> The schedule is shown here as a Gantt chart. Semester 1 covers the literature review, hardware setup, backend and dashboard development, and the progress report itself. Semester 2 covers integration, the seven-day continuous test, and final delivery. The critical activities are highlighted in red.

**中文提示**：甘特图。讲两学期分工 + 红色是关键活动。与 PDM 一致。
⏱ 约 25 秒

---

## Slide 12 — Top Risks & Mitigations

**English script**

> I identified five main risks. The unstable network link is handled by local buffering and retransmission. Server downtime or database corruption is handled by WAL mode and backups. Sensor accuracy is handled by validating and retrying reads. Alert delays are handled by evaluating at ingestion with retries. And query or export performance is handled by indexing the timestamp column. Each risk has a concrete response.

**中文提示**：5 个风险 + 应对措施。可以点出"网络风险（高影响）用离线缓冲化解"最能对应 99% 采集率目标。
⏱ 约 35 秒

---

## Slide 13 — Current Status & Next Steps

**English script**

> To summarise the status: the core system is complete and running on real hardware — sensing, ingestion, the dashboard, CSV export, Telegram alerts, and the Spark and Hive layer. What is in progress is the seven-day continuous validation of the capture-rate and latency targets, and calibration against a reference sensor. My next steps are to complete the formal SMART verification, write the final report, and prepare the demo video and poster. Thank you for listening — I am happy to take questions.

**中文提示**：收尾。讲：核心已完成并真机运行 / 进行中：7 天连续验证 + 校准 / 下一步：SMART 验证、最终报告、演示视频、海报。然后致谢、请提问。
⏱ 约 40 秒

---

## 可能被问到的问题（准备一下）

| 问题 | 回答要点 |
|---|---|
| 为什么用 DHT22 而不是更贵的传感器？ | 成本与精度平衡：±0.5°C / ±2%RH 足够机房监控，且便宜、易获取 |
| 两个传感器有什么用？ | 交叉校验数据可信度（见 Hive 对比查询），也可覆盖不同测点 |
| 99% 采集率怎么保证？ | 本地离线缓冲 + 断网补发；Hive 查询可按小时核查缺口 |
| 为什么还要 Spark/Hive？ | 实时层答"现在几度"，批处理层答"过去整段时间的规律"，做历史分析 |
| 树莓派和后端怎么通信？ | 局域网 HTTP POST，树莓派每分钟上报一次 |
| 告警会不会刷屏？ | 有 10 分钟抑制窗口 + 恢复通知，不重复轰炸 |
