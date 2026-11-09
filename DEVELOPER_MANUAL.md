# Project Eos 开发说明书

> 面向共同开发者的工程手册。最后更新：2026-11-09，对应当前代码与 72 项测试。
>
> 代码是最终事实来源；当本文与代码不一致时，以代码为准，并请顺手更新本文。

---

## 目录

1. [项目定位与当前状态](#1-项目定位与当前状态)
2. [快速启动](#2-快速启动)
3. [架构总览](#3-架构总览)
4. [代码地图](#4-代码地图)
5. [核心数据模型与不变量](#5-核心数据模型与不变量)
6. [规则引擎与动作协议](#6-规则引擎与动作协议)
7. [模拟子系统](#7-模拟子系统)
8. [城市系统专章](#8-城市系统专章)
9. [AI 系统](#9-ai-系统)
10. [存档、回放与确定性](#10-存档回放与确定性)
11. [HTTP API](#11-http-api)
12. [前端 dashboard.html](#12-前端-dashboardhtml)
13. [配置系统](#13-配置系统)
14. [地图与美术](#14-地图与美术)
15. [测试与验收](#15-测试与验收)
16. [团队协作规范](#16-团队协作规范)
17. [常见故障排查](#17-常见故障排查)
18. [已知限制与路线图](#18-已知限制与路线图)
19. [附录：快速参考](#19-附录快速参考)

---

## 1. 项目定位与当前状态

Project Eos 是一个本地运行的文明模拟沙盘：

- 72×54 pointy-top 六边形世界，默认四国（支持 2–12 国），逐日推进，可暂停/倍速。
- 玩家可以观战，也可以随时接管任意一国；AI 与玩家使用同一套规则。
- 世界地图 + 城市局部地图双层视角；城市有独立人口、分区、粮食、预算、宜居度和 AI 市长。
- 所有动态状态由规则引擎写入，AI 只提交 JSON 动作，便于复盘、回放和调试。
- 前端是单页本地指挥台，通过 `127.0.0.1` HTTP 与 Python 引擎通信。
- 无数据库、无云端依赖、无第三方前端框架；存档是 JSON。

当前已具备的主要闭环：

| 领域 | 已实现 |
| --- | --- |
| 地图 | 固定基线世界、公平随机地图、自定义 2–12 国、六种地图图层 |
| 经济 | 粮食、仓容、财政、税收、矿业、建筑维护、贸易协定、城市地方预算 |
| 人口 | 住房、增长、饥荒、城市人口分账、宜居度 |
| 科技 | 三条科技线、六级、时代门槛、开局年代基线 |
| 城市 | 新城扩张、分区、邻接、方针、粮食物流、地方预算、AI 市长、手动/AI 托管 |
| 外交 | 关系、赠礼、贸易协定、和平提案 |
| 军事 | 招募、行军、宣战、边境/远征战斗、占领、战争疲劳、和平 |
| 目标 | 综合评分、四条正式胜利路线、自动结算、继续本局 |
| AI | 多国规则 AI、OpenAI 兼容模型、逐国切换、预算/Token 记录、失败回退 |
| 工程 | 存档槽、自动保存、动作日志回放、世界哈希校验、72 项 pytest |

设计原则（来自 `PROJECT_PLAN.md`）：

1. 真实性服务游戏性，但系统必须可解释、可复盘。
2. 新系统必须进入真实结算，不能只显示在日志或 UI。
3. AI 与玩家经过同一规则审核器。
4. 先完成闭环，再做精细表现。

---

## 2. 快速启动

### 2.1 环境要求

- Python **3.10+**（当前开发环境为 3.14）。
- Windows / macOS / Linux 均可。
- 依赖：`numpy`、`scipy`、`matplotlib`；测试另需 `pytest`。
- 建议把虚拟环境和大文件放在 **D 盘**，不要占用空间紧张的 C 盘。

### 2.2 首次安装（Windows / Git Bash）

```bash
cd /d/CCCQoder/project_eos/Project_Eos_Map_Generation_v0.1
python -m venv .venv
./.venv/Scripts/python -m pip install -r requirements.txt pytest
./.venv/Scripts/python -m pytest -q
```

PowerShell / cmd 中使用：

```bat
.venv\Scripts\python -m pip install -r requirements.txt pytest
.venv\Scripts\python -m pytest -q
```

macOS / Linux：

```bash
.venv/bin/python -m pip install -r requirements.txt pytest
```

> 当前仓库已有 `.venv/`，但不要把它提交到版本库。换机器时重新创建。

### 2.3 启动实时指挥台

全 Mock、零 API 费用：

```bash
./.venv/Scripts/python live_server.py --days 365 --speed 2 --paused --open
```

浏览器打开 `http://127.0.0.1:8765/`。

常用参数：

| 参数 | 含义 |
| --- | --- |
| `--days N` | 本轮目标日；达到后自动暂停 |
| `--speed X` | 每现实秒推进 X 个游戏日 |
| `--paused` | 启动后暂停，适合先看界面 |
| `--open` | 启动后自动打开浏览器 |
| `--port N` | 换端口，默认 8765 |
| `--models FILE` | 逐国 Mock/LLM 配置 |
| `--api-key-file FILE` | 启动时读取一次密钥到进程环境变量 |
| `--max-calls N` | 付费调用次数硬上限 |
| `--max-cost-usd X` | 已知费用硬上限 |

接入真实模型（示例，不要把密钥写进仓库）：

```bash
./.venv/Scripts/python live_server.py --days 180 --speed 2 --open \
  --models config/models.deepseek.json \
  --api-key-file "/path/to/local-key-file" \
  --max-calls 2 --max-cost-usd 0.10
```

真实付费调用必须同时设置 `--max-calls` 和 `--max-cost-usd`。没有密钥或预算时，世界仍可全 Mock 运行。

### 2.4 命令行模拟

```bash
# 四国 Mock，快进 365 日
./.venv/Scripts/python run_simulation.py run --days 365

# 从存档继续
./.venv/Scripts/python run_simulation.py run --load runs/eos_365.json --days 365 \
  --save runs/eos_730.json

# 交互模式
./.venv/Scripts/python run_simulation.py interactive --load runs/eos_365.json

# 查看存档摘要
./.venv/Scripts/python run_simulation.py status --save runs/eos_365.json
```

输出：

- `--save`：完整动态存档。
- `--log`：JSONL 事件流。
- `--snapshots`：每 30 日及关键节点的国家摘要。
- `--api-usage`：本次 API 调用/Token/估算费用。

交互命令：`pause`、`resume`、`step [日]`、`ff 日`、`run 日`、`speed 每日秒数`、`status`、`save [路径]`、`quit`。

### 2.5 老地图生成管线（可选）

```bash
./.venv/Scripts/python worldgen.py --seed 2000 --output output_regenerated
./.venv/Scripts/python simulate_climate.py \
  --world output_regenerated/world_2000BCE.json \
  --out output_regenerated/first_year_weather.json --seed 2000 --days 365
./.venv/Scripts/python build_viewer.py
```

**重要：** `output/world_2000BCE.json` 是校验过的静态基线，不要覆盖。重新生成请写到 `output_regenerated/`。

### 2.6 开发时最小验证

```bash
./.venv/Scripts/python -m pytest -q
```

提交前建议再跑一轮 365 日 Mock：

```bash
./.venv/Scripts/python run_simulation.py run --days 365 \
  --save runs/_check_365.json --log runs/_check_365.jsonl \
  --snapshots runs/_check_365_snapshots.json
```

---

## 3. 架构总览

### 3.1 分层

```
浏览器 dashboard.html
        │  fetch /api/*
        ▼
live_server.py（LiveSession + ThreadingHTTPServer）
        │  锁定、线程、存档槽、快照
        ▼
core/simulation.py（游戏循环、暂停/倍速、JSONL）
        │
        ▼
core/rules.py — RuleEngine（唯一动态状态写入口）
        │
        ├── core/economy.py        粮食、财政、人口、科研、城市服务
        ├── core/construction.py   建设队列
        ├── core/diplomacy.py      关系、交易、协定、和平
        ├── core/military.py       军队、行军、战斗、占领
        └── core/city_governance.py AI 市长（只改 AI 托管城市）
        │
        ▼
core/state.py — GameState / CountryState / CityState / WorldStatic
        │
        ├── config/rules.json      全部可调参数
        └── output/world_*.json    静态地理世界
```

AI 旁路：

```
AgentScheduler ── deepcopy(observation) ──> HeuristicAgent / OpenAICompatibleAgent
       │                                              │
       └──────────── JSON decision ───────────────────┘
                              │
                     RuleEngine.apply_decision
```

前端永远不直接改状态；它只提交动作，然后重新拉取 `/api/state`。

### 3.2 一次日推进的完整顺序

`RuleEngine.step_day()` 的顺序是硬约束：

1. 过期外交/贸易提案。
2. 若到规划日（默认每 90 日）：国家 AI 规划 + 城市 AI 市长规划。
3. 采样并记录当日天气。
4. 各国每日经济结算（粮食、地方物流、城市预算、财政、饥荒）。
5. 军队维护/疲劳。
6. 建设推进。
7. 各国科研推进。
8. 若为月末：天气月度汇总、灾害、宜居度、人口增长、稳定度、军队月结算、社会事件。
9. `day_index += 1`。

最后（实时服务层）检查胜利条件，达成则暂停、记录 `victory` 事件并保存。

**新增系统时若要参与每日结算，应插入上述顺序并说明理由。** 不要绕过 `RuleEngine` 在 UI 或 Agent 中直接改状态。

### 3.3 一次动作的完整流程

玩家：

```
dashboard 提交 {actor, action}
  → LiveSession.player_action（校验是否接管该国）
  → RuleEngine.apply_action
  → validate_action（严格 JSON schema）
  → _execute（业务校验 + 状态变更）
  → ActionResult + action_log + event_log
  → /api/action 返回 {ok, result}
  → 前端 poll(true) 刷新
```

AI：

```
90 日规划点
  → AgentScheduler.build_observation（只含该国信息，deepcopy）
  → Agent.decide(observation)
  → apply_decision（校验 country_id、world_day、最多 4 个动作）
  → 逐个 apply_action
  → 失败动作记录拒绝原因，不会破坏已接受动作
```

---

## 4. 代码地图

| 文件 | 职责 | 主要改动者 |
| --- | --- | --- |
| `core/state.py` | 数据模型、世界加载/哈希、存档、日历、summary、胜利状态 | 核心/引擎 |
| `core/rules.py` | 唯一写入口、动作执行、日推进顺序、SETTLE | 核心/引擎 |
| `core/actions.py` | 动作白名单、JSON schema 校验、ActionResult | 核心/协议 |
| `core/economy.py` | 粮食、税收、矿业、维护、服务预算、人口、科研 | 经济/城市 |
| `core/society.py` | 城市指标、分区邻接、宜居度、评分、时代、胜利条件 | 城市/平衡 |
| `core/city_governance.py` | AI 市长：方针、分区、预算 | 城市/AI |
| `core/construction.py` | 建设队列与劳动力/政策进度 | 经济 |
| `core/diplomacy.py` | 关系、赠礼、贸易托管、协定、战争/和平 | 外交 |
| `core/military.py` | 招募、行军、战斗、占领、维护、疲劳 | 军事 |
| `core/weather.py` | 可复现天气 RNG、月统计、灾害基础 | 世界 |
| `core/simulation.py` | 运行/暂停/倍速、JSONL、自动存档 | 引擎 |
| `core/replay.py` | 从动作日志重建最终状态 | 引擎/QA |
| `agents/scheduler.py` | 90 日规划、隔离观察、并发决策、玩家国家跳过 | AI |
| `agents/heuristic.py` | 多国规则 AI 基线 | AI |
| `agents/llm_adapter.py` | OpenAI 兼容适配、预算、Token 记录、失败回退 | AI |
| `live_server.py` | 本地 HTTP、LiveSession、存档槽、API | 后端/UI |
| `dashboard.html` | 单页 UI：菜单、地图、弹窗、城市视图 | 前端 |
| `config/rules.json` | 所有数值与内容定义 | 平衡/策划 |
| `worldgen.py` | 原始世界生成、气候、水文、灾害、天气函数 | 地图 |
| `mapgen.py` | 公平随机世界、自定义 2–12 国 | 地图 |
| `run_simulation.py` | 批处理/交互 CLI | 工具 |
| `build_viewer.py` / `simulate_climate.py` / `plot_elevation.py` | 离线地图/天气/海拔工具 | 地图 |
| `tests/` | 规则、经济、AI、回放、地图、LLM 测试 | 所有人 |
| `assets/` | 设施与建筑图标 | 美术/前端 |

当前规模约 9,000 行 Python/HTML；`dashboard.html` 约 1,850 行，是最大的单文件。

---

## 5. 核心数据模型与不变量

### 5.1 `WorldStatic`

- 只读地理世界：72×54 六边形、气候、河流、灾害、初始国家。
- 加载时计算文件 SHA-256；存档记录该哈希，加载时不一致会拒绝。
- 坐标使用 `(col, row)`；邻居与距离函数来自 `worldgen.neighbors` / `hex_distance`。
- 世界 JSON 里的 `owner_id` 是基线示意；**运行时领土以 `CountryState.tiles` 为准**。

### 5.2 `GameState`

主要字段：

```text
world, config, seed
start_astronomical_year, start_era_index
day_index
countries: dict[str, CountryState]
trades, relations, pacts, diplomatic_proposals
weather: WeatherModel
action_log, event_log
next_action_number, next_project_number, next_trade_number, next_diplomacy_number
```

- `summary()` 生成前端快照，不是存档本身。
- `fingerprint()` 对动态状态做稳定哈希，用于回放校验。
- `victory_status()` 计算各国胜利条件与最终赢家。

### 5.3 `CountryState`

关键字段：人口、粮食、财政、领土、科技、税率、劳动力、政策、建筑、在建项目、外交、军队、城市列表、稳定度、缺粮统计。

国家人口与城市人口必须满足：

```text
country.population == sum(city.population for city in country.cities)
```

破坏后立即调用 `state.sync_city_population(country)`，或按城市权重分配变化。

### 5.4 `CityState`

```text
city_id, name, center, population, focus, tiles, founded_day
zones: dict[(col,row), zone]
managed_by: "ai" | "manual"
livability
food_output / food_need / food_balance / food_loss
budget, local_revenue, local_upkeep, local_net
```

- `city_id` 创建后保持稳定（如 `ELAR-C1`、`ELAR-C2`）。
- `zones` 必须覆盖全部城域地块；旧存档加载时会用 `default_zone` 补全。
- 城市中心不能被军事占领；城域其它地块可以被占领并转移。
- 城域扩张默认 5 格（`config.expansion.city_tiles`），新增城市继承来源城市的 `managed_by`。

### 5.5 核心不变量

1. **静态世界不可变。** 不要修改 `WorldStatic.data/tiles`；不要无意覆盖 `output/world_2000BCE.json`。
2. **规则引擎是唯一动态写入口。** AI/UI 只提交动作；城市 AI 市长也通过 `engine.apply_action`。
3. **动作原子性。** 校验失败应抛 `ActionRejected`，不能留下半完成状态；涉及资源扣除时先校验后扣款。
4. **人口守恒。** 全国人口等于城市人口之和。
5. **确定性。** 相同种子 + 相同动作日志 + 相同规则，必须得到相同 `fingerprint()`。
6. **观察隔离。** Agent 拿到的是深拷贝；它不能借观察对象修改活状态。
7. **玩家国家跳过 AI。** `scheduler.controlled_by_player` 中的国家不参与自动规划。
8. **手动城市不被 AI 覆盖。** `CityManager` 只处理 `managed_by == "ai"` 的城市。
9. **所有需要复盘的动态变化都要进入动作日志或事件日志。**
10. **前端不持有权威状态。** 每次操作后重新拉取 `/api/state`。

---

## 6. 规则引擎与动作协议

### 6.1 动作集合

公共动作（`core/actions.py`）：

| 动作 | 关键字段 | 说明 |
| --- | --- | --- |
| `BUILD` | `tile:{col,row}`, `building` | 在己方地块开始建造 |
| `ALLOCATE_WORKERS` | `agriculture`, `mining`, `construction` | 三项和为 1 |
| `SET_TAX` | `rate` | 0 到 `maximum_tax_rate` |
| `SET_RESEARCH` | `field` | 三条科技线之一 |
| `SET_POLICY` | `priority` | 六种国家政策 |
| `SETTLE` | `tile:{col,row}` | 相邻无主陆地开拓，建立约 5 格新城 |
| `TRADE` | `operation`, `target`, `offer_food`, `request_treasury` 或 `proposal_id` | `PROPOSE/ACCEPT/REJECT` |
| `DIPLOMACY` | `operation`, ... | `GIFT/PROPOSE_PACT/ACCEPT_PACT/REJECT_PACT/DECLARE_WAR/PROPOSE_PEACE` |
| `MILITARY` | `operation`, ... | `RECRUIT/MARCH/ATTACK` |
| `SET_CITY_FOCUS` | `city_id`, `focus` | 城市方针 |
| `SET_CITY_ZONE` | `city_id`, `tile`, `zone` | 城市地块分区 |
| `SET_CITY_GOVERNANCE` | `city_id`, `managed_by` | `ai/manual` |
| `SET_CITY_BUDGET` | `city_id`, `budget` | `austerity/balanced/investment` |
| `NO_OP` | 无 | 内部空操作，LLM 失败回退也用 |

约束：

- 单次 AI 决议最多 `max_actions_per_decision`（默认 4）个动作。
- LLM 决议必须原样带回 `country_id` 与 `world_day`，否则整份决议被拒绝。
- 动作字段是严格白名单，出现未知字段直接 `INVALID_SCHEMA`。
- 数值必须是有限数，布尔值不算数字。
- 所有拒绝都返回 `ActionResult(reason_code, reason_text)`，不会让服务崩溃。

### 6.2 示例

```json
{"type":"SET_TAX","rate":0.12}
{"type":"BUILD","tile":{"col":13,"row":10},"building":"FARM"}
{"type":"SET_CITY_ZONE","city_id":"ELAR-C1","tile":{"col":14,"row":10},"zone":"farm"}
{"type":"SET_CITY_BUDGET","city_id":"ELAR-C1","budget":"investment"}
{"type":"TRADE","operation":"PROPOSE","target":"MARIS","offer_food":20,"request_treasury":3}
{"type":"MILITARY","operation":"RECRUIT","strength":2}
```

### 6.3 新增一个动作的检查清单

1. `core/actions.py`：加入 `PUBLIC_ACTIONS`。
2. `validate_action` 顶层 `_keys(...)` 加入新字段名。
3. 增加动作分支，返回规范化后的 dict。
4. `core/rules.py::_execute` 增加业务处理，失败用 `ActionRejected("CODE", "中文原因")`。
5. 需要资源变化时先校验、后扣除；写 `state.record(...)`。
6. `agents/llm_adapter.py` 的 system prompt 加入动作说明。
7. 在 `tests/test_actions.py` 增加成功、非法参数、越权/外部对象、原子性测试。
8. 如前端需要入口，在 `dashboard.html` 增加 UI，并只通过 `/api/action` 提交。
9. 跑完整测试 + 365 日 Mock，确认 AI 不会滥用。

---

## 7. 模拟子系统

### 7.1 日历与天气

- 365 天无闰年；天文纪年无 0 年；显示为“公元前/公元”。
- 开局年份支持 **BC 800 – AD 500**，决定起始时代与三条科技线基线。
- 天气由 `WeatherModel` 基于月气候态 + 随机异常生成；RNG 状态写入存档。
- 月末生成降雨/温度异常，驱动洪水/干旱灾害，灾害会实际扣粮。
- 气象是游戏模型，不是科学天气预报/GCM。

### 7.2 国家经济

每日：

```text
粮食产出 = 地块基础产出 × 天气 × 道路 × 城市方针 × 分区 × 邻接 × 宜居
           × 劳动力 × 农业科技 × 政策 × 税收压力 × 稳定度 × 粮仓类建筑
矿业收入 = 地块矿业基础 × 道路 × 方针 × 分区 × 邻接 × 宜居
           × 劳动力 × 冶金科技 × 政策 × 税收 × 稳定度 × 工坊类建筑 × 矿山边际效率
税收     = 人口 × 税率 / divisor × 政策 × 市场 × 贸易协定 × 城市方针/分区
净收入   = 税收 + 矿业 - 建筑维护 - 城市公共服务支出
```

- 粮食有仓容上限，溢出浪费。
- 缺粮会按缺口比例造成人口损失；损失优先落到缺粮城市。
- 稳定度受税率、粮食安全、住房拥挤、城市化、公共建筑、政策影响，并反向影响产出。

### 7.3 城市粮食物流

- 每城单独计算 `food_output`、`food_need`、`food_balance`。
- 盈余上缴全国储备、缺口从全国储备调入，双向产生物流损耗。
- 道路降低损耗率（有上限）。
- 依赖调入粮食的城市，人口增长乘 `import_growth_penalty`（默认 0.85）。
- 全国饥荒时，优先扣减粮食缺口城市的人口。

关键配置：`city_logistics`。

### 7.4 城市地方预算

- 城市税收与矿业收入按人口、方针、分区邻接、地块矿业权重拆分。
- 建筑维护和公共服务支出计入城市本地账本。
- 公共服务支出真实计入全国财政净收入，不是免费加成。
- 三档预算：

| 预算 | 服务支出 | 宜居目标 | 增长 |
| --- | --- | --- | --- |
| `austerity` 紧缩 | ×0.6 | -6 | ×0.92 |
| `balanced` 均衡 | ×1.0 | 0 | ×1.0 |
| `investment` 投资 | ×1.5 | +6 | ×1.08 |

关键配置：`city_service_cost_per_1000`、`city_budgets`。

### 7.5 人口、住房、宜居度

- 住房容量来自城域格数、道路、建筑、住宅分区。
- 人口按月增长，受住房余量、宜居度、粮食进口依赖影响。
- 宜居度目标由住宅/商贸/学术、工矿污染、神庙/市场/粮仓、预算、拥挤共同决定。
- 宜居度影响城市产出倍率、人口增长和全国稳定度。
- 分区邻接：农业连片、工矿聚集、商贸靠中心、学术靠住宅。

关键配置：`housing`、`city_zones`、`stability`。

### 7.6 科技与时代

- 三条科技线：`agriculture`、`bronze_metallurgy`、`writing`，各 6 级。
- 研究点数来自人口/城市方针/分区/书库/政策/稳定度。
- 研究升级到下一级需要 `research_base_threshold × 当前等级`。
- 时代由 `min(三条科技线)` 与开局时代共同决定；不会因开局年代倒退。
- 开局年代会先给三条线基线等级，晚期开局不会直接触发知识胜利（知识胜利要求三线满级 6）。

关键配置：`tech_tree`、`eras`、`research_*`。

### 7.7 建设

- 建筑有造价、工期、地形限制、科技前置、全国上限。
- 建设进度受 construction 劳动力与政策影响。
- 完成后进入 `country.buildings`，实际参与经济/住房/稳定度结算。
- 奇观全国唯一，是后期财政出口。

关键配置：`buildings`、`building_upkeep_per_day`、`workers_baseline`。

### 7.8 外交

- 各国两两关系 -100..+100。
- 赠礼提升关系；贸易成交提升关系；拒绝降低关系。
- 关系达到门槛才能提议贸易协定；协定需对方接受，待回应提案会过期。
- 有效贸易协定给双方税收 +5%。
- 战争会取消双方有效协定并把关系降到 -100。
- 和平通过提案与接受完成。

关键配置：`trade_expiry_days`、`military`、政策参数。

### 7.9 军事

- 国家只有一支战略军队：规模、位置、维护费、战争疲劳。
- 招募消耗财政与粮食，受最大规模限制。
- 行军只能走己方或中立陆地，单次最多 `march_range` 格。
- 进攻要求已宣战，且边境接壤或存在陆上远征路线；远征有惩罚。
- 战斗按兵力、冶金科技、稳定度、少量随机因素结算。
- 胜利可占领一块非城市中心的敌方领土，并转移到胜方最近城市。
- 占领会清理败方城市分区、项目中的该地块，避免存档不一致。
- 战争疲劳抑制长期战争，AI 疲劳过高会求和。

### 7.10 评分与胜利

综合评分四条路线：

- 繁荣：人口、存粮、市场、工坊
- 知识：科技总等级、书库、大书库
- 疆域：领土、前哨、奇观
- 安定：稳定度、住房余量、神庙

正式胜利条件（`config.victory_conditions`）：

| 路线 | 条件 |
| --- | --- |
| 知识 | 三条科技线全部达到 6 级 |
| 繁荣 | 人口 45k、财政 600、存粮达到仓容 80% |
| 疆域 | 至少 26 格，且达到对手平均领土 1.5 倍；至少 3 城 |
| 安定 | 稳定 80、城市平均宜居 62、人口 30k |

- 实时服务每天检查；达成后记录 `victory` 事件、暂停并进入结算。
- 继续本局后不会重复公告同一场胜利。
- 未达成正式胜利时，结算按综合评分显示临时领先。

---

## 8. 城市系统专章

城市是本项目相对普通国家模拟器的核心差异，改动时要特别小心。

### 8.1 城市实体

- 每国初始一座都城；`SETTLE` 建立新城（默认 5 格连通城域，受地形限制）。
- 新城从来源城市迁入人口，默认分区由 `default_zone` 生成。
- 新城继承来源城市的托管状态；AI 国家的新城默认 AI 托管。
- 城市人口独立，但全国人口始终等于城市人口之和。

### 8.2 城市方针

`balanced/growth/industry/commerce/scholar`，影响粮食、矿业、税收、研究乘数。配置在 `city_focuses`。

### 8.3 分区与邻接

`unzoned/residential/farm/industry/commerce/scholar`，配置在 `city_zones`。

邻接规则在 `core/society.py::zone_adjacency`：

- 农业：相邻农业 +食物
- 工矿：相邻工矿 +矿业
- 商贸：靠近中心、相邻商贸 +税收
- 学术：相邻住宅 +研究

城市局部地图上的金色小点表示该地块当前享有邻接加成。

### 8.4 宜居度

`city_livability_target` 计算目标值，月度向目标靠拢。影响：

- 地块产出倍率
- 人口增长
- 全国稳定度

### 8.5 粮食账本

城市详情显示：本地产出、需求、余缺、调配损耗、自给率。相关字段：

```text
food_output, food_need, food_balance, food_loss
```

AI 市长在自给率低于 95% 时转“人口与农业”方针并扩建农业区。

### 8.6 地方预算

城市详情显示本地收入、服务与维护、结余，并提供三档预算按钮。

- 观察模式只读。
- AI 托管城市由市长自动选择，玩家不能直接改。
- 手动城市才能由玩家调整。
- 预算变化真实影响全国财政、宜居和增长。

### 8.7 AI 市长

`core/city_governance.py`：

- 只处理 `managed_by == "ai"`。
- 每 90 日规划一次：方针、预算、目标分区。
- 粮食自给低 → 农业优先。
- 国库紧张且本地亏损 → 紧缩。
- 宜居低或治安/卫生偏低且国库允许 → 投资。
- 卫生紧张 → 优先把工矿地块转为住宅。
- 手动城市完全跳过，不覆盖玩家操作。

### 8.8 城市服务

每座城市维护独立 `security`（治安）和 `health`（卫生），目标值由 `city_service_targets` 计算：

- 治安：神庙、市场、道路提升；工矿分区和住房拥挤压低。
- 卫生：粮仓、灌溉、神庙、市场提升；工矿污染、住房拥挤、缺粮压低。
- 预算档位也会直接修正治安/卫生目标。

阈值与后果：

- `< 45`：紧张；`< 35`：危机。
- 低治安降低税收和人口增长；低卫生降低人口增长。
- 每月危机检查：治安事件损失财政与稳定度；疫病损失人口与稳定度。
- 服务值、目标值和状态显示在城市卡片与城市详情。

字段：`security`、`health`；目标与状态由 `city_static_metrics` 派生为
`security_target`、`health_target`、`security_status`、`health_status`。

### 8.9 新增城市功能的检查清单

1. `CityState` 加字段。
2. `to_dict/from_dict` 加持久化与默认值（旧存档兼容）。
3. `city_static_metrics` 加到前端字段。
4. 若参与结算，更新 `core/economy.py` 对应位置。
5. 若影响 AI，更新 `core/city_governance.py`。
6. UI 城市卡片/详情增加显示或操作。
7. 增加测试：真实结算、存档往返、回放指纹、手动/AI 边界。

---

## 9. AI 系统

### 9.1 规划节奏

- 默认每 90 日一次，由 `RuleEngine.step_day` 在规划日调用。
- `AgentScheduler.build_observation(state, country_id)` 只提供该国可见信息。
- 每个国家的观察是深拷贝；Agent 不能通过观察对象修改活状态。
- 各国决策通过 `asyncio.gather` 并发执行。
- 玩家接管的国家不参与自动规划。
- 单个 Agent 异常会回退为 `NO_OP`，不会中断世界。

### 9.2 规则 AI

`agents/heuristic.py`：

- 各国各有政策/研究/建筑偏好。
- 会接受贸易、评估公平性、赠礼、提议/接受协定。
- 会扩张、建设、研究最低科技线以推进时代、建军和开战/求和。
- 是零成本、确定性的基线，也是 LLM 失败时的安全网。

### 9.3 LLM 适配层

`agents/llm_adapter.py`：

- 只支持 OpenAI 兼容的 `/chat/completions` 协议。
- 每家可单独配置 provider、model、base_url、超时、重试、输出上限、输入/输出单价。
- 密钥只从环境变量读取；配置里只写环境变量名。
- 默认要求同时设置调用次数和费用上限，否则拒绝付费调用。
- 记录 `llm_call` / `llm_decision` 事件；Usage 缺失记为 unknown，不当作 0 费用。
- 非法 JSON、超时、429/5xx 会按配置重试；最终失败回退 `NO_OP`。
- 提示词要求只输出 JSON，动作最多 4 个，并额外输出 `diary`：`title`、`mood`、第一人称 `text`。
- `text` 写公开决策叙事（局势、动机、取舍、下一步），不要求模型暴露逐步推理链。

模型配置示例见 `config/models.example.json`。真实配置复制为本地文件（如 `config/models.local.json`），不要提交密钥。

### 9.4 运行时切换

**简单模式**：只提交厂商预设和 API Key，服务端解析官方默认值：

```json
{
  "country_id": "ELAR",
  "settings": {
    "mode": "openai_compatible",
    "provider_id": "qwen",
    "api_key": "玩家粘贴的本地密钥"
  }
}
```

服务端把 Key 写入该进程的环境变量 `EOS_AGENT_<COUNTRY>_API_KEY`，不会写回响应、存档、日志或页面。重启服务后内存密钥清空。

当前预设（`config/llm_providers.json`）：

| ID | 厂商 | OpenAI 兼容 Base URL | 默认模型 |
| --- | --- | --- | --- |
| `deepseek` | DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| `doubao` | 字节豆包 / 火山方舟 | `https://ark.cn-beijing.volces.com/api/v3` | `doubao-seed-2-1-pro-260915` |
| `qwen` | 阿里千问 / 百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| `kimi` | 月之暗面 Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-auto` |
| `glm` | 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-5.3` |
| `minimax` | MiniMax | `https://api.minimax.cn/v1` | `MiniMax-M3` |

厂商切换但 Key 留空时，服务端拒绝，避免把旧厂商的 Key 发给新厂商。预设模型以各厂商账号实际开通情况为准，可用高级模式覆盖。

**高级模式**：完整自定义：

```json
{
  "country_id": "ELAR",
  "settings": {
    "mode": "openai_compatible",
    "provider": "custom-gateway",
    "model": "custom-model",
    "base_url": "https://gateway.example.com/v1",
    "api_key_env": "EOS_AGENT_ELAR_API_KEY",
    "timeout_seconds": 45,
    "retries": 0,
    "max_output_tokens": 4000
  }
}
```

`GET /api/agents` 同时返回安全的 `providers` 预设列表；页面只显示“是否已配置”，不会返回密钥。Mock 席位不会因为存在全局 `EOS_API_KEY` 而误显示为已配置。

### 9.5 LLM 统治日记

每次 LLM 规划成功后，`AgentScheduler` 把决策叙事记录为 `llm_diary` 事件：

```json
{
  "type": "llm_diary",
  "country_id": "ELAR",
  "day": 180,
  "date": "公元前1999年7月1日",
  "title": "粮食与边境",
  "mood": "谨慎",
  "text": "今年的收成足够……我决定先把税率维持……",
  "actions": [ { "type": "SET_TAX", "rate": 0.12 } ],
  "provider": "deepseek",
  "model": "deepseek-flash",
  "synthetic": false
}
```

- 只对 `OpenAICompatibleAgent` 记录；HeuristicAgent 没有日记。
- 模型没有返回 `diary` 时，用 `reason` 合成并标记 `synthetic: true`。
- 日记是观察/审计元数据，不进入 `fingerprint()`；回放不要求重建模型输出。
- 地图表现：决策首先在首都上方弹出思考气泡；同时最多 2 个，其余排队，同国新决策替换旧气泡。
- 气泡状态机：`highlight` 2.2s → `steady` 5.2s → `fade` 0.9s → 归档；鼠标移入立即转常亮，移出 1.2s 后淡出；淡出中触碰会恢复常亮。
- 单击气泡展开完整正文、动作标签和模型信息；关闭后气泡移除，但日记仍保留在事件日志。
- 顶部“AI 日记”打开“AI 统治档案”，可回看全部已淡出/关闭的日记；载入存档只归档历史，不补弹旧气泡。
- `GET /api/diary?country=ELAR&limit=80` 返回日记、各国控制器和模型信息。
- 载入存档会保留当前 LLM 席位，不会把已配置模型重置为 Mock。

---

## 10. 存档、回放与确定性

### 10.1 存档格式

动态存档格式：

```json
{
  "format": "project-eos-dynamic-save",
  "format_version": 1,
  "rules_version": "...",
  "world_file": "output/world_2000BCE.json",
  "world_sha256": "...",
  "seed": 2000,
  "day_index": 0,
  "start_astronomical_year": -1999,
  "start_era_index": 1,
  "rules": { ... },
  "countries": { ... },
  "trades": { ... },
  "relations": { ... },
  "pacts": { ... },
  "diplomatic_proposals": { ... },
  "weather": { "rng_state": ..., "anomaly": ..., "month_accumulators": ... },
  "counters": { ... },
  "action_log": [ ... ],
  "event_log": [ ... ]
}
```

存档槽：

- `runs/saves/<id>.json`：状态。
- `runs/saves/<id>.meta.json`：名称、日期、种子、开局年、时代、国家名、玩家国、保存时间。
- 每 30 游戏日自动保存，返回菜单和关闭服务也会保存。
- 载入存档后默认暂停，目标日重置为当前日 +365。
- 载入存档会保留当前 LLM 席位和模型配置；不会静默降级为 Mock。

### 10.2 回放

`core/replay.py`：

1. 读取最终存档与动作日志。
2. 从同一静态世界和种子新建状态。
3. 恢复自定义开局年代。
4. 按 `applied_day` 重放动作。
5. 每日推进，**禁用 CityManager**，因为市长的动作已经记录在动作日志中。
6. 对比 `fingerprint()`。

### 10.3 确定性红线

以下行为会破坏回放/测试：

- 使用未写入存档的随机数。
- 在 `CityManager` 或 UI 中直接修改城市状态，而不经过动作日志。
- 把派生字段写进指纹，但这些字段在回放时无法重现。
- 修改世界静态文件但沿用旧哈希。
- 在 config 合并时重命名已有键却没有迁移。

新增状态时问自己：**回放时能否从动作日志 + 种子 + 规则重新得到它？**

### 10.4 存档兼容

- `GameState.load` 会用默认 `rules.json` 合并旧存档的规则，新增配置键自动补默认值。
- `CityState.from_dict` / `CountryState.from_dict` 对新字段使用默认值。
- 破坏性格式变更必须提升 `format_version` 并写迁移或明确拒绝旧档。
- 不要静默删除旧字段。

---

## 11. HTTP API

服务只绑定 `127.0.0.1/localhost`，没有认证，禁止绑定公网。

### 11.1 GET

| 路径 | 作用 |
| --- | --- |
| `/` | 返回 `dashboard.html` |
| `/api/world` | 静态世界压缩载荷（metadata/polities/tiles） |
| `/api/state` | 实时完整快照：日期、国家、城市、事件、建筑、项目、AI、预算、胜利 |
| `/api/agents` | 各国控制器、模型、预算、厂商预设（不含密钥） |
| `/api/diary` | LLM 国家统治日记；`country`、`limit` 可选 |
| `/api/setup` | 新建世界的默认国家、文明类型、核心格数 |
| `/api/saves` | 存档列表与当前存档 ID |
| `/assets/*` | 图标/图片静态资源 |

### 11.2 POST

#### `/api/control`

```json
{"action":"pause"}
{"action":"resume"}
{"action":"step"}
{"action":"speed","value":4}
{"action":"take_control","value":"ELAR"}
{"action":"observe"}
{"action":"extend_round"}
{"action":"reset"}
```

用途：暂停/继续/单步/倍速、接管国家、回到观战、延长本轮、重置。

#### `/api/action`

```json
{
  "actor": "ELAR",
  "action": {"type":"SET_TAX","rate":0.12}
}
```

返回：

```json
{"ok": true, "result": {"action_id":"A00000001","accepted":true,...}}
```

只有在已接管该国时才能提交；只能提交给自己接管的国家。

#### `/api/agents`

见 9.4。

#### `/api/new_game`

```json
{
  "countries": [
    {"name":"赤河国","color":"#cc5544","archetype":"river_valley","population":30000},
    {"name":"蓝港国","color":"#4488cc","archetype":"maritime","population":24000},
    {"name":"云山国","color":"#88aa66","archetype":"highland","population":18000},
    {"name":"沙丘国","color":"#ccaa55","archetype":"semiarid","population":26000}
  ],
  "seed": "",
  "start_year": -799,
  "save_name": "我的世界"
}
```

`countries` 可省略，系统自动填默认四国；支持 2–12 个，名称 1–24 字符、颜色唯一 `#RRGGBB`、人口 8000–60000。

#### `/api/saves`

```json
{"operation":"save","name":"手动存档"}
{"operation":"load","id":"save_..."}
{"operation":"delete","id":"save_..."}
```

### 11.3 本地安全边界

- 服务没有登录，默认只监听 loopback；`main()` 会拒绝非 `127.0.0.1/localhost` 的 host。
- 静态资源做了路径逃逸检查。
- 页面会显示模型是否配置，但永远不会返回密钥。
- 若要局域网共享，请使用系统级远程访问/反向代理并自行加认证，不要直接改 host 暴露公网。

---

## 12. 前端 dashboard.html

### 12.1 结构

单文件 HTML + CSS + 原生 JS，无构建步骤。

主要界面：

- 主菜单：继续、载入、新建世界、AI 席位。
- 游戏壳：顶部资源条、左侧国家/建设队列、中间六边形地图、右侧国家/地块/动态/排名标签。
- 弹窗：科技树、外交、军事、城市、AI 统治档案、AI 席位、新世界、Esc 暂停、结算。
- AI 席位默认显示简单配置（厂商 + API Key），高级配置折叠在下方。
- LLM 决策还会以地图思考气泡出现：首都锚定、最多 2 个、高亮/常亮/淡出、悬停救回、点击展开、关闭归档。
- 城市详情：局部六边形地图、粮食账本、地方预算、分区编辑。

### 12.2 状态流

- `STATE` 保存 `/api/state` 快照，`WORLD` 保存 `/api/world`。
- `poll(force)` 每 500ms 拉取一次；`renderIfChanged()` 用关键字段避免重复重绘。
- 所有玩家操作调用 `submitPlayerAction()` → `/api/action` → 再 `poll(true)`。
- `showOnlyScreen(name)` 切换主菜单/载入/新世界/游戏壳。
- URL 参数便于调试：`?play=latest`、`?tech=1`、`?diplo=1`、`?mil=1`、`?city=1`、`?citymap=1`、`?layer=political`。

### 12.3 地图

- Canvas 绘制六边形，支持拖动、缩放、选中地块。
- 图层：卫星、政治、海拔、降水、资源、交通。
- 国家颜色来自世界 polities；城市、设施图标、道路、施工进度环叠加。
- 设施图标通过 `BUILD_ICON` 映射到 `/assets/icons/*.png`。

### 12.4 城市视图

- 城市卡片：人口、住房、预算、粮食自给、余缺、宜居度。
- 点击进入局部地图，点击地块查看分区/邻接，手动城市可改分区。
- 右侧粮食账本、地方预算、AI 市长说明。
- AI 托管城市只读；玩家需先“收回手动治理”。

### 12.5 前端改动规范

1. 不要在前端计算权威资源；只显示服务端字段。
2. 提交动作必须走 `submitPlayerAction`，不要直接改 `STATE`。
3. 新字段先加进 `summary()`/`city_static_metrics()`，再在 UI 读取。
4. 文本使用中文，保持现有视觉密度；图标沿用 `assets/icons`。
5. 大改后至少做一次浏览器冒烟：主菜单 → 进游戏 → 各弹窗 → 城市视图 → Esc → 回菜单。

---

## 13. 配置系统

`config/rules.json` 是主要平衡入口。修改后重启服务；旧存档会合并新默认配置。

主要分区：

| 键 | 作用 |
| --- | --- |
| `rules_version` | 规则版本标识 |
| `planning_interval_days` | AI 规划间隔 |
| `max_actions_per_decision` | 单次 AI 动作上限 |
| `expansion` | 前哨上限、费用、人口门槛、新城格数 |
| `food_per_1000_people_per_day` | 人均粮食消耗 |
| `biome_food_yield` | 各生态粮食潜力 |
| `base_food_per_tile` / `farm_food_bonus` | 农业产出 |
| `base_mine_per_tile` / `mine_*` | 矿业产出与边际递减 |
| `road_production_bonus` | 道路产出加成 |
| `treasury_population_tax_divisor` | 人口税基 |
| `high_tax_*` | 高税惩罚 |
| `monthly_population_growth_rate` | 月人口增长 |
| `food_storage` | 仓容 |
| `housing` | 住房 |
| `stability` | 稳定度 |
| `social_events` | 月度社会事件 |
| `weather` | 天气/灾害 |
| `buildings` | 建筑定义 |
| `city_zones` | 分区 |
| `city_focuses` | 方针 |
| `city_logistics` | 城市粮食物流 |
| `city_service_cost_per_1000` | 城市服务基础成本 |
| `city_budgets` | 城市预算档位 |
| `city_services` | 治安/卫生目标、阈值、事件概率与损失 |
| `victory_conditions` | 胜利条件 |
| `tech_tree` / `eras` / `research_*` | 科技与时代 |
| `policies` | 国家政策 |
| `military` | 军事 |
| `trade_expiry_days` | 提案过期 |
| `workers_baseline` | 劳动力基准 |

### 13.1 新增建筑

1. `config/rules.json` 的 `buildings` 加定义（造价、工期、地形、科技前置、上限、维护）。
2. `core/economy.py` / `core/society.py` 加实际效果。
3. `dashboard.html` 的 `BUILD_NAMES`、`BUILD_ICON` 加显示。
4. `assets/icons/` 放入图标，或先用文字占位。
5. 增加测试：建造、前置、上限、完成后的真实效果。

### 13.2 新增分区

1. `city_zones` 加定义（food/mining/housing/tax_bonus/research_bonus/color）。
2. `zone_adjacency` 加邻接规则。
3. `default_zone` 决定自动生成。
4. UI 分区调色板自动读取配置。
5. 测试邻接/宜居/产出。

### 13.3 新增科技/时代

1. `tech_tree`、`research_fields`、`eras` 同步调整。
2. 所有读取科技效果的代码（经济、军事、UI）加新线。
3. 开局时代基线、知识胜利条件、LLM 观察字段检查。
4. 回放测试与晚期开局测试。

### 13.4 新增胜利路线

1. `victory_conditions` 加阈值。
2. `core/society.py::victory_progress` 加进度与详情。
3. `dashboard.html` 的侧栏自动遍历 conditions，通常无需改结构。
4. 测试进度、达成、赢家选择。

---

## 14. 地图与美术

### 14.1 静态基线

- `output/world_2000BCE.json`：3,888 格（72×54），2,703 陆地，1,185 海洋，289 河流格。
- 世界哈希被存档引用；文件字节变化会导致旧存档拒绝加载。
- 重新生成写到 `output_regenerated/`。

### 14.2 地图生成

- `worldgen.py`：海拔/气候/水文/灾害/初始国家/天气函数。
- `mapgen.py`：公平随机地图与自定义 2–12 国；各国核心各 16 格连通；搜索公平度达标种子；保存到 `runs/worlds/`。
- 新建世界使用 A/B/C/D… 的通用 ID；固定基线仍使用 ELAR/MARIS/VAYR/SAHAR；颜色、公平度、AI 偏好和 UI 均按国家列表动态生成。
- 新世界通过 UI（可增减国家）或 `POST /api/new_game` 创建。

### 14.3 图标

- 图标在 `assets/icons/*.png`，来源是本地 GPT Image Studio 的写实低质量图。
- 原始拼图在 `assets/raw/`。
- 前端按 `BUILD_ICON` 映射；新增建筑需要新增同名 PNG。
- 当前背景为深蓝灰摄影棚底，通过圆角遮罩融入；替换透明图不需要改逻辑。

---

## 15. 测试与验收

### 15.1 测试矩阵

| 文件 | 覆盖 |
| --- | --- |
| `test_generated_world.py` | 世界完整性、气候、连通性、天气样本 |
| `test_mapgen.py` | 自定义国家、16 格连通核心、公平度元数据 |
| `test_actions.py` | 建造、科研、政策、交易、外交、军事、城市、预算、动作原子性 |
| `test_simulation.py` | 日历、暂停/倍速、存档、世界哈希、经济、评分、胜利、灾害 |
| `test_agents_replay.py` | 观察隔离、AI 贸易、研究、玩家跳过、365 日、回放、断点续跑 |
| `test_llm_adapter.py` | OpenAI 兼容协议、重试、预算、Usage、混用、失败回退 |

当前：**72 passed**。

### 15.2 测试原则

- 新机制必须测试“真实结算”，不能只断言事件出现。
- 资源扣除/转移要测非法输入和失败原子性。
- 城市改动要测人口守恒、存档往返、回放指纹。
- AI 改动要测观察隔离、玩家国家跳过、失败回退。
- 平衡改动跑 365 日；结构性改动跑 1,825 日。

### 15.3 验收清单

提交前逐项确认：

- [ ] `pytest -q` 全绿。
- [ ] 365 日 Mock 无崩溃、无异常饥荒/财政失控。
- [ ] 新动作有 schema、执行、拒绝原因、测试。
- [ ] 新字段进存档并能旧档兼容。
- [ ] 回放指纹一致。
- [ ] UI 实际打开验证，不只看接口。
- [ ] 控制台无 JS 错误、无 404。
- [ ] 没有提交密钥、`.venv`、`runs/`、临时截图。
- [ ] 平衡改动记录实测数据。

---

## 16. 团队协作规范

### 16.1 当前版本控制状态

项目已初始化 Git，并推送到：

```text
https://github.com/xd666-afk/PROJECT-EOS
默认分支：main
```

同事首次获取：

```bash
git clone https://github.com/xd666-afk/PROJECT-EOS.git
cd PROJECT-EOS
python -m venv .venv
./.venv/Scripts/python -m pip install -r requirements.txt pytest
./.venv/Scripts/python -m pytest -q
```

日常提交：

```bash
git switch -c feat/<topic>
# 修改、测试
git add <具体文件>
git commit -m "feat(scope): ..."
git push -u origin feat/<topic>
```

**基线文件：** `.gitignore` 使用 `output/*` 排除生成物，但显式保留 `output/world_2000BCE.json`、`world_summary.json`、`first_year_weather.json`、`sha256_manifest.json`、`viewer.html`。不要用 `git add -f` 绕过规则，也不要把整个 `output/` 重新加回来。

**换行保护：** `.gitattributes` 已固定 `output/world_2000BCE.json -text`，避免 Git 转换换行后导致世界 SHA-256 校验失败；图片按二进制处理。

不要提交：

- `.venv/`
- `runs/`（存档、实验输出、截图）
- `output_regenerated/`
- `.idea/`、`Thumbs.db`
- 任何 API 密钥文件（本机 `api.txt` 在仓库目录之外）
- `__pycache__/`、`.pytest_cache/`

### 16.2 分支与提交

建议：

- `main`：始终可运行、测试全绿。
- `feat/<module>-<topic>`：功能分支。
- `fix/<topic>`：修复分支。
- 每个 PR 只做一件事；动作协议、存档格式、配置键的改动要单独说明。

提交信息示例：

```text
feat(city): add local service budget tiers
fix(replay): exclude UI-only city note from fingerprint
balance(economy): lower city service cost to 0.0015
docs(manual): document action protocol and save format
```

### 16.3 建议分工

| 角色 | 主要文件 | 备注 |
| --- | --- | --- |
| 引擎/规则 | `core/state.py`, `core/rules.py`, `core/actions.py`, `core/simulation.py` | 动作协议与确定性优先 |
| 经济/城市 | `core/economy.py`, `core/society.py`, `core/city_governance.py` | 强耦合，改动需同步测试 |
| AI | `agents/*` | 观察隔离、预算、失败回退 |
| 后端/API | `live_server.py`, `core/replay.py` | 本地安全边界、存档槽 |
| 前端 | `dashboard.html` | 单文件，改动前先沟通，避免冲突 |
| 地图/美术 | `worldgen.py`, `mapgen.py`, `assets/` | 不覆盖基线世界 |
| QA/平衡 | `tests/`, `run_simulation.py`, `runs/` | 365/1,825 日实验 |

`dashboard.html` 与 `core/actions.py` 是冲突高发区；多人同时改时先约定接口字段。

### 16.4 代码风格

- Python 3.10+ 类型标注；模块顶部 `from __future__ import annotations`。
- 业务拒绝用 `ActionRejected("CODE", "中文原因")`，不要抛裸异常。
- 事件类型用稳定 snake_case；payload 保持 JSON 可序列化。
- 不写无意义注释；只在约束/坑点处写一行说明。
- 中文 UI 文本；代码标识符英文。
- 新增数值优先进 `config/rules.json`，不要散落魔法数。

### 16.5 评审重点

- 是否绕过了规则引擎？
- 是否破坏人口守恒/世界哈希/确定性？
- 新字段是否进入存档与回放？
- AI 是否能通过该机制获得无限资源或绕过校验？
- UI 是否只读服务端权威状态？
- 是否泄露密钥或预算失控？
- 是否跑过长期模拟？

### 16.6 GitHub 协作

- 所有人通过 GitHub 仓库协作，不再使用 SMB/SSH/Radmin 远程接入。
- `main` 保持可运行；功能在 `feat/<topic>` 分支开发，通过 Pull Request 合并。
- PR 描述写清：改动目的、影响的存档/协议/配置、测试与长期模拟结果。
- 世界基线 `output/world_2000BCE.json` 是二进制等价输入，任何修改都必须单独评审并同步更新哈希/存档兼容说明。
- 大存档、实验输出和截图不提交；需要分享时使用 Release 附件或外部存储。
- 本机 `live_server.py` 仍然只监听 `127.0.0.1`，没有认证；不要把它部署到公网。

---

## 17. 常见故障排查

### 17.1 端口被占用

Windows：

```bat
netstat -ano | findstr 8765
taskkill /PID <PID> /F
```

或换端口：

```bash
./.venv/Scripts/python live_server.py --port 8766
```

### 17.2 页面一直“正在载入”

- 确认服务进程还活着，`/api/state` 返回 200。
- 浏览器控制台看 JS 错误。
- 如果使用隐藏/后台浏览器自动化，`requestAnimationFrame` 可能被节流；手动调用 `poll(true)` 或用可见的 headless 页面。

### 17.3 控制台中文乱码

- 存档/接口使用 UTF-8；Windows 控制台可能按 GBK 显示。
- 临时设置 `PYTHONIOENCODING=utf-8`，或改用支持 UTF-8 的终端。

### 17.4 存档加载失败

- `static world SHA-256 differs`：世界基线被改动或换行被转换。恢复原文件；不要手改 `output/world_2000BCE.json`。
- `unsupported save format`：格式版本不匹配，检查是否改了 `format_version`。
- 存档引用的 `world_file` 不存在：确认相对路径和目录结构。

### 17.5 回放指纹不一致

- 是否有未记录的随机数？
- 是否新增了派生字段并写进指纹，但回放无法重现？
- 是否绕过了动作日志直接改城市？
- 是否在回放时错误启用了 CityManager？
- 对比 `tests/test_agents_replay.py` 的两个回放测试。

### 17.6 LLM 返回空动作/失败

- 检查密钥环境变量是否配置。
- 推理模型可能把输出预算耗在 reasoning 上；提高 `max_output_tokens`（上限 4000）。
- 确认返回是纯 JSON，不要 Markdown 围栏。
- 检查 `country_id`、`world_day` 是否与观察一致。
- 查看事件日志里的 `llm_call` / `agent_fallback`。

### 17.7 测试找不到 pytest / scipy

使用项目 `.venv`，不要用全局 Python：

```bash
./.venv/Scripts/python -m pip install pytest
./.venv/Scripts/python -m pytest -q
```

---

## 18. 已知限制与路线图

当前是垂直切片，不是完整商业游戏。

已知限制：

- 六家 LLM 厂商的预设已完成接入与本地安全测试，但尚未用五家真实账号逐一验收；模型 ID 以各账号控制台实际开通情况为准。
- Mock 规则 AI 仍是基线强度，尚未进行“无 Key 玩家也能获得完整体验”的深度策略优化。
- 军事是战略抽象：单支军队，无海军、围城、补给线、多军团。
- 城市没有完整物资库存与城市间商品网络；目前只有粮食账本与地方预算。
- 城市服务已有治安/卫生指标，但还没有独立的卫生所、治安所、消防等设施与事件链。
- 无正式胜利动画、音效、过场；结算为 UI 面板。
- 世界气象是游戏模型，不是科学天气预报。
- 前端是单文件原生 JS，无组件化/构建系统；规模继续增长时需要拆分。
- 实时服务无认证，只适合本机；远程访问需额外认证层。
- 存档格式版本 1；破坏性变更尚无迁移框架。
- 事件日志会随长期运行增长，尚未做归档。

路线图（详见 `PROJECT_PLAN.md`）：

1. 城市物资库存、完整分区供需、城市服务设施。
2. 更强的 AI 市长诊断与预算解释。
3. 多军团、海军、围城、补给线、战争目标。
4. 时代专属建筑/单位/政策，更多剧本与目标模式。
5. 正式美术、动画、音效、胜利演出。
6. UI 组件化与可访问性。

---

## 19. 附录：快速参考

### 19.1 常用命令

```bash
# 测试
./.venv/Scripts/python -m pytest -q

# 实时观察台（Mock）
./.venv/Scripts/python live_server.py --days 365 --speed 2 --paused --open

# 带 LLM（需本机密钥文件与预算）
./.venv/Scripts/python live_server.py --days 180 --speed 2 --open \
  --models config/models.deepseek.json --api-key-file "/path/to/key" \
  --max-calls 2 --max-cost-usd 0.10

# 批处理 365 日
./.venv/Scripts/python run_simulation.py run --days 365

# 从存档继续
./.venv/Scripts/python run_simulation.py run --load runs/eos_365.json --days 365 \
  --save runs/eos_730.json

# 地图重建（不要覆盖 output/）
./.venv/Scripts/python worldgen.py --seed 2000 --output output_regenerated
```

### 19.2 关键文件

```text
core/state.py                 数据模型、存档、summary、胜利
core/rules.py                 唯一写入口、日推进
core/actions.py               动作 schema
core/economy.py               经济、粮食物流、预算
core/society.py               城市指标、分区、评分、胜利条件
core/city_governance.py       AI 市长
live_server.py                HTTP + 会话 + 存档槽
dashboard.html                单页 UI
config/rules.json             全部平衡参数
config/llm_providers.json     LLM 厂商简单模式预设（端点/默认模型/文档）
output/world_2000BCE.json     不可覆盖的静态世界基线
runs/saves/                   存档槽（不入库）
runs/worlds/                  自定义随机世界（不入库）
```

### 19.3 状态字段速查

国家快照主要字段：

```text
population, food, treasury, tax_rate, workers, policy
technology, research_field, research_progress
tiles, outposts, buildings, projects, cities
stability, housing, food_capacity, last_economy
army_strength, army_position, at_war_with, war_exhaustion
diplomacy, scores(total/breakdown), victory
```

城市快照主要字段：

```text
city_id, name, center, population, focus, tiles
housing, food_potential, food_output, food_need, food_balance
food_self_sufficiency, food_status, food_loss
budget, budget_label, local_revenue, local_upkeep, local_net
security, health, security_target, health_target, security_status, health_status
livability, managed_by, zones, buildings, tiles_detail
```

### 19.4 验证用数值

- 世界：72×54，3,888 格；2,703 陆地；1,185 海洋；289 河流格。
- 默认四国：ELAR / MARIS / VAYR / SAHAR。
- 默认新城：目标 5 格城域（地形/相邻无主陆地不足时可能更少）。
- 科技：3 线 × 6 级。
- 默认规划周期：90 日。
- 自动保存：每 30 日。
- 测试：72 项。
- 实时服务默认端口：8765。

---

**维护约定：** 修改动作协议、存档格式、核心不变量、启动方式或团队分工时，请同时更新本说明书。文档应始终能让一位新同事在不问人的情况下完成“装环境 → 跑测试 → 启动 → 改一个动作 → 验证”的闭环。
