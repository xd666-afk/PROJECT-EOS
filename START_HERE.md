# Project Eos — 开发入口

**先读 [`DEVELOPER_MANUAL.md`](DEVELOPER_MANUAL.md)。** 这是当前项目的完整开发说明书：启动、架构、动作协议、城市系统、API、存档/回放、测试与协作规范。

**当前版本 v0.49：见 [`STRATEGY_UI_2026-11-15.md`](STRATEGY_UI_2026-11-15.md)。** 地图为主的实时战略交互，顶部国旗与资源、左侧对象、底部命令、固定时间控制。

**此前小更新 v0.48：见 [`MAP_SIZES_2026-11-15.md`](MAP_SIZES_2026-11-15.md)。** 新建世界可选小、中、大图，默认小图，旧档尺寸保留。

**此前版本 v0.47：先读 [`ROADS_RESEARCH_2026-11-15.md`](ROADS_RESEARCH_2026-11-15.md)。** 道路与建筑共存、整段规划、地形与跨河许可、30 项分支科技。

**此前交互版 v0.46：先读 [`INTERACTION_REWORK_2026-11-14.md`](INTERACTION_REWORK_2026-11-14.md)。** 地图常驻与对象操作重构，沿用现有美术。

**物流与外交 v0.45：先读 [`CIVIL_NETWORKS_2026-11-14.md`](CIVIL_NETWORKS_2026-11-14.md)。** 已实现城市粮仓与真实道路调运、外交通行、物流图层和地图军队直接选择。

**此前整合请读 [`INTEGRATION_REPORT_2026-11-14.md`](INTEGRATION_REPORT_2026-11-14.md)。** 地图 v0.35 与军事 v0.43 已整合；旧交接报告保留作历史记录。

**此前交接请读 [`PROJECT_EOS_HANDOFF_2026-11-14.md`](PROJECT_EOS_HANDOFF_2026-11-14.md)**（也可打印/传阅 `Project_Eos_开发交接报告_2026-11-14.docx` 或打开 `.html` 版）：当前状态、v3 地图、道路/外交门槛、已知限制、安全约束、Git 状态与后续路线。

当前项目已经不只是地图底座，而是一个可运行的文明模拟器：

- 144×108 六边形先铺的 v3 世界、默认四国、逐日推进、暂停/倍速。
- 国家经济、科技、建设、外交、多军队与六兵种、逐日行军、野战/溃退/围城/吞并、评分与正式胜利条件。
- 世界 + 城市双层视角：城市人口、分区、邻接、宜居度、粮食物流、地方预算、AI 市长与手动托管。
- 本地实时指挥台、存档槽、动作回放、公平随机地图与自定义国家。
- 道路连通校验、外交等级与跨边界修路门槛。
- 355 项 pytest；全 Mock 可零 API 费用运行。

快速验证：

```bash
./.venv/Scripts/python -m pytest -q
./.venv/Scripts/python live_server.py --load examples/civil_networks/save.json --days 365 --paused --open
```

地图生成管线仍保留：

- `worldgen.py`：原始世界生成（静态基线 `output/world_2000BCE.json`，不要覆盖）。
- `simulate_climate.py`：首年逐日天气实验。
- `build_viewer.py` / `output/viewer.html`：离线地图查看器。
- `plot_elevation.py`：补充海拔图。
- `mapgen.py`：公平随机世界与自定义四国。
- 历史交接材料：`AGENT_MAP_HANDOFF.md`（仅作地图模块参考，项目整体以开发说明书为准）。
