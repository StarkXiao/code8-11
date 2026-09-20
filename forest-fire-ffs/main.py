#!/usr/bin/env python3
"""森林火险瞭望与卫星热点核查系统 —— 命令行入口。

用法：
  python3 main.py run       --data data --out out            运行融合派发流水线
  python3 main.py status    --db out/ffs.db                  查看事件与任务状态
  python3 main.py feedback  --db out/ffs.db --task T-0001 \
                            --result confirmed --note "..."  回传核查结论
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ffs.pipeline import run_pipeline  # noqa: E402
from ffs.store import Store  # noqa: E402

CST = timezone(timedelta(hours=8))  # 东八区


def cmd_run(args) -> int:
    summary = run_pipeline(args.data, args.db, args.out)
    print(f"输入：卫星热点 {summary['input']['satellite_hotspots']} 条，"
          f"塔台观测 {summary['input']['tower_observations']} 条")
    print(f"融合去重后事件 {summary['fused_events']} 起，"
          f"已派发核查任务 {summary['tasks_dispatched']} 项")
    if summary["unassigned_events"]:
        print(f"⚠ 护林员在办已满，未能派发：{', '.join(summary['unassigned_events'])}")
    print()
    print(f"{'事件':<7}{'优先级':<5}{'置信度':<8}{'FRP(MW)':<9}{'坐标':<24}{'任务':<8}{'执行人':<6}")
    task_by_event = {t["event_id"]: t for t in summary["tasks"]}
    for e in summary["events"]:
        t = task_by_event.get(e["event_id"], {})
        coord = f"({e['lat']:.4f}, {e['lon']:.4f})"
        print(f"{e['event_id']:<7}{e['priority']:<5}{e['confidence']:<8.0%}"
              f"{e['frp_max_mw']:<9.1f}{coord:<24}{t.get('task_id', '-'):<8}"
              f"{t.get('ranger_id', '-'):<6}")
    print(f"\n核查清单已输出至 {Path(args.out) / 'checklists'}/，汇总见 {Path(args.out) / 'summary.json'}")
    return 0


def cmd_status(args) -> int:
    store = Store(args.db)
    events = store.list_events()
    tasks = store.list_tasks()
    store.close()
    print(f"{'事件':<7}{'状态':<8}{'优先级':<5}{'置信度':<8}{'坐标'}")
    for e in events:
        print(f"{e['event_id']:<7}{e['status']:<8}{e['priority']:<5}"
              f"{e['confidence']:<8.0%}({e['lat']:.4f}, {e['lon']:.4f})")
    print()
    print(f"{'任务':<7}{'事件':<7}{'护林员':<7}{'状态':<8}{'结论':<10}{'备注'}")
    for t in tasks:
        print(f"{t['task_id']:<7}{t['event_id']:<7}{t['ranger_id']:<7}"
              f"{t['status']:<8}{(t['result'] or '-'):<10}{t['note'] or ''}")
    return 0


def cmd_feedback(args) -> int:
    store = Store(args.db)
    try:
        result = store.record_feedback(args.task, args.result, args.note,
                                       datetime.now(CST))
    except (KeyError, ValueError) as exc:
        store.close()
        print(f"反馈失败：{exc}", file=sys.stderr)
        return 1
    store.close()
    print(f"已记录：任务 {result['task_id']} → 事件 {result['event_id']} "
          f"状态更新为「{result['event_status']}」")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="森林火险瞭望与卫星热点核查系统")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="运行融合去重与派发流水线")
    p_run.add_argument("--data", default="data", help="数据目录")
    p_run.add_argument("--out", default="out", help="输出目录")
    p_run.add_argument("--db", default="out/ffs.db", help="SQLite 数据库路径")
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="查看事件与任务状态")
    p_status.add_argument("--db", default="out/ffs.db")
    p_status.set_defaults(func=cmd_status)

    p_fb = sub.add_parser("feedback", help="回传核查结论")
    p_fb.add_argument("--db", default="out/ffs.db")
    p_fb.add_argument("--task", required=True, help="任务编号，如 T-0001")
    p_fb.add_argument("--result", required=True,
                      choices=["confirmed", "false_alarm", "need_backup"],
                      help="confirmed=确认火情 false_alarm=误报 need_backup=需增援")
    p_fb.add_argument("--note", default="", help="现场备注")
    p_fb.set_defaults(func=cmd_feedback)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
