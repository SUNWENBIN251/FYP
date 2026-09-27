# IoT 机房环境监控系统（Server Room Environmental Monitoring）

基于 Raspberry Pi + DHT22 的低成本机房温湿度监控系统：实时采集 → 网页仪表盘 → 阈值告警（Telegram）→ 历史存储与导出，另含 Spark + Hive 批处理分析层。

COMP4299/CSAI4299 Final Year Project — Sun WenBin (P2321251)

---

## 1. 系统架构

```
2× DHT22 传感器 (GPIO4 / GPIO17)
        │
        ▼
树莓派 collector.py  ──每 60 秒 POST──▶  Flask 后端 (app.py)
   (systemd 服务)                              │
                                               ├─▶ SQLite (monitor.db, WAL)
                                               ├─▶ CSV (readings.csv)
                                               ├─▶ 阈值判断 → Telegram 告警 + 告警历史入库
                                               │
                                               ▼
                                       网页仪表盘 (Chart.js)
                         实时读数+趋势徽章 / 趋势文字摘要 / 24h 趋势图
                         批处理（按时间段的批次卡片：统计 / 异常 / 读数 / 告警）/ 报表（热力图 / 趋势 / 完整性 / 偏差）/ 阈值设置 / CSV 导出

[离线缓冲] 网络不通时 collector 先写 offline_buffer.csv，恢复后自动补发 → 保障 ≥99% 采集率
[告警历史] 每次越限与恢复记入 alerts 表 + alerts.csv，可在仪表盘查看、可交 Hive 分析
[批处理层] 数据 → PySpark 按小时聚合 → HDFS 按天分区 → Hive 外部表查询（WSL2 单机伪分布式）
           两条入口：演示脚本读 readings.csv / alerts.csv（见第 9 节）
                     批处理面板读 SQLite，按时间窗增量处理（见第 12 节）
[批处理调度] 水位线增量 + 任意时间窗重跑 + 按天分区动态覆写（幂等，见第 12 节）
```

**数据流方向**：树莓派（采集节点）→ 电脑（中心服务器）→ 浏览器 / 手机。

---

## 2. 目录结构

```
FYP/
├── README.md                   本文件
├── run_server.bat              后端后台启动脚本（Windows 自启靠它，勿删）
├── demo_backup.sh              备份功能一键演示（见第 10 节）
├── demo_calibration.sh         校准机制一键演示（见第 10 节）
├── seed_alerts.sh              生成演示用告警数据（见第 9 节）
├── start_wsl_keeper.bat        WSL 保活，让批处理跑得快（见第 12 节）
├── FYP Progress Report ...docx 进度报告文档
├── FYP Proposal ...docx/pdf    项目计划书
└── iot_monitor/
    ├── sensor/                 ── 部署到树莓派 ──
    │   ├── collector.py        采集 + 上报 + 离线缓冲
    │   ├── requirements.txt    adafruit-circuitpython-dht 等依赖
    │   └── offline_buffer.csv  离线缓存（运行生成）
    ├── server/                 ── 运行在 Windows 电脑 ──
    │   ├── app.py              Flask 主程序（API + 页面 + 备份/批处理调度线程）
    │   ├── config.py           配置：路径、默认阈值、告警参数、备份与批处理设置
    │   ├── database.py         SQLite 读写（readings / thresholds / alerts / calibration / batches / batch_windows）
    │   ├── alerts.py           阈值判断 + Telegram 发送 + 告警历史记录
    │   ├── calibrate.py        传感器校准工具（见第 10 节）
    │   ├── backup.py           备份脚本（见第 10 节）
    │   ├── batch.py            批处理编排（见第 12 节）
    │   ├── hive.py             Hive 报表查询 + 缓存（见第 13 节）
    │   ├── static/index.html   前端仪表盘
    │   ├── data/               数据库与 CSV（运行生成）
    │   │   ├── batch/          批次导出的 CSV 与结果 JSON（运行生成）
    │   │   └── backups/        自动备份（运行生成）
    │   └── spark/
    │       └── spark_etl.py    PySpark 按小时聚合（支持时间窗 + 按天分区）
    ├── spark/                  ── 在 WSL 里运行 ──
    │   ├── demo_spark_hive.sh      Spark + Hive 一键演示（见第 9 节）
    │   ├── batch_run.sh            单次增量批次，后端调它（见第 12 节）
    │   ├── hive_query.sh           跑一条 Hive 查询，结果以 TSV 打到 stdout（见第 13 节）
    │   ├── keep_wsl_alive.sh       保活：起服务并持有 WSL（见第 12 节）
    │   └── start_hive_services.sh  仅启动 Hive 服务，供手动查询
    ├── logic_design.png        逻辑架构图
    ├── pdm_diagram.png         PDM 网络图
    └── gantt.png               甘特图
```

---

## 3. 当前部署状态（已配置好）

| 端 | 位置 | 自启机制 | 状态 |
|---|---|---|---|
| **采集端** | 树莓派 (192.168.43.11) | systemd 服务 `collector.service` | 开机自启 ✓ |
| **后端** | Windows 电脑 (192.168.43.7) | 启动文件夹快捷方式 `FYP IoT Backend.lnk` | 登录自启 ✓ |

- 后端地址：`http://192.168.43.7:5000`
- 树莓派用户名：`swb`
- 传感器：dht22-01 → GPIO4，dht22-02 → GPIO17

---

## 4. 日常使用流程

1. **电脑开机 → 登录 Windows**（后端自动启动）
2. **树莓派上电**（collector 服务自动启动）
3. 两者接入**同一个手机热点**
4. 等约 1 分钟，数据自动上报

**验证：** 浏览器打开 `http://192.168.43.7:5000` 看到实时数据即正常。

### 关键前提（务必记住）

- ⚠️ 电脑必须**保持开机 + 登录**，后端才在跑
- ⚠️ 必须用**同一个热点**，`192.168.43.7` 才有效（换热点 IP 会变，见第 6 节）
- ⚠️ 树莓派断电重启后约 1 分钟恢复上报

---

## 5. 常用命令

### 树莓派侧（SSH：`ssh swb@192.168.43.11`）

| 操作 | 命令 |
|---|---|
| 看服务状态 | `systemctl status collector.service` |
| 看实时日志 | `tail -f ~/collector.log` |
| 重启服务 | `sudo systemctl restart collector.service` |
| 停止服务 | `sudo systemctl stop collector.service` |
| 开机启用/禁用 | `sudo systemctl enable/disable collector.service` |

### Windows 电脑侧

| 操作 | 命令 |
|---|---|
| 手动启动后端 | 双击 `run_server.bat` |
| 查看后端进程 | `tasklist | findstr pythonw` |
| 停止后端 | `taskkill /F /IM pythonw.exe` |
| 查本机 IP | `ipconfig`（看 WLAN 的 IPv4） |

---

## 6. 故障排查（数据没进来时按顺序查）

**① 电脑 IP 是否变了**（换/重启热点后）
```bash
ipconfig                 # 看 WLAN IPv4 还是不是 192.168.43.7
```
变了 → 在树莓派上改服务里的地址：
```bash
sudo nano /etc/systemd/system/collector.service     # 改 SERVER_URL 那行
sudo systemctl daemon-reload && sudo systemctl restart collector.service
```

**② 后端是否在跑**：`tasklist | findstr pythonw` → 没有就双击 `run_server.bat`

**③ 树莓派服务是否在跑**：`systemctl status collector.service` → 非 active 就 `sudo systemctl restart collector.service`

**④ 网络是否通**（树莓派上）：`curl http://192.168.43.7:5000/api/latest`
- 通 → 链路 OK
- 不通 → 检查是否同一热点、电脑防火墙 5000 端口是否放行

**⑤ 防火墙（若 ④ 不通，管理员 PowerShell）**
```bash
netsh advfirewall firewall add rule name="FYP Flask 5000 all" dir=in action=allow protocol=TCP localport=5000 profile=any
```

---

## 7. 传感器接线（供重接时参考）

| DHT22 引脚 | 接到树莓派 | 说明 |
|---|---|---|
| VCC / + | 3.3V（物理脚 1 或 17） | 两只共用同一 3.3V |
| GND / − | GND（物理脚 6/9/14 等） | 必须共地 |
| DATA / OUT | 传感器①→ GPIO4（物理脚 7）<br>传感器②→ GPIO17（物理脚 11） | 各接不同 GPIO |

- 模块版（带 PCB，3 脚）通常**自带上拉电阻**，直插即可
- 裸传感器（4 脚）需在 DATA 与 3.3V 间接 **4.7k–10kΩ 上拉电阻**

**单独测传感器**（树莓派上）：
```bash
python3 - <<'EOF'
import time, board, adafruit_dht
devs = {"dht22-01": adafruit_dht.DHT22(board.D4), "dht22-02": adafruit_dht.DHT22(board.D17)}
for i in range(5):
    for n, d in devs.items():
        try: print(n, d.temperature, "C", d.humidity, "%RH")
        except RuntimeError as e: print(n, "retry:", e)
    time.sleep(3)
EOF
```

---

## 8. 关键参数（默认值）

| 参数 | 默认 | 位置 |
|---|---|---|
| 采集间隔 | 60 秒 | collector.py `INTERVAL` |
| 温度阈值 | 15–30 °C | config.py `DEFAULT_THRESHOLDS` |
| 湿度阈值 | 20–70 %RH | config.py `DEFAULT_THRESHOLDS` |
| 告警抑制 | 600 秒 | config.py `ALERT_SUPPRESS_SECONDS` |
| 备份间隔 | 24 小时 | config.py `BACKUP_INTERVAL_HOURS`（0=关闭）|
| 备份保留 | 14 份 | config.py `BACKUP_KEEP` |
| 校准偏移 | 0 / 0（无校正）| calibration 表（见第 10 节）|
| 批次超时 | 20 分钟 | config.py `BATCH_TIMEOUT_MINUTES`（超时标失败并释放锁）|
| 批次历史条数 | 8 | batch.py `HISTORY_LIMIT` |
| WSL 发行版 | Ubuntu | config.py `BATCH_WSL_DISTRO` |
| 后端端口 | 5000 | app.py |

- 阈值可在**仪表盘的 "ALERT THRESHOLDS" 面板**实时修改（写入数据库）
- Telegram 凭证通过环境变量 `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` 设置（勿写死进代码）

---

## 9. Spark + Hive 批处理演示

大数据层：把后端采集的 CSV 送进 HDFS，用 Spark 做小时聚合，再用 Hive 建外部表跑 SQL 查询。

```
readings.csv → HDFS → PySpark 清洗+按小时聚合 → HDFS /iot/agg_hour/dt=YYYY-MM-DD/ → Hive 外部表 SQL 查询
```

> 这一节是**手动跑一次全量**（适合讲解整条链路）。
> 要做**增量处理、任意时间窗重跑**，见**第 12 节**。
> 聚合结果按天分区存放，表建成分区表 `PARTITIONED BY (dt STRING)`，下面的查询 A–H 不需要改。

### 一键运行

演示脚本：`iot_monitor/spark/demo_spark_hive.sh`

在 Windows 终端（CMD/PowerShell）直接运行：

```bash
wsl -d Ubuntu bash /mnt/c/Users/1/Desktop/FYP/iot_monitor/spark/demo_spark_hive.sh
```

或先 `wsl -d Ubuntu` 进系统，再：

```bash
bash /mnt/c/Users/1/Desktop/FYP/iot_monitor/spark/demo_spark_hive.sh
```

全程约 2–4 分钟，脚本自动完成 6 步，无需中途干预。

### 演示步骤与讲解要点

| 步骤 | 屏幕输出 | 讲解要点 |
|---|---|---|
| 1. HDFS + YARN | `NameNode :9000 OK` | 分布式存储与资源调度启动 |
| 2. Hive 服务 | `Metastore :9083`、`HiveServer2 :10000 OK` | Hive 元数据服务 + 查询服务 |
| 3. CSV → HDFS | 上传约 949 KB 的 `readings.csv` | 采集数据送入大数据存储 |
| 4. Spark ETL | `rows after cleaning` → `agg total rows` → `written to HDFS` | Spark 清洗 + 按传感器每小时聚合 avg/max/min 温湿度 |
| 5. Hive SQL 分析 | 5 类分析查询结果 | 用 SQL 做历史分析（见下表） |
| 6. 告警历史分析 | 按条件/传感器统计 + 时间线 | 对告警记录做 SQL 分析 |

### Hive 分析查询（第 5 步展示内容）

建好外部表后，用 SQL 回答"过去整段时间"的问题：

| 查询 | SQL 要点 | 回答什么问题 |
|---|---|---|
| **A. 超标小时** | `WHERE max_temp > 28` | 哪些小时温度越限（合规回顾） |
| **B. 累计超标小时数** | `COUNT(*) ... GROUP BY sensor_id` | 每个传感器一共多少小时不达标 |
| **C. 每日趋势** | `SUBSTR(hour,1,10) ... GROUP BY` | 按天的温湿度走势与极值 |
| **D. 数据完整性** | `WHERE cnt < 55` | 找出缺数小时，验证 ≥99% 采集率 |
| **E. 双传感器对比** | `CASE WHEN sensor_id=...` | 同小时两传感器差异，交叉校验一致性 |
| **F. 告警统计** | `GROUP BY condition, kind`（iot.alerts） | 各类告警 / 恢复各多少次 |
| **G. 告警按传感器** | `WHERE kind='alert' GROUP BY sensor_id` | 哪个传感器问题最多 |
| **H. 告警时间线** | `ORDER BY ts DESC LIMIT 10` | 最近的告警事件列表 |

示例（A. 超标小时）：

```sql
SELECT hour, sensor_id, ROUND(max_temp,1) AS peak_t
FROM iot.agg_hour WHERE max_temp > 28
ORDER BY max_temp DESC LIMIT 10;
```

示例（D. 数据完整性——验证 ≥99% 采集率）：

```sql
-- 每小时理论应有 60 条读数；列出不足的小时，即为采集缺口
SELECT hour, sensor_id, cnt
FROM iot.agg_hour
WHERE cnt < 55
ORDER BY cnt
LIMIT 10;
```

### 告警分析（F/G/H）需要先有告警数据

第 6 节的 [F][G][H] 读的是告警记录。如果还没有告警，会显示 `(no alert history to analyse yet)`。演示前先跑一次种子脚本生成告警：

```bash
bash seed_alerts.sh
```

它会：**重启后端**（清空 10 分钟的告警抑制状态）→ 对两颗传感器各制造一次温度越限 + 一次湿度越限（含恢复）→ 共 **8 条告警事件**，写入 `alerts` 表和 `alerts.csv`。

> 选项：`bash seed_alerts.sh --no-restart` 跳过重启（刚重启过后端时用）。
> 需在 Windows Git Bash 里运行（后端在那）。

### 手动查询（现场回答提问时用）

不用跑整个演示流程，只启动服务、自己敲 SQL：

1. **打开一个 WSL 终端并保持开着**：`wsl -d Ubuntu`
2. 启动服务（HDFS + YARN + Hive，约 1 分钟）：
   ```bash
   bash /mnt/c/Users/1/Desktop/FYP/iot_monitor/spark/start_hive_services.sh
   ```
3. 进入交互式 SQL 客户端：
   ```bash
   beeline -u jdbc:hive2://localhost:10000
   ```
4. 敲任意 SQL；`!quit` 退出。

> ⚠️ 必须在**保持打开**的 WSL 终端里跑（脚本会提示）。若用一次性 `wsl -d Ubuntu bash ...`，命令一返回 WSL 就关闭，服务随之停止。
> 前提是数据已跑过一次演示（`iot.agg_hour` 表存在）。

---

## 10. 传感器校准与自动备份

### 10.1 传感器校准（机制已就位，待参考仪器）

DHT22 出厂标定 ±0.5 °C / ±2 %RH。为支持"对照参考仪器校准"（proposal 风险 1 的应对），系统已内置**校准偏移机制**：

- 每颗传感器可设一组 `temp_offset` / `hum_offset`
- 后端**在入库时自动加上偏移**，因此库中存的是校正后的值
- 偏移默认 `0 / 0`（= 不做任何改动），未校准时完全无影响

**校准流程**（需要一台更准的参考温度计 / 湿度计）：

1. 把 DHT22 与参考仪器放在同一位置，静置几分钟
2. 读取参考仪器的数值
3. 运行工具（会自动取该传感器最近若干条读数求平均、算出偏移并保存）：

```bash
cd iot_monitor/server
python calibrate.py --sensor dht22-01 --ref-temp 25.4 --ref-hum 48.0
```

| 命令 | 作用 |
|---|---|
| `python calibrate.py --show` | 查看当前各传感器偏移 |
| `python calibrate.py --sensor dht22-01 --ref-temp 25.4` | 只校准温度 |
| `python calibrate.py --sensor dht22-02 --ref-hum 48.0` | 只校准湿度 |
| `GET/POST /api/calibration` | 通过接口读写偏移 |
| `bash demo_calibration.sh`（项目根目录，**需 Git Bash，见 10.4**）| **一键演示**：设置偏移 → 入库自动校正 → 自动清理 |

> ⚠️ `calibrate.py` 直接读写数据库文件，必须在 **Windows 端**运行（CMD 或 Git Bash）——
> 它使用 Windows 的数据库路径，在 WSL 里会找不到文件。

> 当前状态：**机制已实现并集成，尚无参考仪器，故未执行实际校准**（偏移保持 0/0）。拿到参考仪器后按上面步骤即可，无需改代码。

### 10.2 自动备份

后端**自带每日备份**，无需额外配置：

- 服务启动时先备份一次，之后**每 24 小时**自动备份
- 备份内容（存于 `server/data/backups/<时间戳>/`）：`monitor.db`（用 SQLite 备份 API 取的**一致性快照**，服务运行时也安全）、`readings.csv`、`alerts.csv`、`alerts_table.csv`
- 自动保留最近 **14 份**，更早的自动删除

| 项 | 值 | 位置 |
|---|---|---|
| 备份间隔 | 24 小时 | config.py `BACKUP_INTERVAL_HOURS`（设 0 可关闭）|
| 保留份数 | 14 | config.py `BACKUP_KEEP` |
| 存放目录 | `server/data/backups/` | — |
| 手动备份 | `python backup.py`（在 `server/` 下运行）| — |
| **一键演示** | `bash demo_backup.sh`（项目根目录，**需 Git Bash，见 10.4**）| — |

### 10.3 备份功能演示

运行 `bash demo_backup.sh` 会自动展示 5 项证据：

1. 备份目录里一排带时间戳的文件夹
2. 最新一份备份的内容（monitor.db / readings.csv / alerts.csv / alerts_table.csv）
3. 备份库与实时库**逐项对比**（行数、表结构一致 = 快照完整可用）
4. **证明确实自动**：重启后端 → **最新备份自动更新**（保留份数固定为 14，新备份挤掉最旧的）
5. 后端状态确认

> 答辩时：截 `backups/` 目录图 + 演示输出图，即为"自动备份已实现"的实证。

### 10.4 运行演示脚本的环境要求 ⚠️

两个演示脚本都是 **bash 脚本**，必须在 **Windows 的 Git Bash** 里运行：

| 环境 | `demo_backup.sh` | `demo_calibration.sh` |
|---|---|---|
| **Git Bash** | ✅ 完整（第 5 步显示 HTTP 200）| ✅ 完整 |
| WSL (Ubuntu) | ⚠️ 能跑，但第 5 步只能查进程状态 | ❌ 跑不了 |
| CMD | 需显式调用 Git 的 bash（见下）| 同左 |

**为什么 WSL 不行**：`demo_calibration.sh` 要访问后端 API（`localhost:5000`），而 WSL 连不到 Windows 的 localhost。

#### 正确打开方式

**方式 A（推荐）**：文件资源管理器进入 `C:\Users\1\Desktop\FYP`，空白处**右键 → "Git Bash Here"**，然后运行：

```bash
bash demo_backup.sh
```

```bash
bash demo_calibration.sh
```

**方式 B**：在 **CMD** 里显式指定 Git 的 bash：

```
cd /d C:\Users\1\Desktop\FYP
D:\Git\bin\bash.exe demo_backup.sh
```

```
cd /d C:\Users\1\Desktop\FYP
D:\Git\bin\bash.exe demo_calibration.sh
```

> ⚠️ **在 CMD 里直接敲 `bash` 会跑在 WSL 里**——系统 PATH 中 `C:\Windows\System32` 排在 `D:\Git\cmd` 之前，`bash` 命中的是 WSL 启动器 `C:\Windows\System32\bash.exe`。
> 必须用全路径 **`D:\Git\bin\bash.exe`**（注意是 **bin** 目录，不是 `usr\bin`）。

#### 怎么确认自己在 Git Bash

提示符里带 **`MINGW64`** 就是 Git Bash：

```
user@PC MINGW64 /c/Users/1/Desktop/FYP
$
```

若看到 `swb@Swb:~$` → 那是 WSL，请改用上面的方式 A 或 B。

---

## 11. 仪表盘功能说明

| 区域 | 功能 |
|---|---|
| 顶部健康条 | 整体状态（NOMINAL/ALERT）、平均温湿度、在线传感器数 |
| 传感器卡片 | 当前读数 + 径向仪表 + **趋势徽章**（▲/▼ 与变化量，如 `▲ +0.9 °C/h`）|
| **趋势摘要** | **用文字描述变化方向**，如 "dht22-01 over the last 1 hour: temperature is rising steadily (+0.9 °C), humidity is falling quickly (-11.2 %RH)." |
| 24 小时趋势图 | 折线图，可切换 All / 单个传感器 |
| 告警阈值 | 在线修改阈值，立即生效 |
| 导出数据 | 按日期范围 + 传感器导出 CSV |
| **流水线进度条** | 点 Process 后，顶部进度条**逐站点亮**：Export → Services → Spark → HDFS → Hive → Done，右侧秒表实时走。Spark 自己打印的日志**可选查看**（默认收起，点 `Log ▾` 展开）。阶段来自脚本真实输出，不是估算（见第 12.3 节）|
| **批处理（批次卡片）** | 自己创建时间段（名称 + 下拉预设或自定义起止）→ 每张卡片**默认折叠成三行**：名称 / 时间范围 / 统计行（读数条数 + 温湿度 avg 与 min–max + 异常条数 + 上次处理结果）。点标题行展开，出现两个查询按钮（**Show abnormal** 按告警阈值、**Range query** 按你填的温度/湿度范围）、三个选项卡 **Abnormal / Readings / Alerts**（该段内的异常时间点含原因、每条原始读数分页、告警事件），以及 **Process**（单独送 Spark）/ **Delete**（只删定义，已处理数据保留）。见第 12 节 |
| **报表（从 Hive 读）** | **在本页点过一次 Process 之后这个面板才会出现** —— 批次是报表数据的来源，这样因果关系看得见；**刷新页面会重新隐藏**。四个按钮：**Hourly heatmap**（24 小时 × 日期的热力图，悬停看该小时 min/avg/max）、**Daily trend**（含采集完整度）、**Temperature spikes**（每小时温变最猛的时段 → 突发事件）、**Risk hours**（温湿度同时偏高 → 最伤设备的时段）。**数据全部来自 Hive**，即 Spark 的产物；每次查询几秒，后端有缓存（见第 13 节）|

> 原来独立的 **History** 和 **Alert History** 两个面板已经并入批次卡片 —— 它们现在是"**按某个批次的时间段**"来看，而不是全局看。

### 相关接口

| 接口 | 作用 |
|---|---|
| `GET /api/readings?start=&end=&sensor_id=&limit=&offset=` | 通用分页读读数（按日期范围；批次卡片改用下面的窗口版）|
| `GET /api/daily?start=&end=&sensor_id=` | 按天 + 按传感器的聚合（min/avg/max）|
| `GET /api/latest` | 实时读数；**额外返回每传感器的 `trend`**（相对 N 分钟前的变化量）|
| `GET /api/alerts?limit=` | 通用告警查询（按数量；批次卡片用下面的窗口版）|
| `GET /api/calibration` / `POST` | 校准偏移读写 |
| —— **批次定义** —— | |
| `GET /api/batch/windows` | 全部批次 + 每批的统计、异常数、上次处理状态 |
| `POST /api/batch/windows` | 创建批次 `{name?, from, to}`（from/to 是本地时间，服务端转 UTC）|
| `DELETE /api/batch/windows/<id>` | 删除批次定义（不动已处理的数据）|
| `GET /api/batch/windows/<id>/outliers?t_min=&t_max=&h_min=&h_max=` | 窗口内落在该范围**之外**的读数。**不传范围 = 用告警阈值**（面板的 Show abnormal）|
| `GET /api/batch/windows/<id>/readings?limit=&offset=` | 窗口内每条读数（分页）|
| `GET /api/batch/windows/<id>/alerts?limit=` | 窗口内的告警事件 |
| —— **批处理运行** —— | |
| `GET /api/batch` | 水位线 + 正在跑的批次 + 最近批次列表 + 实时阶段进度 |
| `POST /api/batch/run` | 起一次处理。`{from,to}` 本地时间 / `{from_iso,to_iso}` 精确 UTC（批次卡片用这个）/ `{full:true}` 全量重建。**202** 已启动 / **409** 忙 / **400** 窗口非法 |
| —— **报表（读 Hive）** —— | |
| `GET /api/hive/report?name=` | 跑一个报表。`name` ∈ `heatmap` / `trend` / `spike` / `risk`。**503** = Hive 没跑或查询失败 |

> 趋势窗口默认 1 小时，可用 `GET /api/latest?window=15`（分钟）调整。

---

## 12. 批处理调度（增量处理 + 任意调度）

第 9 节是**手动跑一次全量**。这一节是它的数据管理版本：**分批次处理**（只处理新数据）、**随意调度**（自选时间窗，任意片段可重跑），并且**幂等**（重复跑不产生重复数据）。

**"批次"在界面上 = 一个你自己命名的时间段**，存在数据库里（`batch_windows` 表），随时可查、可折叠、可单独处理、可删除。同一段时间反复处理结果都一样。

### 12.1 两个核心概念

**水位线（watermark）** —— 上次**成功**批次处理到的时刻。它**记在数据库里，但界面上不显示**。

- 只有在**调接口不带时间窗**时才会用到它：从水位线之后接着处理 —— 这就是"增量"
- 首次运行水位线为空 → 处理全部历史（跑一次之后自然变成增量）
- **水位线只在批次成功时推进**；失败就不动，所以失败的那段数据不会丢，直接重跑即可
- 界面上的批次卡片**始终带明确的时间窗**，走的是显式窗口，不经过水位线 —— 所以日常使用时它对你不可见

**按天分区 + 动态覆写** —— 聚合结果按 `dt=YYYY-MM-DD` 分目录存放，写入用 Spark 的 `partitionOverwriteMode=dynamic`，即**只覆盖这次批次碰到的那几天**，其它天原封不动。所以同一个时间窗跑多少次，结果都一样。

> 这正是"随意调度"能成立的前提：不需要先清理，随便挑一个历史窗口重跑，结果都正确。

### 12.2 保活进程（决定点一次 Run 要等多久）

WSL2 在 `wsl.exe` 调用返回后会**关掉整个发行版**，里面的 HDFS/Hive 守护进程一起死。所以两条路：

| 保活进程 | 点一次 Run 要等 | 说明 |
|---|---|---|
| **在跑** | 约 30–60 秒 | 服务已就绪，只跑 Spark + 注册分区 |
| 没跑 | 约 1–4 分钟 | 脚本会**自己把服务起起来**（自愈），结果一样，只是慢 |

用法：双击项目根目录的 **`start_wsl_keeper.bat`**，它会起 HDFS + Hive 然后一直持有发行版。**这个窗口必须保持开着。**

开机自启：给 `start_wsl_keeper.bat` 建个快捷方式放进 `Win+R → shell:startup`（跟后端自启同一个套路）。

> ⚠️ **在 Git Bash 里手动跑 WSL 脚本必须加 `MSYS_NO_PATHCONV=1`**，否则 Git Bash 会把 `/mnt/c/...` 改写成 `D:/Git/mnt/c/...` 导致"文件不存在"：
> ```bash
> MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu bash /mnt/c/Users/1/Desktop/FYP/iot_monitor/spark/batch_run.sh --csv ... --result ...
> ```
> 后端调用（`subprocess` 传参数组）和 `.bat`（走 cmd.exe）都不受影响，只有 Git Bash 命令行需要。

### 12.3 仪表盘：BATCH PROCESSING 面板

**① 顶部：流水线进度条**（点 Process 后逐站点亮）

```
● Export  →  ● Services  →  ◐ Spark  →  ○ HDFS  →  ○ Hive  →  ○ Done        12s
```

六个站点按数据实际的流向排列，**处理到哪一站，哪一站就亮**（灰=未到，琥珀色脉动=进行中，绿=完成，红=失败）。右侧是**秒表**，运行中实时走，结束后显示这次的总耗时。

秒表旁边有一个 **`Log ▾`** 按钮，**默认收起** —— 这时整块只占进度条那一行。点一下展开，显示这次运行的**完整日志**：

```
---- Spark ETL ----
rows after cleaning: 560
agg total rows: 8
writing hourly aggregates to HDFS ...
written to HDFS: hdfs://localhost:9000/iot/agg_hour/
  rows_in=560 rows_out=8 partitions=["2026-09-18"]
---- Hive partition registration ----
| 369 |
==================== BATCH COMPLETE ====================
```

再点一下收起（箭头变 ▴/▾）。展开状态**会保持**，不会被自动刷新弄回去；没有日志时（后端刚重启）按钮自动隐藏。

**这些阶段不是估算的**：后端把 `spark-submit` 的输出**边跑边读**，按脚本里的标记行切换阶段。所以亮到哪一站，就是真的跑到哪一站。

实测一次 560 行的处理（约 25 秒）：

| 时刻 | 亮到哪 |
|---|---|
| 1s | Export ✓ → Services 进行中 |
| 4s | Services ✓ → **Spark 进行中（约 11 秒）** |
| 15s | Spark ✓ → **HDFS 进行中**（写分区）|
| 18s | HDFS ✓ → **Hive 进行中**（注册分区）|
| 25s | 全部 ✓，秒表停在 25.0s |

> 答辩时这就是"数据是怎么被处理的"最直观的一屏：**看着它一站点一站点走完 采集→导出→Spark→HDFS→Hive**。而且日志区里 Spark 自己打印的行数就是证据。

**② 顶部：创建批次**

名称 + 时间段下拉（Custom / Last hour / Last 24 hours / Last 7 days / All data）+ 起止时间 → `Create batch`。
下拉只是快速把时间框填好，仍然可以手改；名称留空会用时间范围自动生成。

**③ 中间：每个时间段一张卡片**

**默认折叠**，只有三行 —— 点标题行（或左边的 ▸）展开：

```
▸ 09-18 demo day
  2026-09-18 00:00 → 2026-09-19 00:00
  560 readings | temperature avg 26.6 °C (23.9–32.5) | humidity avg 50.7 %RH (37.5–81.0) | 12 abnormal | processed · 8 hourly rows · 122s
```

展开后多出这些：

| 卡片元素 | 含义 |
|---|---|
| **Show abnormal** | 按 `ALERT THRESHOLDS` 判定，列出超出阈值的读数 —— 结果停在 **Abnormal** 标签 |
| **温度/湿度范围 + Range query** | 填温度区间和湿度区间，列出落在区间**之外**的读数 —— 结果落在 **Readings** 标签 |
| **Abnormal / Readings / Alerts** | 三个选项卡：阈值异常结果 / 该段每条原始读数（分页）/ 该段告警事件 |
| **Process** | 用这个窗口单独跑一次 Spark（**精确到秒**，不经过水位线）|
| **Delete** | 只删批次定义 —— **已处理进 Hive 的数据和运行记录都保留** |

折叠/展开**纯属显示，不发任何请求**：已经查出来的结果留在页面上，收起再展开不会重新查。新建的批次会自动展开，方便确认创建成功。

两个查询按钮的区别是**判定标准**和**结果落在哪个标签**：

- **Show abnormal** → 停在 **Abnormal**，用告警阈值判定
- **Range query** → 切到 **Readings**，等价于**给 Readings 加一个过滤器**

**Range query 之所以落在 Readings**：它本质上就是"把这批读数里超出范围的筛出来"，放在读数该在的地方更自然，也不会把视图从你正在看的标签上拽走。手动点 **Readings** 标签就会回到**不带筛选**的完整列表（带分页）。

两张结果表都有 **Reason** 列说明触发了哪个条件（可同时多个，如 `temp>28, hum<40`），摘要行还会写明判定框，例如：

```
51 readings outside 20–28 °C and 40–60 %RH      ← Range query
12 readings outside 20–29 °C and 20–75 %RH      ← Show abnormal（告警阈值）
```

**④ 顶部徽章** —— `IDLE` / `RUNNING`，表示有没有批次正在跑。

> 处理是**手动触发**的（点卡片的 `Process`，或调 `POST /api/batch/run`）。没有内置的定时调度 —— 系统的定位是"你决定什么时候处理、处理哪一段"。
>
> **全量重建**（忽略水位线，从最早一条数据重写所有分区）在界面上没有按钮，需要时调接口：`POST /api/batch/run {"full": true}`。它是分区出问题时的恢复手段，日常用不到。

### 12.4 命令行

```bash
cd iot_monitor/server
python batch.py            # 立即跑一个增量批次
python batch.py --full     # 全量重建
```

### 12.5 怎么验证做对了

**幂等（最重要）** —— 用同一个时间窗跑两次，总数不变：

```sql
SELECT COUNT(*) AS hourly_rows FROM iot.agg_hour;
```

**分区** —— 看每天一个目录：

```sql
SHOW PARTITIONS iot.agg_hour;
SELECT dt, COUNT(*) FROM iot.agg_hour GROUP BY dt ORDER BY dt;
```

**并发** —— 批次运行期间再点一次 Run，接口返回 `409 busy`，不会产生第二个批次。

### 12.6 处理结果在哪里看

批次卡片本身已经能看到**这个时间段内**的数据：`Readings`（每条原始读数）、`Alerts`（告警事件）、`Abnormal`（异常时间点）三个选项卡，加上卡片上的统计行。下面两处是看**处理产物**——Hive 里那份小时聚合——的地方。

**① 仪表盘的「Reports from Hive」面板**（页面最下面）

点 **Hourly heatmap** → 24 小时 × 日期 的格子，颜色深浅代表温度。**鼠标悬停任意格子**就能看到那一小时的完整数值：

```
2026-09-03 04:00 · 23.9°C (22.1–26.0) · 49.0%RH (44.0–55.9) · 120 samples
```

即 **均温（最低–最高）· 均湿（最低–最高）· 读数条数** —— 相当于把"每小时一行"的表格压缩成了可交互的图。灰色格子表示那一小时没有数据。

另外三个报表（Daily trend / Temperature spikes / Risk hours）见第 13 节。

**② Hive（要完整的 SQL 能力时）**

```bash
wsl -d Ubuntu
```

```bash
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export HIVE_HOME=$HOME/apache-hive-4.2.1-bin
export PATH=$JAVA_HOME/bin:$HIVE_HOME/bin:$PATH
beeline -u jdbc:hive2://localhost:10000
```

```sql
SELECT hour, sensor_id, ROUND(avg_temp,1) AS avg_t, ROUND(max_temp,1) AS max_t,
       ROUND(min_temp,1) AS min_t, cnt
FROM iot.agg_hour ORDER BY hour DESC LIMIT 20;
```

`!quit` 退出。Hive 里能做面板做不了的复杂查询（CASE WHEN、跨传感器对比、多表 join 等）。

> 前提：`start_wsl_keeper.bat` 的窗口开着（服务在跑）；并且至少跑过一次批次，`iot.agg_hour` 里才有数据。

**`Readings` 那一列是数据质量探针**：正常一小时约 60 条，远低于 60 说明那小时采集断了，远高于 60 说明有重复/回填数据。

### 12.7 不用 SQL 也能看到 Spark：Web UI

Spark 跑任务时会自己起一个 Web UI，**在浏览器里就能看到 DAG 图、stage、task、shuffle 读写量** —— 不用写一行 SQL，也不用开终端。

**地址：** `http://localhost:4040`

**前提（重要）**：`start_wsl_keeper.bat` 那个窗口必须开着。

实测结果：

| 保活进程 | 点 Process 后访问 `localhost:4040` |
|---|---|
| **开着** | **约 4 秒**就能打开，页面标题是 `iot_etl - Spark Jobs` |
| 没开 | **访问不到** —— 发行版是冷的，4040 存活时间只有十几秒，WSL 的 localhost 转发来不及建立 |

> 顺带验证过：WSL 的端口转发本身是好的（HDFS 的 Web UI `localhost:9870` 一直能访问）。4040 打不开纯粹是因为它**存活时间太短**，不是网络问题。

**怎么演示：**

1. **先**把标签页打开 → `http://localhost:4040`
2. 回到仪表盘，点某个批次的 **Process**
3. 切回 4040 那个标签（页面会自动刷新）→ 出现 **`iot_etl`** 应用
4. 点进去看 **Jobs / Stages** → DAG 可视化、每个 stage 的 task 数与耗时、shuffle 读写量

**注意窗口很短**：这个 UI **只在该次 Spark 任务运行期间存在**（约 10–20 秒）。ETL 结束时会调用 `spark.stop()`，JVM 退出，4040 随即关闭。所以**必须先开标签页再点 Process**，反过来一定看不到。

**它有什么**：`iot_etl` 应用的 Jobs / Stages / Storage / Environment / Executors 五个页面。答辩时最有说服力的是 **Stages 页的 DAG 图** —— 那是 Spark 把这次聚合拆成 stage 和 task 的直观证据，比任何表格都硬。

### 12.8 一个已知的数据不一致 ⚠️

批处理读 **SQLite**（系统的记录源），而第 9 节的演示脚本读 **`readings.csv`**（追加式原始日志）。**这两个存储目前已经对不上**：

| 日期 | readings.csv | SQLite | 差 |
|---|---|---|---|
| 2026-09-06 | 1214 | 1212 | 2 |
| 2026-09-13 | 14 | **0** | 14 |
| 2026-09-18 | 564 | 560 | 4 |
| **合计** | **24405** | **24385** | **20** |

后果：跑完演示脚本，Hive 里是 **369** 条小时聚合；用批处理面板跑，是 **364** 条。差的正是那 20 行 —— 两个数字都对，只是来源不同。

想统一的话有两个方向：把缺的行补进 SQLite，或者让演示脚本也改成从 SQLite 导出（与批处理同一个源）。**在你决定之前，不要把任何一个数字当成"正确值"。**

---

## 13. 报表：不懂 SQL 也能用上大数据层

第 12 节做的是"把数据算出来、存进 Hive"。这一节回答另一半问题：**不会写 SQL 的人，怎么用上这一层？**

答案是把常用分析做成按钮 —— 用户只看到图和表，完全不知道背后有 beeline 和 Spark。

### 13.1 四个报表

| 按钮 | 回答什么问题 | 长什么样 |
|---|---|---|
| **Hourly heatmap** | 哪些时段容易出问题？ | 24 小时 × 日期 的格子，颜色=温度（青 → 琥珀 → 红），灰格子=那小时没数据；**悬停看该小时的 min / avg / max** |
| **Daily trend** | 机房是不是在变热？数据可不可信？ | 每天每传感器一行：Avg °C、**Temp trend 条**（按**中间 80% 的天数**缩放，免得某个薄数据日把其它天压平）、Peak、Low、Avg %RH、Samples、**Hours / 24**、**Captured** |
| **Temperature spikes** | 哪一小时出事了？ | 每小时与前一小时之间温变最大的时段，降序；`+1.68°C` 暖色、`-1.25°C` 冷色 |
| **Risk hours** | 哪几小时最伤设备？ | 温湿度**同时**偏高的时段（按小时的**极值**判定），带一个 **Stress** 百分比 |

**"系统没开机"和"采集中断"是两个问题**，Daily trend 最后两列把第二个说清楚了：

- **Hours / 24** = 那天有数据的小时数 → "**系统开着吗**"
- **Captured** = 样本数 ÷ (有数据的小时数 × 60) → "**开着的时候每分钟都记了吗**"

当前库里的真实数据：

| 日期 | Hours | Captured | 说明 |
|---|---|---|---|
| 08-31 | 24 / 24 | **100%** | 全天开机，一分钟没漏 |
| 08-30 | 17 / 24 | **98%** | 开了 17 小时，其间漏了 2% |
| 09-18 | 8 / 24 | **117%** | 开着时采得过密（有回填 / 重复读数）|

**"≥99% 采集率"这类主张要基于 Captured 说，不要基于"样本数 ÷ 1440"** —— 后者会把"系统没开机"算成"采集丢失"，把一个 98% 的日子说成 70%。

**Risk hours 为什么用极值而不是均值**：09-18 13:00 那一小时内部同时存在 81%RH 的潮湿读数和 32.5°C 的高温读数，但**小时均值只有 51.9%RH** —— 按均值判定会**完全漏掉这一小时**。而"短暂冲到高温且高湿"才是真正伤设备的，所以 Risk hours 用 `max_temp` / `max_hum`。

**判定门槛来自你的告警阈值**：温度上限 − 3°C、湿度上限 − 10%RH 当作"接近上限"。改了 Alert Thresholds，这个列表跟着变。

### 13.2 数据真的来自 Hive

这是这一节存在的意义：报表**全部从 `iot.agg_hour` 取数**（走 beeline），而不是从面板那个 SQLite 副本现算。

```
点「Hourly heatmap」
   → 后端通过 WSL 调 beeline 查 Hive
   → 结果以 TSV 回传、解析成 JSON
   → 前端画成热力图
   → 用户看到图，全程不知道有 SQL 和 Spark
```

面板顶部会写明来源，例如 `186 rows from Hive | just computed | last batch #19 (24s, 8 hourly rows)` —— 当场能看出这批数字是哪个批次算出来的。

### 13.3 速度与缓存

每次查询要起 beeline，**约 6 秒**。所以后端把结果缓存在内存里（`hive.py`），并且**每次批次处理结束后自动失效**（`hive.invalidate()`）。

- 第一次点某个报表：约 6 秒
- 再点、或刷新页面：**瞬间**
- 跑完一次 Process：缓存失效；**当前显示的那个报表会自动重查一次**，于是新批次的效果立刻可见

这里缓存几乎总是命中 —— 因为 **Hive 里的数据在两次批次处理之间不会变**。

### 13.4 面板什么时候出现（在本页点过 Process 才会）

**整个「Reports from Hive」面板默认隐藏**，只有**在本次页面里跑完一次成功的 Process** 才会出现 —— 出现的同时自动加载热力图。

这是有意设计的：**批次处理是这些报表的数据来源**，把"先处理、后有报表"的因果直接摆出来，比分批次处理本身更能说明问题。

具体行为：

| 时刻 | 面板 |
|---|---|
| 打开 / **刷新页面** | **隐藏**（哪怕库里已经有处理过的数据）|
| 点 Process，处理**进行中** | 仍然隐藏 |
| 处理**成功结束** | **出现** + 弹提示 + 自动加载热力图 |
| 之后再跑一次 | 已显示，且当前报表自动重查，反映新批次 |
| 从**别处**发起的处理（另一个标签页 / 直接调接口）| **不会**让本页面板出现 |

**刷新页面会重新隐藏** —— 这样每次演示都能重现"点 Process → 报表出现"的效果。库里已有的处理结果一直都在，只是不会自动把面板摆出来。

所以演示顺序天然是：

1. 建一个批次 → 点 **Process** → 看顶部进度条逐站点亮
2. 跑完 → 报表面板出现 + 弹一条提示 → 热力图开始加载
3. 看报表

> 这条规则只影响**面板是否显示**。想再看报表时，刷新后点一次 Process 即可（约 25 秒）。

另外：**`start_wsl_keeper.bat` 的窗口要开着**。Hive 没跑时报表会提示先去启动，不会干等。

### 13.5 ⚠️ 修过的一个环境坑：HiveServer2 堆只有 256MB

**症状** —— 查了几条之后，之后每一条都失败，任务在 `map = 0%` 就挂、一行数据没读：

```
ERROR : Ended Job = job_local... with errors
FAILED: Execution Error, return code 2 from org.apache.hadoop.hive.ql.exec.mr.MapRedTask
INFO  : Stage-Stage-1:  HDFS Read: 0 HDFS Write: 0  FAIL
```

看起来像 HDFS 坏了，**其实不是**（当时 HDFS 报告完全健康、内存也充足）。

**根因**：`bin/hive-config.sh` 里写死 `HADOOP_HEAPSIZE=256`，而 `conf/hive-env.sh` **默认不存在** —— 所以 HiveServer2 只有 **256 MB 堆**。Hive 每执行一条查询都会生成新类，256MB 跑 4–5 条就耗尽，之后所有 MR 任务都起不来。

**修法**：创建 `$HIVE_HOME/conf/hive-env.sh`：

```sh
if [ "$SERVICE" = "hiveserver2" ]; then
  export HADOOP_HEAPSIZE=1024
fi
if [ "$SERVICE" = "metastore" ]; then
  export HADOOP_HEAPSIZE=768
fi
```

然后重启 Hive 服务。**已经配好了**（现在是 `-Xmx1024m` / `-Xmx768m`）。修完连跑 8 条查询 0 失败；修之前是第 5 条起必挂。

> **以后再看到 `return code 2 from MapRedTask`**：先重启 HiveServer2（`pkill -f HiveServer2` 再启动）—— 立刻恢复。这是对照测试确认过的。

### 13.6 为什么值得这么做

对使用者：

- **不用学 SQL** —— 点按钮就有图和表
- **回答的是长期问题** —— "这个月有没有变热""哪个传感器该换了"，实时面板答不了
- **大数据层真的在服务用户** —— 不是演示脚本里的摆设，而是报表的数据源

对项目：

- 答辩能讲清"**为什么要用 Spark/Hive**"：报表读的就是它算出来的表，SQLite 副本只是热数据
- 顺带证明了 Spark 算的结果与面板本地算的**逐行一致**（见第 12.6 节）






