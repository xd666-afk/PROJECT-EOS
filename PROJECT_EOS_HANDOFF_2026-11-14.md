# Project Eos 开发交接报告

> 交接日期：2026-11-14  
> 代码版本：v0.35（六边形先铺 + 道路/外交门槛）  
> 测试状态：**103 passed**（本地实测 26.96 秒）  
> 项目路径：`D:\CCCQoder\project_eos\Project_Eos_Map_Generation_v0.1`  
> GitHub：<https://github.com/xd666-afk/PROJECT-EOS>（分支 `main`）  
> 本文面向接手开发的工程师，假设你熟悉 Python，但不了解本项目。

---

## 0. 60 秒交接摘要

Project Eos 是一个**本地、确定性、可暂停的实时文明模拟沙盘**：世界地图 + 城市双视角，2–12 个国家由规则 AI、LLM 或玩家控制，共用同一套动作规则。当前是垂直切片，不是完整商业游戏。

现在你应该先做三件事：

```bash
cd D:\CCCQoder\project_eos\Project_Eos_Map_Generation_v0.1
.venv/Scripts/python -m pytest -q          # 应看到 103 passed
.venv/Scripts/python live_server.py --days 365 --speed 2 --paused
```

然后打开 `http://127.0.0.1:8765/`，选择“继续游戏”或“载入存档”。

当前最终存档是 `runs/saves/save_1794547249538_50002.json`（世界 `runs/worlds/world_v3_custom_50002.json`，四国 A/B/C/D，公元前 800 年，第 0 日，公平度 0.8157）。注意：`runs/` 被 `.gitignore` 忽略，**不会随 Git 仓库交接**；如果只通过 GitHub 交接，需要另外拷贝这两个文件，或在新环境重新生成世界。

当前工作树有大量未提交修改（v0.32–v0.35 的地图、道路、图标、文档），Git 最后提交为 `2952c75 style(map): unify water color and recolor roads`。接手后第一步建议先完整跑测试，再按团队规范提交。

---

## 1. 项目定位与完成度

### 1.1 目标

- 玩法优先、拟真其次；每个可见机制都必须影响真实状态。
- 《文明 VI》式六边形地块 + 《群星》式可暂停实时运行 + 多国 AI。
- 不依赖大模型也能完整运行；LLM 是可选增强，不是硬依赖。
- 纯本地单机，不做联机、不做远程访问。

### 1.2 已落地

- 144×108 点顶六边形世界，每格约 750.8 km²，半径 17 km；v3 为“六边形先铺、逐格采样地形”。
- 逐日 Tick、365 日一局、90 日规划周期、暂停/继续/1×–8× 倍速。
- 国家层：人口、粮食、财政、税收、科技三线、建设、外交、贸易、军事、战争疲劳、正式胜利条件。
- 城市层：城市实体、城域、住房、仓容、稳定度、分区、邻接、宜居度、地方预算、治安/卫生、粮食物流。
- 城市治理：AI 托管 / 玩家手动 / LLM 统治者三种模式，共用动作规则。
- AI：规则 AI（Mock）+ 六家 LLM 厂商预设 + 激进/中立/保守三种性格。
- 地图表现：卫星/政治/海拔/降水/资源/交通图层、领土色、边界、河流/湖泊、细弯曲道路、透明建筑图标、通知气泡、AI 决策气泡。
- 存档/自动保存/回放/世界哈希校验；测试隔离，避免测试世界覆盖玩家存档。
- v0.35 道路系统：初始路网物流减损、道路连通校验、外交等级、跨边界修路门槛、全局弯曲渲染。

### 1.3 明确未完成

- 海军、多军团、围城、补给线、战争目标仍是最小闭环。
- 城市没有完整商品库存与城市间物流网络；粮食是抽象账本。
- 桥梁只是普通道路的视觉/数据变体，没有独立桥梁玩法（用户已明确“先不做变体”）。
- 没有正式动画、音效、过场、胜利演出。
- Mock AI 的长期规划仍偏浅，反雪球能力有限。
- 六家 LLM 预设没有逐一用真实账号验收；不同账号的模型开通情况可能不同。
- 前端是单文件 `dashboard.html`，没有构建系统、组件化、端到端浏览器测试。
- 原生客户端（脱离 HTML）仍只是方向讨论，没有决策。

---

## 2. 快速运行

### 2.1 环境

- 项目自带 `.venv`，Python 3.14.7。
- 依赖：`numpy>=1.24`、`scipy>=1.10`、`matplotlib>=3.7`；测试另需 `pytest`。
- Windows 使用 `.venv/Scripts/python`；macOS/Linux 换成 `.venv/bin/python`。
- 受 C: 盘空间限制，工具与数据尽量放 D:。

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt pytest
```

### 2.2 启动本地指挥台

```bash
# 全 Mock，零 API 费用；--paused 表示启动后先暂停
.venv/Scripts/python live_server.py --days 365 --speed 2 --paused

# 自动打开浏览器
.venv/Scripts/python live_server.py --days 365 --speed 2 --paused --open
```

浏览器访问 `http://127.0.0.1:8765/`。服务只绑定 `127.0.0.1`，没有认证，不要暴露公网。

### 2.3 载入最终存档

UI：着陆页 → “载入存档” → 选择“六边形先铺 · 地形后填”。

命令行/脚本：

```python
from core.simulation import Simulation
from pathlib import Path

sim = Simulation.load(Path("runs/saves/save_1794547249538_50002.json"))
sim.step(3)
print(sim.state.day_index, sim.state.summary()["date"])
```

API：

```bash
curl -X POST http://127.0.0.1:8765/api/saves \
  -H "Content-Type: application/json" \
  -d '{"operation":"load","id":"save_1794547249538_50002"}'
```

### 2.4 新建 v3 世界

新世界默认走 v3。UI：“新建世界”。API：

```bash
curl -X POST http://127.0.0.1:8765/api/new_game \
  -H "Content-Type: application/json" \
  -d '{"seed":50002,"start_year":-799,"save_name":"新世界"}'
```

程序内直接生成：

```python
from mapgen import generate_fair_world, normalize_countries

countries = normalize_countries(None)  # 默认 4 国；也可传 2–12 国自定义列表
world, path = generate_fair_world(countries, base_seed=50002, generation_version="v3")
print(path, world["metadata"]["fairness"]["score"])
```

不要覆盖 `output/world_2000BCE.json`；它是保留的静态基线，有 SHA-256 校验。重新生成请写到 `output_regenerated/` 或 `runs/worlds/`。

### 2.5 批处理模拟

```bash
.venv/Scripts/python run_simulation.py run --days 365
.venv/Scripts/python run_simulation.py status --save runs/eos_latest.json
.venv/Scripts/python run_simulation.py interactive --load runs/eos_latest.json
```

### 2.6 测试

```bash
.venv/Scripts/python -m pytest -q
# 103 passed
```

测试必须使用临时目录生成世界，避免覆盖 `runs/saves` 和玩家世界哈希。v1/v2/v3 生成器都支持 `output_dir`，不要移除。

---

## 3. 架构与数据流

```text
dashboard.html（单页 Canvas + 原生 JS）
        │  GET /api/world /api/state ...；POST /api/action ...
        ▼
live_server.py
  LiveSession（线程锁、暂停、倍速、自动保存、存档槽、玩家国家）
        │
        ├── Simulation
        │     ├── GameClock（日推进、倍速）
        │     ├── RuleEngine（唯一动作写入口）
        │     └── GameState（世界、国家、城市、事件、动作日志）
        │
        └── AgentScheduler（90 日规划、观察隔离、并发决策）
              ├── HeuristicAgent（规则 AI / Mock）
              └── LLM adapter（OpenAI 兼容、预算、日记、性格）
        │
        ▼
地图生成：mapgen.py → mapgen_v3.py（新默认）/ mapgen_v2.py（旧世界）
规则数值：config/rules.json
厂商预设：config/llm_providers.json
```

### 3.1 动作管线

1. 前端提交 `{"type": "...", ...}`。
2. `LiveSession.player_action` 检查玩家国家。
3. `RuleEngine.apply_action` 调用 `validate_action` 做 schema 校验。
4. 规则层做所有权、地形、科技、财政、冷却、连通性等业务校验。
5. 通过后修改 `GameState`，写入 `action_log` 和 `event_log`。
6. 前端下一次 `snapshot()` 拉到新状态；失败返回 `accepted=false` 与 `reason_code`。

所有国家（玩家、Mock、LLM）都走同一个入口，不允许绕过规则直接改状态。

### 3.2 确定性

- 世界由 seed 决定；生成结果、首都、领土、路网可复现。
- 模拟按日推进，不依赖真实时间；`--speed` 只影响观察节奏。
- 存档保存世界文件路径与 SHA-256；世界文件被改动后载入会校验失败。
- 测试覆盖存档往返、回放、断点续跑。

---

## 4. v3 地图生成

### 4.1 网格

- 144×108 = 15,552 格；odd-r pointy-top 六边形。
- 每格面积 750.8 km²，半径 17 km。
- 地图纬度约 8°–51°N，地球式 24 小时/365 天假设。

### 4.2 生成顺序（v3）

1. 在 576×432 高分辨率栅格上生成基础陆地、海拔、断层。
2. 清理小岛/噪点，平滑生物群系。
3. 生成气候（温度、月降水）。
4. 生成水文：流向、汇水面积、河段、封闭盆地、湖泊。
5. **逐六边形采样**：每个格直接取地形、气候、水文、灾害，分类为 biome。
6. 放置首都：按国家 archetype 评分，保证国家间距离。
7. 划分 16 格连通核心领土，检查公平度。
8. 生成初始道路：连接首都的最小生成树/最低成本六边形路径；河格标记为桥。
9. 打包 metadata，校验 schema。

关键文件：`mapgen_v3.py`（432 行），复用 `mapgen_v2.py` 的水文/湖泊/河段整形辅助函数。`mapgen.py` 是统一入口，`generate_fair_world(..., generation_version="v3")` 默认分派到 v3。

### 4.3 水体

- 海洋和湖泊都是六边形水体，统一海水蓝绘制。
- 河流占一格宽，`river_cells` 保存水深、覆盖率、流向、汇水面积、`kind`、`terminal_lake_id`。
- 内流河 `kind=endorheic` 在湖岸终止，不进入海洋；外流河最终入海。
- 湖泊来自封闭洼地/不与外海连通的封闭水域，`lake_cells` 保存深度与湖面高程。
- 城心、道路格、建城目标格不得落在湖格/河面；规则分别返回 `LAKE_TILE`、`RIVER_TILE`。

### 4.4 审计世界 50002（当前最终存档）

| 项目 | 数值 |
| --- | --- |
| 网格 | 144×108，15,552 格 |
| 陆地 / 海洋 | 11,314 / 4,238 |
| 内湖 | 6 个（LK01–LK06），70 个湖格 |
| 河格 | 881，其中内流河 226 |
| 初始道路 | 112 格 |
| 公平度 | 0.8157 |
| 世界文件 | `runs/worlds/world_v3_custom_50002.json`（约 8.3 MB） |
| 存档 | `runs/saves/save_1794547249538_50002.json`（约 258 KB，引用世界文件） |
| 365 日 Mock 审计 | 通过，城心全部干地 |

### 4.5 v2 兼容

- 旧 v2 世界 `schema_version=2`、连续地形纹理 + 144×108 聚合，仍可载入。
- `mapgen_v2.py` 保留约 1,420 行，不建议继续扩展；新功能优先写 v3。
- `validate_v2` 接受 schema_version 2 和 3。

---

## 5. 核心玩法系统

### 5.1 日推进与规划

- `Simulation.run(days)` 每天调用 `RuleEngine.step_day`。
- 每 90 日 AI 做一次规划；每 30 日自动保存。
- 胜利条件每回合检查，达成后暂停。
- 天气是物理启发的程序模型，不是 GCM；天气影响粮食产出与灾害事件。

### 5.2 经济

- 粮食：地块基础产出 × 天气 × 道路 × 城市方针 × 分区 × 邻接 × 宜居。
- 财政：人口税、矿业、贸易 +5%、城市地方预算上缴/调入。
- 粮食跨城调配有损耗；道路降低损耗（有上限）。
- 初始路网提供一份基础物流减损；动态 `ROAD` 建筑按数量计入。
- 高税会压低产出；缺粮会提高死亡率。

### 5.3 城市

- 城市有中心、城域、人口、住房、仓容、稳定度、宜居度。
- 分区：住宅、农业、工业、商业、学术等；中心邻接有加成。
- 地方预算：税收、矿业、维护、公共服务。
- 治安/卫生是抽象指标，由神庙、市场、道路、粮仓、灌溉等影响。
- 新城通过 `SETTLE` 在相邻无主陆地建立，自动纳入约 5 格城域。
- 双击城市进入城市规划视图；城市内建造与大地图共用全国上限和规则。

### 5.4 科技、外交、军事、胜利

- 科技三线（农业/冶金/文字）各 6 级，按时代重命名节点。
- 外交：-100..+100 关系、赠礼、贸易协定、和平提案；关系 15 可提议贸易。
- 军事：招募、行军（单次最多 4 格）、宣战、边境/远征战斗、占领、疲劳、和平。
- 胜利：知识（科技 6 级）、繁荣（人口/财政/粮食）、疆域（领土/城市/领先比）、安定（稳定/宜居/人口）。

### 5.5 AI 与性格

- `HeuristicAgent`：规则 AI，免费、默认；按粮食、财政、威胁、扩张、建设评分选动作。
- `LLM adapter`：OpenAI 兼容，六家厂商预设；预算按调用次数和估算费用双重限制。
- 性格：激进/中立/保守，写入存档与席位 UI；Mock 和 LLM 共用。
- LLM 决策以地图气泡展示，写入第一人称统治日记。
- 观察隔离：AI 只能看到自己国家的状态；玩家接管的国家的 AI 决策暂停。

---

## 6. v0.35 道路系统（本次重点）

### 6.1 数据

- 初始路网：`world.data["road_cells"]`，每项形如：

```json
{
  "tile": {"col": 25, "row": 25},
  "owner_id": "A",
  "kind": "road" | "bridge",
  "network_id": 1
}
```

- 动态道路：`country.buildings[(col,row)] = "ROAD"`。
- 初始道路只作为物流基础设施，**不**逐格计入住房/治安；避免开局 112 个路格把平衡刷爆。
- 动态 `ROAD` 建筑按正常建筑计入产出、住房、治安、维护。

### 6.2 修路规则

`core/rules.py` 中 `BUILD` 的检查顺序：

1. `TILE_NOT_OWNED`：目标格不属于本国。
2. `INVALID_TERRAIN`：海域。
3. `BUILDING_CONFLICT`：已有建筑或在建。
4. `ROAD_TILE`：目标格是初始道路，却要建其他设施。
5. 地形/科技/河道/全国上限/财政检查。
6. `ROAD_EXISTS`：目标格已经是初始道路。
7. 道路连通检查：
   - `ROAD_DIPLOMACY_REQUIRED`：相邻节点属于外交等级不足的外国；
   - `ROAD_NOT_CONNECTED`：没有任何相邻城市/道路节点。

### 6.3 连通与外交门槛

核心实现：`core/road.py`

- `road_node_owners(state, country, coord)` 收集目标格六邻接内的节点所有者：
  - 本国城市中心；
  - 外国城市中心；
  - 本国动态 `ROAD` 建筑；
  - 所有初始 `road_cells`（带 `owner_id`）。
- `road_connection_status(state, country, coord)`：
  - 无任何节点 → `connected=False, denied=[]`；
  - 有外国节点且 `state.diplomatic_level(本国, 外国) < state.road_connection_level()` → `denied` 非空；
  - 否则 `connected=True`。

外交等级定义在 `config/rules.json`：

| id | 标签 | 最低关系 |
| --- | --- | --- |
| 0 | 敌对 | -100 |
| 1 | 冷淡 | -30 |
| 2 | 中立 | 0 |
| 3 | 友好 | 25 |
| 4 | 同盟 | 60 |

`road_connection_level` 默认 **3（友好，关系 ≥ 25）**。跨边界连通不同国家路网必须达到该等级。

### 6.4 初始路网例外

初始世界路网视为“历史基线”，保留原有连通，不受新外交门槛追溯限制。门槛只约束**新建道路**。

这带来一个已知边界：如果初始路网恰好跨过两国边界，视觉/物流上可能已经连通；当前 50002 世界没有这种相邻节点，所以未触发。接手后若要彻底封闭，需要给初始路网也做一次外交归属审计，或在生成时避免跨边界路网。

### 6.5 AI 修路

`agents/scheduler.py` 观察项新增：

- `road_cell`：该格是否已有初始道路；
- `road_connected`：是否满足连通/外交门槛；
- `road_denied`：拒绝连通的外国列表。

`agents/heuristic.py`：

- 非道路建筑候选排除 `road_cell`；
- `ROAD` 候选要求 `road_connected == true` 且 `road_cell == false`；
- 道路评分：`1.8 - abs(elev-400)/1000 + 0.4 if river`。

因此 AI 不会再修孤立断头路，也不会在关系不足时强行跨国连通。

### 6.6 渲染

`dashboard.html` 中：

- `roadEntityCells` 收集初始 `road_cells` + 动态 `ROAD` 建筑；
- `roadChainsFromCells` 建全局路网图，按相邻格组链（不再按国家分组，避免视觉断裂）；
- `smoothRoadPath` 使用 Chaikin 平滑 + 确定性多频率值噪声横向偏移；
- `strokeRoadPath` 画深色描边 + 陶土色内线 + 阴影；
- 起点、终点、岔路口保持准确；不填充六边形。

### 6.7 当前验证结论

2026-11-14 实测：

- 载入 `save_1794547249538_50002` 正常，四国均存在，道路门槛 3。
- 后端临时构造“A 国边界格邻接 B 国初始道路”：关系 0 时返回 `ROAD_DIPLOMACY_REQUIRED`；关系改为 30 后修路成功。
- 玩家接管 D，选中都城相邻格 `(100,24)`，道路按钮可用，点击后项目入队，财政 100 → 85。
- 前端注入一条相邻的外国道路后，按钮显示“需与 国家A 达到友好”并禁用；关系改为 30 后恢复“条件满足”。注入仅在浏览器内存中，未写入存档。
- 浏览器控制台无报错。

---

## 7. UI 结构

### 7.1 一级/二级导航

一级：世界、国家、城市、科技、外交、军事、AI、系统。每个入口打开独立全屏 deck。

二级标签：

- 国家：概览 / 城市 / 排名
- 城市：列表 / 规划
- 科技：总览 / 三线
- 外交：关系 / 提案
- 军事：军队 / 战争
- AI：席位 / 档案
- 通知：动态 / 工程

### 7.2 地图

- 图层：卫星、政治、海拔、降水、资源、交通。
- v3 卫星图按六边形填地形色，邻格高程做明暗，海岸线描边；无连续地形纹理。
- 领土色、边界、河流、湖泊、道路、城市标记、设施图标、施工进度环。
- 道路用细曲线；河流/湖泊统一海水蓝；内流河/内流湖在图例中单独标注。
- 点击地块打开“详情检视”；玩家模式下可建造。
- 通知以气泡出现，可点击进入通知中心。

### 7.3 图标

- 根目录 `assets/icons/`：15 个映射图标（farm、mine、road、granary、irrigation、workshop、library、market、temple、great_*、palace、city_center、military_camp）。
- `assets/icons/buildings/`：32 个英文命名的新六边形徽章素材 + `MAPPING.txt`；旧图标备份在 `runs/old_icons_backup/`。
- 图标为透明 PNG，通常 320×320；`workshop.png` 由 GPT Image Studio 参考图生成后抠底。
- `.build-thumb` 使用 `object-fit: contain`，不加方形边框。

### 7.4 已知 UI 限制

- `dashboard.html` 约 3,372 行，单文件、无构建；改动时注意不要破坏 DOM id 和函数名。
- 测试只做静态 HTML 断言，没有真实浏览器端到端测试。
- 窄视口（如 610 px）下外交页关系条标签会拥挤；桌面宽屏正常。
- 服务端改动后必须重启 `live_server.py`，否则新规则/字段不会加载。

---

## 8. API 与存档

### 8.1 API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/world` | 世界 metadata、polities、tiles、river/lake/road_cells、rendering |
| GET | `/api/state` | 当前快照：国家、城市、建筑、项目、外交等级、胜利、事件 |
| GET | `/api/terrain` | v2 旧世界地形纹理；v3 返回空/不使用 |
| GET | `/api/agents` | AI 席位配置与用量 |
| GET | `/api/setup` | 厂商/模型预设 |
| GET | `/api/saves` | 存档列表 |
| GET | `/api/diary` | LLM 统治日记 |
| POST | `/api/action` | 玩家动作 |
| POST | `/api/control` | 暂停/继续/倍速/快进 |
| POST | `/api/new_game` | 新世界（v3） |
| POST | `/api/saves` | `save` / `load` / `delete` |
| POST | `/api/agents` | 配置某国 AI 席位 |
| POST | `/api/agents/test` | 最小连接测试 |
| POST | `/api/agents/budget` | 调用次数/费用预算 |
| POST | `/api/agents/personality` | 设置性格 |

`/api/state` 快照新增字段：`diplomacy_levels`、`road_connection_level`。

### 8.2 存档格式

- `GameState.save(path)` 写 JSON：`format`、`world_file`、`world_sha256`、`seed`、`day_index`、`rules`、`countries`、`relations`、`pacts`、`weather`、`action_log`、`event_log`。
- 世界本体不复制进存档，引用外部 `world_file`；载入时校验 SHA-256。
- 存档元数据写在同名 `.meta.json`，供存档列表使用。
- 自动保存每 30 日；退出时也保存。
- `runs/` 被 Git 忽略；交接时需单独拷贝存档和世界，或重新生成。

### 8.3 测试隔离

- v1/v2/v3 生成器都接受 `output_dir`。
- 测试写入 `tmp_path`，避免覆盖 `runs/worlds`、`runs/saves`。
- 新增生成器或改动输出路径时，务必保留该参数。

---

## 9. 测试与验证

### 9.1 测试规模

**103 passed**（2026-11-14，26.96 秒）。

| 文件 | 用例数 | 覆盖 |
| --- | ---: | --- |
| `test_actions.py` | 27 | 动作 schema、建造、科研、政策、交易、外交、城市、预算、道路门槛 |
| `test_simulation.py` | 22 | 日推进、暂停、倍速、存档、经济、评分、胜利、灾害 |
| `test_llm_adapter.py` | 11 | OpenAI 兼容、重试、预算、Usage、失败回退 |
| `test_agents_replay.py` | 9 | 观察隔离、玩家跳过、回放、断点续跑 |
| `test_personality.py` | 6 | 三种性格、Mock/LLM 一致性 |
| `test_dashboard_ui.py` | 6 | 静态 UI 断言、v3 地图、道路函数、图标 |
| `test_generated_world.py` | 4 | 世界完整性、气候、连通、天气 |
| `test_messages.py` | 4 | 事件短讯、日记气泡 |
| `test_mapgen_v2.py` | 3 | v2 连续地形、河深/道路、内湖/内流河 |
| `test_providers.py` | 3 | 厂商预设、模型选择 |
| `test_mapgen.py` | 2 | v1 公平世界、六国 |
| `test_mapgen_v3.py` | 2 | v3 生成、道路节点、外交等级、存档往返 |
| `conftest.py` | — | 测试夹具 |

### 9.2 本次交接前的验证

- `pytest -q`：103 passed。
- 载入最终存档：通过。
- 外交等级：四国均为中立（2），道路门槛 3。
- 后端跨边界修路门槛：中立拒绝、友好放行。
- 玩家手动修路：从都城相邻格成功。
- 前端拒绝原因：显示“需与 国家A 达到友好”。
- 浏览器控制台：无报错。

### 9.3 尚未自动化的验证

- 真实浏览器端到端（点击地图、存档、AI 席位）仍靠人工。
- 六家 LLM 厂商没有逐家用真实账号验收；只做过 DeepSeek 小规模真实动作闭环。
- 长期平衡只跑到 1,825 日（Mock），不代表 12 国/长期稳定。
- 多国（>4）UI 布局和道路外交组合没有系统压力测试。

---

## 10. 最近变更（v0.33–v0.35）

### v0.33 水文重置

- 河段追踪 + 正弦蜿蜒、河谷走廊、封闭内流盆地。
- 内流河在湖岸终止，注册 `terminal_lake_id`。
- 内湖深度梯度；UI 统一海水蓝。

### v0.34 六边形先铺

- 从“连续地形 → 量化”改为“先铺六边形 → 逐格采样”。
- 取消 576×432 地形纹理，海岸线沿六边形边，消除锯齿。
- 生成时间约 20–50 秒降到 1–2 秒；世界文件约 19 MB 降到 8 MB。
- 新世界 metadata：`schema_version=3`、`generator=mapgen_v3_hexfirst`、`terrain_mode=hex_fill`。

### v0.35 道路与外交

- 初始路网物流减损；动态道路正常计入。
- 道路必须连通；禁止断头路。
- 外交等级与跨边界修路门槛；`ROAD_DIPLOMACY_REQUIRED`。
- 道路不能覆盖初始路格；其他设施也不能建在路格。
- 全局路网取链 + 确定性弯曲噪声，细线、自然弯曲、端点准确。
- 新图标集：32 个六边形徽章 + 工坊补绘。
- 测试隔离：v1/v2/v3 `output_dir`。
- 文档同步到 103 项测试。

---

## 11. 已知限制与技术债

按影响排序：

1. **Mock AI 深度不足。** 长期规划、反雪球、外交/战争判断、城市经营仍偏规则化；大多数玩家不会配置 LLM，这是体验上限。
2. **LLM 真实账号未全面验收。** 六家预设只验证了协议与部分真实调用；模型开通、限流、费用差异需要逐家测试。
3. **初始路网外交例外。** 初始 `road_cells` 不受门槛追溯；若未来生成器产生跨边界初始路网，会出现“未达友好却已连通”。建议生成时做归属审计，或在载入时拆分跨边界网络。
4. **道路门槛只看邻接节点。** 当前不搜索整条路径；它约束的是“新路格是否与外国节点相邻”，不是完整网络连通性证明。若未来要做贸易路线/物流路径，需要真正的图搜索与路径合法性校验。
5. **桥梁无独立玩法。** 目前只是 `kind=bridge` 的颜色/数据差异；没有渡河成本、桥梁维护、破坏等。
6. **城市库存/物流缺失。** 粮食是抽象账本；没有商品库存、运输队、仓储容量网络。
7. **军事简化。** 单军团、无海军、无围城、无补给线；战争目标与和平条款较简单。
8. **前端单体。** `dashboard.html` 3,372 行，无组件化/构建/端到端测试；改动容易回归。
9. **窄屏布局。** 610 px 视口下外交关系条标签拥挤；移动端未系统适配。
10. **v1/v2 兼容负担。** 两套旧生成器仍在仓库中，增加理解成本；新功能应优先 v3。
11. **无认证。** 本地服务只监听 127.0.0.1；不要加公网暴露。
12. **存档引用外部世界。** 移动/删除世界文件会导致存档载入失败；哈希能防篡改但不能自包含。若要做“单文件存档”，需要把世界内嵌或打包。

---

## 12. 安全与运维约束（必须保留）

这些是项目所有者明确要求的约束，接手后不要擅自改变：

- **不做联机/远程访问。** 已删除远程方案；默认只本地 + GitHub。
- **API Key 只存在本机服务进程内存。** 不进入存档、事件日志、`/api/state`、页面回显、Git。
- **GitHub 网络失败不重试。** 遇到网络/代理错误，保留本地提交，报告错误并停止；不要反复重试。
- **工具/数据放 D:。** C: 盘空间有限；安装器强制 C: 时用独立包或 junction。
- **国家不写死四个。** 通用 ID `A/B/C…`，默认名 `国家A/B/C…`；支持 2–12 国。历史基线 ELAR/MARIS/VAYR/SAHAR 是例外。
- **不覆盖静态基线。** `output/world_2000BCE.json` 不重新生成；新世界写 `output_regenerated/` 或 `runs/worlds/`。
- **测试不得污染玩家世界。** 生成器保留 `output_dir`，测试写临时目录。
- **截图/视觉结论要验证。** 区分数据 bug、渲染缝隙、样式问题；不要只凭代码推断“看起来对”。

---

## 13. Git 状态与交接步骤

当前：

- 分支：`main`。
- 远程：`origin https://github.com/xd666-afk/PROJECT-EOS.git`。
- 最后提交：`2952c75 style(map): unify water color and recolor roads`。
- 工作树：约 40 项未提交（29 个修改文件 + 新增文件）。
- 未跟踪的关键文件：
  - `mapgen_v3.py`
  - `core/road.py`
  - `tests/test_mapgen_v3.py`
  - `assets/icons/buildings/`（32 个图标 + MAPPING）
  - `assets/icons/city_center.png`、`military_camp.png`、`palace.png`
  - `Project_Eos_图标素材清单.txt`
  - `Project_Eos_新手试玩指南.docx`
  - `docs/report_assets/ui_v3_hexfirst*.png`

建议交接流程：

1. `pytest -q` 确认 103 passed。
2. `git diff` 逐项审查 v0.35 改动（道路、外交、UI、图标、文档）。
3. 本地提交（不要 `git add -A` 把无关文件带进来；按实际文件添加）。
4. 推送 GitHub 只尝试一次；失败按网络策略停止并保留本地提交。
5. 单独拷贝 `runs/saves/save_1794547249538_50002.json` 和 `runs/worlds/world_v3_custom_50002.json` 给接手人；它们不在 Git 中。
6. 若接手人无法获得存档，可在 UI 新建世界（v3）或运行生成脚本。

---

## 14. 推荐下一步

### P0：交接稳定化（先做）

- 提交当前工作树；确认 CI/本地测试全绿。
- 把最终存档与世界文件打包给接手人，或在文档中写清重新生成步骤。
- 修复窄屏外交页标签拥挤（纯 CSS）。
- 给道路外交门槛补一个**端到端动作测试**：构造两国相邻节点，验证 `ROAD_DIPLOMACY_REQUIRED` 与放行。当前 `test_actions.py` 只测了 `road_connection_status` 单元逻辑。
- 服务器重启后自动检测版本/配置变化，或在文档/UI 提示“后端改动需重启”。

### P1：玩法深度

- **城市库存与物流**：商品库存、仓储、运输网络、道路实际路径与容量。
- **道路网络图**：从“邻接门槛”升级为“路径合法性 + 连通分量 + 贸易路线”；支持断路、维护、桥梁。
- **Mock AI 长期规划**：反雪球、外交记忆、战争目标、城市专业化；可参考 `PERSONALITY_EXPERIMENT_REPORT.md` 做对照实验。
- **桥梁变体**（用户暂缓）：渡河成本、桥梁维护、战争破坏；数据层已预留 `kind=bridge`。
- **多军团/海军/围城/补给**：先把军事从单军团扩展为可调度单位。

### P2：表现与平台

- 原生客户端决策：Python 引擎可分离，但需要先决定 PySide6/Qt 或其他方案；不要在没有决策时大规模重写。
- 前端拆分：把 `dashboard.html` 拆成模块（地图、面板、API、状态），引入最小构建或至少按文件拆分。
- 动画/音效/胜利演出。
- 更多地图脚本、时代内容、政策/建筑。

### P3：质量

- 真实浏览器端到端测试（Playwright/Selenium）。
- 12 国长期平衡实验与性能基准。
- 存档自包含/迁移工具。
- v1/v2 旧世界清理或明确冻结。

---

## 15. 交接检查清单

- [x] 代码可运行
- [x] 103 项测试通过
- [x] 最终存档可载入
- [x] v3 地图与 UI 正常
- [x] 道路/外交门槛后端验证
- [x] 道路/外交门槛前端验证
- [x] 浏览器控制台无报错
- [x] 文档更新到 v0.35 / 103
- [ ] 提交当前工作树
- [ ] 推送 GitHub（按一次性网络策略）
- [ ] 单独交接 `runs/saves` 与 `runs/worlds`
- [ ] 真实 LLM 厂商账号验收
- [ ] 原生客户端方案决策

---

## 附录 A：关键命令

```bash
# 测试
.venv/Scripts/python -m pytest -q

# 实时观察台（暂停启动）
.venv/Scripts/python live_server.py --days 365 --speed 2 --paused

# 批处理 365 日
.venv/Scripts/python run_simulation.py run --days 365

# 载入存档跑 30 日
.venv/Scripts/python run_simulation.py run \
  --load runs/saves/save_1794547249538_50002.json --days 30

# LLM 服务（本地 Key 文件，预算上限）
.venv/Scripts/python live_server.py --days 365 --speed 2 --paused \
  --models config/models.deepseek.json \
  --api-key-file "/path/to/local-key" \
  --max-calls 40 --max-cost-usd 1.00

# 重建静态基线（不要覆盖 output/）
.venv/Scripts/python worldgen.py --seed 2000 --output output_regenerated
```

## 附录 B：关键文件

```text
core/state.py                数据模型、存档、summary、外交等级、胜利
core/rules.py                唯一写入口、建造/建城/道路规则、日推进
core/road.py                 道路节点归属、连通状态、外交门槛
core/actions.py              动作 schema 与基础校验
core/simulation.py           run/pause/speed/save/load 高层封装
core/economy.py              经济、粮食物流、预算、服务、事件
core/society.py              城市指标、分区、评分、胜利条件
core/city_governance.py      AI 市长
core/construction.py         建造项目推进
core/diplomacy.py            关系、贸易、提案
core/military.py             招募、行军、战斗、占领、和平
core/frontier.py             边疆开拓
core/replay.py               动作回放
core/messages.py             事件短讯与统治者消息
agents/heuristic.py          规则 AI
agents/scheduler.py          90 日规划、观察隔离、道路观察
agents/llm_adapter.py        OpenAI 兼容、预算、日记
agents/personality.py        三种性格
agents/providers.py          厂商预设
mapgen.py                    v1/v2/v3 统一入口
mapgen_v3.py                 v3 六边形先铺（新默认）
mapgen_v2.py                 v2 连续地形（旧世界兼容）
worldgen.py                  原始世界、气候、水文、灾害、天气
live_server.py               HTTP、LiveSession、存档槽、预算
dashboard.html               单页 UI、地图、城市、道路、AI 席位
config/rules.json            平衡参数、外交等级、道路门槛
config/llm_providers.json    厂商/模型预设
runs/saves/                  存档（Git 忽略）
runs/worlds/                 随机世界（Git 忽略）
output/world_2000BCE.json    不可覆盖的静态基线
assets/icons/                图标映射与资源
tests/                       103 项 pytest
```

## 附录 C：关键绝对路径（本机）

```text
项目：D:\CCCQoder\project_eos\Project_Eos_Map_Generation_v0.1
最终存档：D:\CCCQoder\project_eos\Project_Eos_Map_Generation_v0.1\runs\saves\save_1794547249538_50002.json
最终世界：D:\CCCQoder\project_eos\Project_Eos_Map_Generation_v0.1\runs\worlds\world_v3_custom_50002.json
开发手册：D:\CCCQoder\project_eos\Project_Eos_Map_Generation_v0.1\DEVELOPER_MANUAL.md
阶段报告：D:\CCCQoder\project_eos\Project_Eos_Map_Generation_v0.1\PROJECT_EOS_DEVELOPMENT_REPORT.md
新手指南：D:\CCCQoder\project_eos\Project_Eos_Map_Generation_v0.1\Project_Eos_新手试玩指南.docx
图标清单：D:\CCCQoder\project_eos\Project_Eos_Map_Generation_v0.1\Project_Eos_图标素材清单.txt
```

---

**交接结论：** 代码处于可运行、可测试、可继续开发的状态；v3 地图与 v0.35 道路/外交门槛已验证。最大的未完成项是城市库存/物流、Mock AI 深度、桥梁玩法和原生客户端决策；最大的交接风险是 `runs/` 不在 Git 中，以及当前约 40 项工作树改动尚未提交。
