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
                         历史浏览（分页表格+按天汇总）/ 告警历史 / 阈值设置 / CSV 导出

[离线缓冲] 网络不通时 collector 先写 offline_buffer.csv，恢复后自动补发 → 保障 ≥99% 采集率
[告警历史] 每次越限与恢复记入 alerts 表 + alerts.csv，可在仪表盘查看、可交 Hive 分析
[批处理层] readings.csv / alerts.csv → PySpark 按小时聚合 → HDFS → Hive 外部表查询（WSL2 单机伪分布式）
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
├── FYP Progress Report ...docx 进度报告文档
├── FYP Proposal ...docx/pdf    项目计划书
└── iot_monitor/
    ├── sensor/                 ── 部署到树莓派 ──
    │   ├── collector.py        采集 + 上报 + 离线缓冲
    │   ├── requirements.txt    adafruit-circuitpython-dht 等依赖
    │   └── offline_buffer.csv  离线缓存（运行生成）
    ├── server/                 ── 运行在 Windows 电脑 ──
    │   ├── app.py              Flask 主程序（API + 页面 + 每日自动备份线程）
    │   ├── config.py           配置：路径、默认阈值、告警参数、备份设置
    │   ├── database.py         SQLite 读写（readings / thresholds / alerts / calibration）
    │   ├── alerts.py           阈值判断 + Telegram 发送 + 告警历史记录
    │   ├── calibrate.py        传感器校准工具（见第 10 节）
    │   ├── backup.py           备份脚本（见第 10 节）
    │   ├── static/index.html   前端仪表盘
    │   ├── data/               数据库与 CSV（运行生成）
    │   │   └── backups/        自动备份（运行生成）
    │   └── spark/
    │       ├── spark_etl.py            PySpark 聚合任务
    │       ├── demo_spark_hive.sh      Spark + Hive 一键演示（见第 9 节）
    │       └── start_hive_services.sh  仅启动 Hive 服务，供手动查询
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
| 后端端口 | 5000 | app.py |

- 阈值可在**仪表盘的 "ALERT THRESHOLDS" 面板**实时修改（写入数据库）
- Telegram 凭证通过环境变量 `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` 设置（勿写死进代码）

---

## 9. Spark + Hive 批处理演示

大数据层：把后端采集的 CSV 送进 HDFS，用 Spark 做小时聚合，再用 Hive 建外部表跑 SQL 查询。

```
readings.csv → HDFS → PySpark 清洗+按小时聚合 → HDFS /iot/agg_hour → Hive 外部表 SQL 查询
```

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
| 4. Spark ETL | `清洗后行数` → `agg 总行数` → `已写入 HDFS` | Spark 清洗 + 按传感器每小时聚合 avg/max/min 温湿度 |
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
| `bash demo_calibration.sh`（项目根目录）| **一键演示**：设置偏移 → 入库自动校正 → 自动清理 |

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
| **一键演示** | `bash demo_backup.sh`（项目根目录）| — |

### 10.3 备份功能演示

运行 `bash demo_backup.sh` 会自动展示 5 项证据：

1. 备份目录里一排带时间戳的文件夹
2. 最新一份备份的内容（monitor.db / readings.csv / alerts.csv / alerts_table.csv）
3. 备份库与实时库**逐项对比**（行数、表结构一致 = 快照完整可用）
4. **证明确实自动**：重启后端 → 备份份数自动 +1
5. 后端状态确认

> 答辩时：截 `backups/` 目录图 + 演示输出图，即为"自动备份已实现"的实证。

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
| 告警历史 | 越限与恢复记录（时间/传感器/类型/条件/读数/限值）|
| **历史浏览** | 时间范围 + 传感器筛选 → **分页表格**（每条读数）+ **汇总统计**（条数与温湿度 min/avg/max）；可切换 **"按天汇总"** 视图 |

### 相关接口

| 接口 | 作用 |
|---|---|
| `GET /api/readings?start=&end=&sensor_id=&limit=&offset=` | 分页浏览历史读数，返回 rows / total / summary |
| `GET /api/daily?start=&end=&sensor_id=` | 按天 + 按传感器的聚合（min/avg/max）|
| `GET /api/latest` | 实时读数；现在**额外返回每传感器的 `trend`**（相对 N 分钟前的变化量）|
| `GET /api/alerts?limit=` | 告警历史 |
| `GET /api/calibration` / `POST` | 校准偏移读写 |

> 趋势窗口默认 1 小时，可用 `GET /api/latest?window=15`（分钟）调整。





