#!/usr/bin/env python3
"""森林火险瞭望与卫星热点核查系统 —— 端到端演示。

数据流：
    瞭望塔台观测 ─┐
                 ├─→ 归一化 → 时空去重融合 → 风险定级 → 派发核查清单 → 护林员
    卫星红外热点 ─┘

运行：python3 main.py          （可加 --json result.json 导出结果）
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime

from forest_fire.dispatch import dispatch_events
from forest_fire.fusion import (
    fuse_detections,
    hotspot_to_detection,
    observation_to_detection,
)
from forest_fire.geo import haversine_km
from forest_fire.models import (
    Ranger,
    SatelliteHotspot,
    SourceType,
    Tower,
    TowerObservation,
)

NOW = datetime(2026, 9, 20, 10, 30)  # 演示场景时刻

# ---------------------------------------------------------------- 演示数据
# 场景：云岭林区（虚构）。红松洼发生真实火情——两颗卫星三次过顶、两座瞭望塔
# 同时观测到；老里克湖一处烟点由卫星与塔台各报一次；东侧另有一个低置信孤立
# 热点（疑似工业热源）。共 8 条原始报告，去重后应为 3 个事件。

TOWERS = [
    Tower("T01", "北岭瞭望塔", 42.150, 127.860, 980),
    Tower("T02", "青峰瞭望塔", 42.060, 127.940, 1120),
    Tower("T03", "南沟瞭望塔", 42.020, 127.800, 860),
]

RANGERS = [
    Ranger("R01", "王海峰", "北岭管护站", 42.140, 127.830, phone="139-0433-0121"),
    Ranger("R02", "李秀兰", "青峰管护站", 42.070, 127.970, phone="139-0433-0122"),
    Ranger("R03", "张建国", "南沟管护站", 42.000, 127.820, phone="139-0433-0123"),
    Ranger("R04", "赵敏", "机动巡护队", 42.100, 127.900, phone="139-0433-0124",
           jurisdiction_km=40.0),
]

TOWER_OBSERVATIONS = [
    # 两座塔台观测同一火点（红松洼）：方位角/距离为人工估测，含合理误差
    TowerObservation("OB-001", "T01", datetime(2026, 9, 20, 9, 12),
                     azimuth_deg=141.2, distance_km=6.9, smoke_color="灰白",
                     notes="烟柱稳定，风向西北"),
    TowerObservation("OB-002", "T02", datetime(2026, 9, 20, 9, 15),
                     azimuth_deg=328.5, distance_km=5.2, smoke_color="灰黑",
                     notes="烟量增大"),
    # 南沟塔台观测老里克湖烟点
    TowerObservation("OB-003", "T03", datetime(2026, 9, 20, 9, 48),
                     azimuth_deg=355.3, distance_km=18.4, smoke_color="白",
                     notes="断续轻烟"),
]

SATELLITE_HOTSPOTS = [
    # 红松洼火点：三颗卫星三次过顶（同一火情的重复报告）
    SatelliteHotspot("HS-001", "Suomi-NPP/VIIRS", datetime(2026, 9, 20, 9, 5),
                     42.1018, 127.9048, frp=62.4, confidence=95, brightness_k=341.2),
    SatelliteHotspot("HS-002", "NOAA-20/VIIRS", datetime(2026, 9, 20, 9, 40),
                     42.1025, 127.9056, frp=71.8, confidence=98, brightness_k=352.6),
    SatelliteHotspot("HS-003", "Aqua/MODIS", datetime(2026, 9, 20, 10, 20),
                     42.1011, 127.9039, frp=55.1, confidence=90, brightness_k=335.8),
    # 老里克湖烟点
    SatelliteHotspot("HS-004", "Suomi-NPP/VIIRS", datetime(2026, 9, 20, 9, 5),
                     42.1803, 127.7795, frp=24.3, confidence=60, brightness_k=318.4),
    # 东侧孤立低置信热点（疑似工业热源/误报）
    SatelliteHotspot("HS-005", "Suomi-NPP/VIIRS", datetime(2026, 9, 20, 9, 5),
                     42.0498, 128.0512, frp=6.2, confidence=20, brightness_k=305.1),
]

SOURCE_LABEL = {SourceType.TOWER: "塔台", SourceType.SATELLITE: "卫星"}


def build_detections():
    towers = {t.tower_id: t for t in TOWERS}
    detections = []
    for obs in TOWER_OBSERVATIONS:
        det = observation_to_detection(obs, towers[obs.tower_id])
        if det is not None:
            detections.append(det)
    detections.extend(hotspot_to_detection(h) for h in SATELLITE_HOTSPOTS)
    return detections


def print_report(detections, events, tasks, spatial_km, temporal_hours):
    w = 64
    print("=" * w)
    print("  森林火险瞭望与卫星热点核查系统 · 核查派发单")
    print(f"  生成时间：{NOW:%Y-%m-%d %H:%M}")
    print("=" * w)

    n_tower = sum(1 for d in detections if d.source_type is SourceType.TOWER)
    n_sat = len(detections) - n_tower
    print(f"\n【输入】塔台观测 {n_tower} 条 · 卫星热点 {n_sat} 条，共 {len(detections)} 条探测")
    print(f"【去重】融合为 {len(events)} 个火情事件"
          f"（空间阈值 {spatial_km}km，时间窗口 {temporal_hours}h）\n")

    for ev in events:
        src = " + ".join(sorted({SOURCE_LABEL[s] for s in ev.sources}))
        print(f"  事件 {ev.event_id} ｜ 风险：{ev.risk.value}（评分 {ev.risk_score}）"
              f" ｜ 位置 {ev.lat:.5f}, {ev.lon:.5f}")
        print(f"    来源：{src}，共 {len(ev.detections)} 次探测 ｜ "
              f"首见 {ev.first_seen:%H:%M} ｜ 末见 {ev.last_seen:%H:%M}")
        for d in ev.detections:
            print(f"      · [{SOURCE_LABEL[d.source_type]}] {d.source_id}：{d.detail}")
        print()

    print("【派发】护林员核查清单")
    print("-" * w)
    for task in tasks:
        ev = task.event
        r = task.ranger
        dist = haversine_km(ev.lat, ev.lon, r.lat, r.lon)
        tag = " ［跨区支援］" if task.cross_region else ""
        print(f"  {task.task_id} → {r.name}（{r.station}，{r.phone}）{tag}")
        print(f"    事件 {ev.event_id} @ {ev.lat:.5f}, {ev.lon:.5f} ｜ 距驻地 {dist:.1f}km")
        print(f"    优先级：{task.priority.value} ｜ 派发 {task.issued_at:%H:%M} ｜ "
              f"核查时限：{task.deadline:%H:%M} 前回传")
        for i, item in enumerate(task.checklist, 1):
            print(f"      {i}. {item}")
        print()
    if len(tasks) < len(events):
        print(f"  ⚠ 有 {len(events) - len(tasks)} 个事件因护林员满负荷暂未派发，"
              f"请上级调度增援。")
    print("=" * w)


def main():
    parser = argparse.ArgumentParser(description="森林火险瞭望与卫星热点核查系统")
    parser.add_argument("--spatial-km", type=float, default=2.0,
                        help="去重空间阈值（公里），默认 2.0")
    parser.add_argument("--temporal-hours", type=float, default=12.0,
                        help="去重时间窗口（小时），默认 12")
    parser.add_argument("--json", metavar="PATH", help="将派发结果导出为 JSON 文件")
    args = parser.parse_args()

    detections = build_detections()
    events = fuse_detections(detections, args.spatial_km, args.temporal_hours)
    tasks = dispatch_events(events, RANGERS, now=NOW)

    print_report(detections, events, tasks, args.spatial_km, args.temporal_hours)

    if args.json:
        payload = {
            "generated_at": NOW.isoformat(),
            "params": {"spatial_km": args.spatial_km, "temporal_hours": args.temporal_hours},
            "events": [asdict(e) for e in events],
            "tasks": [asdict(t) for t in tasks],
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        print(f"结果已导出：{args.json}")


if __name__ == "__main__":
    main()
