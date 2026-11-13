# v0.41–v0.43 交接报告：这一批改了什么，还有什么没改

对应提交：[`43cd12a` feat(military): borders slow marches and enemy camps can be fought](https://github.com/zsmb07/neirong/commit/43cd12a)
分支：`feat/military-units`（尚未合进 `main`）
规模：38 个文件，+13116 / −427
写作时间：2026-11-13

这份报告只干两件事：把这一批的改动讲清楚，然后把**已知还没修的问题**一条条列出来，列到能直接照着下手的粒度。接手的人（云电脑上的我）不需要重新读一遍 diff。

---

## 一、这一批解决了什么

三个用户诉求，按版本号排：

- **v0.41 溃退**：打赢了不只是「对方人数变少」，而是整条队伍溃散、幸存者折返、营帐可能一起丢。
- **v0.42 点哪格都能行军 / 敌人扎在野地里也能打**：点击任意一格空地，右侧弹「行军至此」并能在卡片里选军队；敌方驻扎在**不是它领土**的格子上的军队，也能就地打——这是野战，歼其军而边界不动。
- **v0.43 边境减速 + 距离误判**：铺了路的地方军队更快，别国领土内更慢；除了「被敌国围死」，地图上任何一点都该到得了。原来的 bug 是路太远就被判定「没有路可走」。

一句话概括这一批的规则改动：**行军从「能不能走」变成了「走得动但走不快，落点另有规矩」，野战从「打不了」变成了「打得但拿不到地」。**

## 二、数据层：规则表新增了一整个 `movement` 块

`config/rules.json:729-745`（本批之前 `rules.json` 里根本没有 `movement` 这个块）：

| 键 | 值 | 含义 |
| --- | --- | --- |
| `daily_budget` | 3.0 | 一支军队一天能烧掉多少点移动成本——行军是逐日推进的下单，不是瞬移 |
| `road_cost` | 0.35 | 道路每格成本，**不分归属**都按这个价；边境附加费是叠在它上面的，所以敌国境内的路（0.35+1.25=1.6）仍然比本国草原（1.0）贵、但比敌国的山地（2.4+1.25）便宜 |
| `hostile_cost` | 1.25 | **本批新增**：格子属于别国时，在该格的每格成本上追加的附加费 |
| `maximum_order_cost` | 60.0 | 单条命令的成本上限；超了不是「到不了」，是「一条令走不到，要分段下令」 |
| `biome_cost` | 草原 1.0 → 山地 2.4 | 地形基础成本，覆盖世界文件里出现的每个陆地群系（缺一个就建局时报 `ContentError`） |

校验在 `core/content.py`：`MOVEMENT_KEYS` 收进了 `hostile_cost`，`_validate_movement` 要求 `hostile_cost >= 0` 且 `maximum_order_cost > road_cost + hostile_cost`——最后这条保证「任何一格至少能作为一条命令的落脚点」，否则分段行军在数学上不可能。

`military.expedition_factor` = 0.78（`config/rules.json:684`），`military.rout` = `{survivor_rate: 0.4, barracks_lost_survivor_rate: 0.0, retreat_radius: 1}`。

## 三、结算层：`core/military.py` + `core/movement.py`

**成本与路径**

- `core/movement.py`：`Movement` 读进 `hostile_cost`，`cost()` 在 `state["hostile"]` 为真时把附加费加到该格上；`search()` 多了 `cap` 参数，可以跑一次不设上限的搜索。
- `core/military.py:489` `_road(actor, start, target, *, movement=None, explain=False)` 返回 `{plan, reason, cost, days}`，reason ∈ `SEA` / `NO_ROAD` / `ENCLAVED` / `ORDER_LIMIT`。`explain=True` 时**多付一次不设上限的搜索**，专门用来把「太远，一条令走不到」和「根本没有陆路连着」这两种情况分开——这正是 v0.43 那个 bug 的根因：原来两者都报成「没有路」。
- `core/military.py:554` `_refusal()` 把它翻译成给面板和回执看的四种诚实说法：`INVALID_TERRAIN` / `NO_LAND_LINK` / `ORDER_LIMIT`（带上真实成本与天数）/ 外加 `FOREIGN_GROUND`、`ALREADY_THERE`。
- `core/military.py:527` `_expedition()` 现在**从实际走出来的路线**判断这支军队是否算远征（沿途是否踩到别国领土），不再靠「起点终点不同国」猜；`expedition_factor` 0.78 仍然惩罚抵达战力。

**穿过 ≠ 驻下**

- `core/military.py:91` `_marchable()`：MARCH 令的**落点**只能是己方或无主的格子；ATTACK 令哪都能落。这是这一批最重要的一条规则线，面板文案、AI 提示词、引擎回执三处必须说的是同一套话。
- `march_daily` 不再因为沿途格子易主就取消在途命令（原来的行为会让一场边境拉锯把所有行军令清零）。

**野战**

- `attack` → `_attack_tile`，当目标格**不在**防守方的 `tiles` 里时走 `core/military.py:1507` `_attack_camp()`。
- `_battle` 新增 `seizes = target_tile in defender.tiles`，并把 `"field": not seizes` 报进结果：赢了只是打散这条队伍，**边界一格都不动**，对方其他在途军队照旧走它的路。
- `_arrive` 的触发条件放宽成 `ground or camped`，扎在野地里的营帐也能被抵达结算撞上。

**给面板备料的两个新帧**

- `core/military.py:1031` `_march_frame()` → `{tile, owner, reason, cap, daily_budget, rows[]}`，每行 `{army_id, strength, from, reachable, days, cost, expedition, reason, cost_needed, days_needed}`，按 `(不可达, 天数, -兵力, 军队 id)` 排序。
- `core/military.py:1089` `_field_frames()` → 每一个「在本格驻军、但本格不属它」的国家出一帧 `{target, target_name, at_war, field, reason, armies, strength, power, strikes[]}`；`strikes` 行的字段和 `payload["strikes"]` 对齐（`can_attack` 靠 `hex_distance<=1`，否则用 `core/military.py:634` `_approach_to()` 找集结点）。
- 两者都在 `core/military.py:890` `tile_strikes()` 的 `NO_OWNER` / `OWN_TERRITORY` 提前返回**之前**算好——否则点一格空地就什么帧都拿不到，这正是 v0.42 的原始症状。

**溃退（v0.41）**

- `_rout_frame()`（报价，`core/military.py:230`）与 `_apply_rout()`（结算，`:330`）分开，面板上的「预计溃散」和实际发生的走同一本账。

## 四、AI 会用

- `agents/heuristic.py:215` `_strike_choice()` 现在返回 `objective` 与 `companion_objective`（`:264-278`）；`:281` 新增 `_strike_action(target, army_id, objective)`，只在报价真的带 objective 时才往命令里塞 `tile`。`:386`、`:397` 两处进攻都改走它。
- `agents/llm_adapter.py` 提示词教了四件事：ATTACK 协议元组里可选的 `tile`（:180、:207）、行军只落己方或无主地 + 踩别国领土每格多付 `rules.movement.hostile_cost` + `ORDER_LIMIT` 就分段（:185-191）、`objective` 与 `march_target` 不是一回事（:192-193）、对着野地营帐打的是野战（:207-209）；围城路线的措辞在 :218，保留了「只走己方或无主地」这个子串。

## 五、UI 显示（`dashboard.html`）

- `:1186` `marchBreakdown()` 把边境附加费算进逐格成本明细。
- `:2128` `hostilePaceText()` / `:2132` `MARCH_REFUSALS` / `:2137` `marchRowLine()` / `:2143` `marchRowButton()` / `:2148` `tileMarchCard()`：这就是 v0.42 要的「点任意一格 → 弹行军至此 → 在卡片里选军队」，逐支待命军队报天数、成本、是否远征，走不到的直接说原因（包括「这一格要 X 点 / Y 天，上限 Z 点——先在中途驻一脚，再下第二段令」）。
- `:2168` `fieldStrikeRow()` / `:2181` `fieldFrameCard()` / `:2197` `tileFieldCard()`：野战卡片，写清楚「营盘扎在谁的土地上、这一格并不属它」「打赢只歼其军、边界不动」，未交战时给一枚宣战按钮。
- `:1862` `STRIKE_NOTES` 重写（`NO_OWNER` 不再谎报「无需攻打」，补了 `FOREIGN_GROUND` / `SEA`）。
- 地块卡接线 `:2410`、`:2412`；三个处理器 `:2434`（MARCH）、`:2439`（带 tile 的 ATTACK）、`:2445`（DECLARE_WAR），各自 `.then(repriceTile)` 下完令立刻重报价。
- 教令文案改口：`:4348`、`:4359`、`:4456`（「别国领土只是减速，不是墙」）、`:4686-4692`、`:4721`、`:4728`。

## 六、测试与验证

跑法：`C:/Users/ROG/venvs/eos/Scripts/python.exe -m pytest -q --basetemp=.tmp_pytest`（仓库不带 `.venv`，别建）。

- **316 通过 / 6 失败**（总数 322，和 README 说的那个数字对得上，但「全绿」已经不成立了，见下一节）。
- 这一批新增/大改的测试文件：`test_march_movement.py`(370)、`test_tile_strikes.py`(452)、`test_mass_battle.py`(484)、`test_siege.py`(925)、`test_border_alerts.py`(371)、`test_capture_tribute.py`(362)、`test_recruit_receipts.py`(428)、`test_military_units.py`(360)、`test_march_balance.py`(208)、`test_dashboard_ui.py`(186)、`test_mapgen_custom.py`(385)。
- 手工端到端验证过一场真实的 17 天野战结算：`field=True`、战后边界一格未变、双方战损与卡片预报价一致。（验证用的探针脚本按约定已删，未入库。）
- `output/world_2000BCE.json` 未被改动；diff 里不含任何密钥。

---

## 七、还没修的问题（照着这个清单接手）

### 7.1 六个红灯测试：还钉在已经删掉的「走廊」教义上

这六个是本批刻意留下的（决定：什么都不补，先推）。**失败原因是测试写的是旧规则，不是引擎坏了**——别去改引擎迁就它们。

| # | 测试 | 为什么红 | 怎么修 |
| --- | --- | --- | --- |
| 1 | `tests/test_march_movement.py:47-58` `farthest_walkable_tile()` | helper 还在调**已经不存在**的 `engine.military._corridor(country_id, engine.military._owners())`（`:53`）。它有 4 个调用方：`:153`、`:184`、`:312`、`:340`，一处报错连环拖垮下面第 1/2/4/5 号测试 | 改成用 `_road(actor, start, target, explain=True)` 或直接取最远的可达格。**先修这一条**，一次救活 4 条 |
| 2 | `tests/test_march_movement.py:148` `test_march_order_queues_and_walks_the_route_one_budget_per_day` | 只被 helper 带倒 | 逐日推进的语义本批没动，helper 修好后应随之一绿（其余断言仍需对照新成本表核一遍） |
| 3 | `tests/test_march_movement.py:179` `test_a_march_is_cancelled_when_the_corridor_turns_hostile` | **前提被本批推翻**：`march_daily` 现在故意不再因为沿途易主而取消命令。这条除了 helper 还断言旧行为 | 删掉，或改成反向断言「沿途易主后命令照旧推进、不取消」 |
| 4 | `tests/test_march_movement.py:282` `test_an_expedition_is_priced_but_never_walked` | 断言了已删除的文案字面量「行军线沿途有格子易主，军队就地停下」。同样是旧教义：远征现在**真的会走**，只是又慢又打折 | 改成「远征照旧走完，但抵达战力打折 `expedition_factor`」 |
| 5 | `tests/test_march_movement.py:307` `test_a_march_in_progress_survives_a_save_and_resumes_where_it_stopped` | 只被 helper 带倒 | 存档往返语义未变，helper 修好后应随之转绿 |
| 6 | `tests/test_march_movement.py:336` `test_the_summary_publishes_what_the_march_panel_draws` | 只被 helper 带倒 | helper 修好后**还要看 `:352`**：那条硬断 `march["expedition"] is False`，而新规则下最远可达格的路线很可能踩到别国领土 → 让它跟着实际路线走，别硬掰引擎 |
| 7 | `tests/test_siege.py:911` `test_the_prompt_and_the_panel_both_offer_the_march` | `:910` 断言面板含字面量「只走己方与无主地」，`dashboard.html` 这句话已改口（现文案见 `:4456`） | 换成仍存在的语义串 |

- 注意：`tests/test_siege.py:924` 断言的是 **AI 提示词**里的「只走己方或无主地」，那条**是绿的**——提示词里这个子串是被有意保留的（MARCH 落点规则确实还是这句话）。别顺手把它一起改了。
- 上表编号 1 是 helper 本身，不是测试；实际红灯 = 2..7 共 6 条。

### 7.2 缺一份溃退（v0.41）的测试文件

`tests/` 里**没有** `test_rout_retreat.py`。v0.41 的 `_rout_frame` / `_apply_rout` 目前只被别的文件的断言顺带覆盖。至少该钉住：幸存者比例 0.4、`retreat_radius` 内的落点选择、营帐易主时 `barracks_lost_survivor_rate`（当前 0.0）的行为、以及「报价帧」和「结算结果」两边数字一致。

### 7.3 文档落后于代码

- `README.md:3` 状态行还写着「**322 项 pytest 全绿**」。实际是 316 绿 6 红。这句话是最先该改的。
- `README.md:165` 那行「测试总数 322」同样需要跟着实际情况更新。
- README 里**完全没有** v0.41 / v0.42 / v0.43 三个版本的章节（现有版本记录停在更早的批次）。
- `DEVELOPER_MANUAL.md` 是**「写了但写的是旧教义」**，比没写更容易误导人：
  - `:576` 说「单条命令上限 `maximum_order_cost`：超过就 `NO_PATH` 拒绝」——现在超上限报的是 `ORDER_LIMIT`（带真实成本与天数，且明说可以分段），根本走不到的才叫 `NO_LAND_LINK` / `ENCLAVED`。`NO_PATH` 这个码在本批之后已经不是行军回执了。
  - 同一行还在讲「通道只允许己方或无主陆地；必须穿过敌国领土时改判为远征」——这正是本批删掉的走廊教义。现在的规则是**别国领土穿得过去，只是每格多付 `hostile_cost`**；「只走己方或无主地」降级成了 MARCH 令的**落点**限制（`_marchable`），不再是沿途限制。
  - `:1280` 的 `movement` 表列了 `daily_budget` / `road_cost` / `maximum_order_cost` / `biome_cost`，**少了 `hostile_cost`**。
  - `:1597` 那段历史观察里还写着「远超 24 点的 `movement.maximum_order_cost`」——现在这个值是 60，需要说明那是当时的取值。
  - 结算结果里新增的 `field=true`（野战、不夺地）、`tile_strikes` 新增的 `march` / `field` 两种帧、以及 `FOREIGN_GROUND` 回执码，手册一个字都没提。
- `PROJECT_EOS_DEVELOPMENT_REPORT.md` 顶部汇总行也没跟上。

### 7.4 已知的小缺口（不红，但行为不完美）

- **画笔预览读不到边境加价**：`/api/setup` 的草稿数据里没有 `hostile_cost`，`march_preview` 只按地形 + 道路报价。所以手绘世界时看到的行军预览价，和游戏里真实结算价会差一层边境附加费。引擎侧是对的，缺的是那条预览链路。
- **`march_target` 可能落在第三国**：`_camp_map` / `_staging_map` 为野战挑的集结格，有可能是**第三个国家**的领土。真下 MARCH 令时会被 `FOREIGN_GROUND` 拒（走 ATTACK 不受影响，因为进攻令什么地都能落）。要么让这两个函数只在己方/无主地里挑集结格，要么在面板上提前标出来。
- 面板的野战卡片在 `at_war=False` 时只提供宣战按钮，不提供「先派过去等着」——属于设计选择，不是 bug，但值得记一笔。

### 7.5 故意没决定的事：远征行军的平衡

已知缺陷**刻意保留**，因为两种修法都会改动战争强度，不该由改代码的人顺手定：

1. 让远征更贵（加大 `hostile_cost` 或远征折扣），代价是边境拉锯几乎打不起来；
2. 维持成本、只削抵达战力（调低 `expedition_factor`），代价是长距离奇袭仍然一刀致命。

现在 0.78 / 1.25 这组值是「能玩、没验算过长期」的状态。要动它，先用 `run_march_balance.py` 跑一轮，别裸改。

### 7.6 其他挂账

- `peace_war_cooldown_days`（打完仗不能立刻再宣战）从 v0.40 挂到现在，没做。
- 长期平衡 `run_march_balance.py`（735 行，本批入库）**这一轮没有重跑**。用户明确说过手抄版够用，所以报告里没有新的长期曲线。

---

## 八、给接手人的三条注意事项

1. **别为绿灯改引擎。** 6 条红灯全部是测试在断言已被推翻的旧教义（详见 7.1）。先改测试，改完再跑全量确认没引入新红。
2. **`maximum_order_cost` 是承重的。** 面板 5 处读它来印「上限 X 点，超了分段下令」，`tests/test_march_balance.py:178`/`:202` 直接改写和回读它，`core/content.py` 则要求它 > `road_cost + hostile_cost`。改这个数等于改行军教义，不是改一个常量。
3. **`output/world_2000BCE.json` 不许重新生成**，密钥只走环境变量或本地文件、不进 JSON / 日志 / 提交。
