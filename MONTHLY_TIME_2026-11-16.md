# v0.53：按自然月推进

游戏的最小可操作时间改为月。保留实时演进、暂停和倍速；点击「+1 月」或运行一次时钟会结算到下个月月初，玩家不能停在月内下令。默认观察期限为 12 个月，可继续延长一年。

## 玩家看到的变化

- 日期显示到月份，建设、道路、科研、行军、外交期限和事态持续时间统一以月呈现。有剩余工作的预计工期至少 1 个月；没有建设劳力时显示「工期暂停」。道路工期考虑队列、劳力、政策和事态修正。
- 每个国家 AI 每月议事一次，城市自动治理和边疆选点也在月初处理；月内不再因日警报追加国家议事。LLM 观察提供月历和月账，动作协议中的 `world_day` 继续作为兼容身份索引，必须原样返回。
- 财政页展示刚结束月份的真实累计收入、支出和粮食流量，标明账期；首次未结算时标为估算。军队维护记录实际支付额，单次招募、外交交易等仍见原有回执，不计入民政结余。城市粮食可供时长按月需求计算。
- 观众事件默认持续 3 个月，允许 1–24 个整数月；可调整强度和剩余月数。多个事态独立推进，焦点仍只有玩家选中的一个。进度条、历史和结束编年以月呈现，阶段仍取自实际行动与结果。
- 月结算时单步按钮显示「结算中」，阻止重复点击。三级菜单和地图优先布局延续 v0.51，卫星国界和控制区延续 v0.52。

## 旧存档

不重开世界、不重放已结算进度。旧档若位于月中，首次推进完成该月余期，再进入完整自然月；首份月账标为「旧档首月余期」。旧事态的剩余时间向上对齐到可观察的月边界，迁移记录保留原截止时间。原始导入文件保持不变，新时间制进入本机存档槽。

存档新增 `time_unit` 与 `monthly_ledger`。月账包含账期、起止游标、实际结算次数、国家流量与城市流量；天气随机状态继续随存档保存。月度动作回放按原顺序处理迁移、月初、指令和结算，重建月账。

## 工程接口

`core/monthly.py` 负责自然月历、月工期、累计账目、迁移和公开月度字段；`RuleEngine.step_month()` 是正式结算入口，`Simulation.run_months()/step_months()` 供服务器与命令行使用。现有无闰年历法保持 31/28/31 等月长，一年 365 日。

天气、资源、行军、围城和建设在月事务内部沿用确定性的细分积分，保留既有平衡与旧档精度。整个事务持有会话锁，对外只暴露完整结算结果。异常（包括中断）回退世界状态、时钟、随机状态和新增日志；监听器在月提交后才收到事件。已发出的模型 HTTP 请求及其费用不属于本地状态回退范围。

公开 JSON 增加 `calendar`、`months_left`、`estimated_months`、`remaining_months`、`month_number`、`monthly_economy` 等明确月度字段；旧日字段保留兼容含义，不能当作月字段直接使用。`assets/ui/monthly.js` 统一适配现有视图。`/api/control` 的 `step_month` 和兼容的 `step` 均推进一个月，不能通过后者推进一天。

事态接口示例：

```json
{"operation":"create","event":{"preset_id":"drought","country_id":"A","duration_months":3,"intensity":2}}
```

```json
{"operation":"update","id":"事态ID","changes":{"remaining_months":2,"intensity":1}}
```

公共事态接口拒绝旧的 `duration` / `remaining_days` 请求，防止单位混淆。保存与回放内部仍使用精确游标。

```powershell
.venv/Scripts/python live_server.py --load examples/civil_networks/save.json --months 12 --speed 1 --paused --open
.venv/Scripts/python run_simulation.py run --months 12 --save runs/monthly.json
.venv/Scripts/python run_simulation.py interactive --load runs/monthly.json
```

交互命令 `step [月]`、`ff 月`、`run 月`、`speed 每秒月数`；`--speed 1` 表示每现实秒最多推进一个游戏月，计算耗时另计。旧 `Simulation.step/run/fast_forward`、`RuleEngine.step_day` 与显式 `run --days` 仅供分析、旧测试和回放，不是玩家游戏入口。

## 验证

`tests/test_monthly.py` 的 21 项用例覆盖自然月长、旧档余期、实际累计账目、每月一次议事、月期限、保存续演、动作回放、劳力工期、异常回退、并发读取隔离及 CLI 旧档地图载入。完整 pytest：443 项通过。

四国 Mock 从旧档完整续演 12 个月：48 次国家议事、12 次月结算、125 条接受动作和 1 条拒绝动作；回放与最终存档状态指纹一致。旧科技制存档的遗留研究点在迁移记录中保留，回放不丢弃兼容字段。

浏览器验收：

```powershell
.venv/Scripts/python scripts/verify_monthly_ui.py --output docs/report_assets/monthly_v053
.venv/Scripts/python scripts/verify_situations_ui.py --output runs/ui_checks/monthly_situations
.venv/Scripts/python scripts/verify_strategy_ui.py --output runs/ui_checks/monthly_strategy
```

独立临时存档验证：旧档一月 → 二月 → 三月、两个月事件准时结束、月报价行军真实到达、月账与 API 一致、主要面板无日单位泄漏、桌面与手机时间按钮可用。预览截图和验收结果见 `docs/report_assets/monthly_v053/`。现有战略及事态脚本继续验证真实治理命令与三级导航，不使用玩家存档。
