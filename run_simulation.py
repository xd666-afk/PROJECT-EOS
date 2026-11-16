"""Monthly game CLI, with an explicit legacy daily mode for analysis tools."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shlex

from agents.llm_adapter import CallBudget, load_agents
from agents.scheduler import AgentScheduler
from core.simulation import Simulation
from core.state import DEFAULT_RULES, DEFAULT_WORLD
from core import monthly


def configure_models(simulation: Simulation, args: argparse.Namespace) -> CallBudget:
    budget = CallBudget(args.max_calls, args.max_cost_usd)
    if args.models and not args.no_agents:
        scheduler = AgentScheduler(load_agents(args.models, budget))
        simulation.scheduler = scheduler
        simulation.engine.planner = scheduler
    return budget


def print_status(simulation: Simulation) -> None:
    summary = simulation.state.summary()
    is_monthly=simulation.state.time_unit=='month'
    print(f"\n游戏月 {monthly.month_index(simulation.state.day_index)+1} · {monthly.month_label(simulation.state.day_index,simulation.state.start_astronomical_year)}" if is_monthly else f"\n游戏日 {summary['day']} · {summary['date']}")
    print("国家       人口      粮食      财政      政策          研究             建筑/在建  缺粮月" if is_monthly else "国家       人口      粮食      财政      政策          研究             建筑/在建  缺粮日")
    print("-" * 92)
    for country_id, country in summary["countries"].items():
        print(
            f"{country_id:<9} {country['population']:>7} "
            f"{country['food']:>9.2f} {country['treasury']:>9.2f} "
            f"{country['policy']:<13} {country['research_field']:<16} "
            f"{len(country['buildings'])}/{country['projects']:<5} "
            f"{len({monthly.month_index(e['day']) for e in simulation.state.event_log if e['type']=='food_shortage' and e.get('country_id')==country_id}) if is_monthly else country['shortage_days_total']:>6}"
        )
    accepted = sum(entry["result"]["accepted"] for entry in simulation.state.action_log)
    rejected = len(simulation.state.action_log) - accepted
    hazards = sum(event["type"] == "hazard_impact" for event in simulation.state.event_log)
    print(f"动作：接受 {accepted} / 拒绝 {rejected}；灾害影响事件：{hazards}；交易：{summary['trades']}")


def run_command(args: argparse.Namespace) -> int:
    if args.load:
        simulation = Simulation.load(args.load, args.world, use_mock_agents=not args.no_agents)
    else:
        simulation = Simulation.new(
            args.world or DEFAULT_WORLD, args.rules, args.seed, use_mock_agents=not args.no_agents
        )
    simulation.set_speed(args.speed)
    api_budget = configure_models(simulation, args)
    simulation.attach_jsonl(args.log, append=bool(args.load and Path(args.log).exists()))
    if args.days is None:
        return run_month_command(simulation,args,api_budget)
    start_day = simulation.state.day_index
    final_day = start_day + args.days
    snapshot_days = set(range(start_day, final_day + 1, 30))
    snapshot_days.update({start_day, 90, 180, 365, final_day})
    snapshots = [{"day": start_day, "state": deepcopy(simulation.state.summary())}]
    completed = 0
    try:
        for _ in range(args.days):
            stepped = simulation.run(
                1,
                real_time=args.real_time,
                force=args.force,
                autosave_path=args.save,
            )
            completed += stepped
            if not stepped:
                break
            if simulation.state.day_index in snapshot_days:
                snapshots.append({
                    "day": simulation.state.day_index,
                    "state": deepcopy(simulation.state.summary()),
                })
        simulation.state.save(args.save)
        Path(args.snapshots).parent.mkdir(parents=True, exist_ok=True)
        Path(args.snapshots).write_text(
            json.dumps({
                "start_day": start_day,
                "requested_days": args.days,
                "completed_days": completed,
                "final_fingerprint": simulation.state.fingerprint(),
                "snapshots": snapshots,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print_status(simulation)
        print(f"存档：{Path(args.save).resolve()}")
        print(f"日志：{Path(args.log).resolve()}")
        print(f"快照：{Path(args.snapshots).resolve()}")
        Path(args.api_usage).parent.mkdir(parents=True, exist_ok=True)
        Path(args.api_usage).write_text(
            json.dumps(api_budget.summary(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"API 用量：{Path(args.api_usage).resolve()} · {api_budget.summary()}")
    finally:
        simulation.close()
    return 0 if completed == args.days else 2


def run_month_command(simulation,args,budget):
    if args.months<0:raise ValueError('月份不能为负数')
    monthly.enable(simulation.state)
    snapshots=[{'month_number':monthly.calendar(simulation.state)['month_number'],'state':monthly.decorate(simulation.state.summary(),simulation.state)}]
    completed=0
    try:
        for _ in range(args.months):
            count=simulation.run_months(1,force=args.force,real_time=args.real_time,autosave_path=args.save)
            completed+=count
            if not count:break
            snapshots.append({'month_number':monthly.calendar(simulation.state)['month_number'],'state':monthly.decorate(simulation.state.summary(),simulation.state)})
        simulation.state.save(args.save)
        Path(args.snapshots).parent.mkdir(parents=True,exist_ok=True)
        Path(args.snapshots).write_text(json.dumps({'time_unit':'month','requested_months':args.months,'completed_months':completed,
            'final_fingerprint':simulation.state.fingerprint(),'snapshots':snapshots},ensure_ascii=False,indent=2),encoding='utf-8')
        Path(args.api_usage).parent.mkdir(parents=True,exist_ok=True)
        Path(args.api_usage).write_text(json.dumps(budget.summary(),ensure_ascii=False,indent=2),encoding='utf-8')
        print_status(simulation)
        print(f'已推进 {completed} 个月；存档：{Path(args.save).resolve()}')
    finally:simulation.close()
    return 0 if completed==args.months else 2


def status_command(args: argparse.Namespace) -> int:
    simulation = Simulation.load(args.save, args.world, use_mock_agents=False)
    print_status(simulation)
    return 0


def interactive_command(args: argparse.Namespace) -> int:
    if args.load:
        simulation = Simulation.load(args.load, args.world)
    else:
        simulation = Simulation.new(args.world or DEFAULT_WORLD, args.rules, args.seed)
    monthly.enable(simulation.state)
    print("命令：pause | resume | step [月] | ff 月 | run 月 | speed 每秒月数 | status | save [路径] | quit")
    print_status(simulation)
    try:
        while True:
            try:
                parts = shlex.split(input("eos> ").strip())
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not parts:
                continue
            command, *arguments = parts
            try:
                if command in {"quit", "exit"}:
                    break
                if command == "pause":
                    simulation.pause()
                    print("已暂停；step 可在暂停时精确推进。")
                elif command == "resume":
                    simulation.resume()
                    print("已继续。")
                elif command == "step":
                    count = int(arguments[0]) if arguments else 1
                    print(f"已推进 {simulation.step_months(count)} 个游戏月。")
                    print_status(simulation)
                elif command == "ff":
                    print(f"已快进 {simulation.step_months(int(arguments[0]))} 个游戏月。")
                    print_status(simulation)
                elif command == "run":
                    count = int(arguments[0])
                    print(f"已实时推进 {simulation.run_months(count, real_time=True)} 个游戏月。")
                    print_status(simulation)
                elif command == "speed":
                    simulation.set_speed(float(arguments[0]))
                    print(f"速度：{simulation.clock.ticks_per_second} 游戏月/现实秒。")
                elif command == "status":
                    print_status(simulation)
                elif command == "save":
                    destination = arguments[0] if arguments else args.save
                    simulation.state.save(destination)
                    print(f"已保存：{Path(destination).resolve()}")
                else:
                    print("未知命令。")
            except (ValueError, IndexError) as exc:
                print(f"命令错误：{exc}")
    finally:
        simulation.state.save(args.save)
        simulation.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project Eos deterministic country simulator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="推进模拟并写出存档、日志和快照")
    run.add_argument("--world", type=Path, default=None)
    run.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    run.add_argument("--load", type=Path)
    period=run.add_mutually_exclusive_group()
    period.add_argument("--months", type=int, default=12)
    period.add_argument("--days", type=int, default=None, help='旧制分析工具兼容参数；游戏使用 --months')
    run.add_argument("--seed", type=int, default=2000)
    run.add_argument("--speed", type=float, default=1.0, help="现实每秒推进的游戏月数")
    run.add_argument("--real-time", action="store_true", help="按 speed 实时 pacing；默认无等待快进")
    run.add_argument("--force", action="store_true", help="即使暂停也强制快进")
    run.add_argument("--no-agents", action="store_true")
    run.add_argument("--models", type=Path, help="每国 Mock/OpenAI 兼容模型配置 JSON")
    run.add_argument("--max-calls", type=int, default=None, help="本次实验最大 HTTP 调用尝试数")
    run.add_argument("--max-cost-usd", type=float, default=None, help="本次实验已知估算费用上限")
    run.add_argument("--save", type=Path, default=Path("runs/eos_latest.json"))
    run.add_argument("--log", type=Path, default=Path("runs/eos_latest.jsonl"))
    run.add_argument("--snapshots", type=Path, default=Path("runs/eos_latest_snapshots.json"))
    run.add_argument("--api-usage", type=Path, default=Path("runs/eos_api_usage.json"))
    run.set_defaults(handler=run_command)

    status = subparsers.add_parser("status", help="读取动态存档并显示状态")
    status.add_argument("--save", type=Path, default=Path("runs/eos_latest.json"))
    status.add_argument("--world", type=Path, default=None)
    status.set_defaults(handler=status_command)

    interactive = subparsers.add_parser("interactive", help="交互式暂停、继续、单步和倍速")
    interactive.add_argument("--world", type=Path, default=None)
    interactive.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    interactive.add_argument("--load", type=Path)
    interactive.add_argument("--seed", type=int, default=2000)
    interactive.add_argument("--save", type=Path, default=Path("runs/eos_interactive.json"))
    interactive.set_defaults(handler=interactive_command)
    return parser


if __name__ == "__main__":
    arguments = build_parser().parse_args()
    raise SystemExit(arguments.handler(arguments))
