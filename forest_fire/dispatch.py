"""核查任务派发：按风险优先级、责任区覆盖与负载均衡分配护林员。"""
from __future__ import annotations

from datetime import datetime, timedelta

from .geo import haversine_km
from .models import FireEvent, Ranger, RiskLevel, VerificationTask

# 各风险等级的核查时限（自派发时刻起，小时）
DEADLINE_HOURS = {RiskLevel.HIGH: 1, RiskLevel.MEDIUM: 2, RiskLevel.LOW: 4}

CHECKLIST_TEMPLATE = [
    "携带定位终端与对讲设备，按坐标 {lat:.5f}, {lon:.5f} 导航至现场",
    "确认热点性质（明火 / 阴燃 / 非火情：农事用火、工业热源、云影误报等）",
    "拍摄东、南、西、北四方位现场照片并回传",
    "记录植被类型、估计过火面积、现场风向风速",
    "评估蔓延风险，必要时立即请求增援",
    "在时限内通过终端回传核查结论",
]

_PRIORITY_ORDER = {RiskLevel.HIGH: 0, RiskLevel.MEDIUM: 1, RiskLevel.LOW: 2}


def dispatch_events(
    events: list[FireEvent],
    rangers: list[Ranger],
    now: datetime | None = None,
) -> list[VerificationTask]:
    """把火情事件派发给护林员。

    派发顺序：高风险优先，同级按首见时间。选人规则：责任区内 →
    负载最轻 → 距离最近；无人覆盖时就近跨区支援并标记。
    """
    now = now or datetime.now()
    load = {r.ranger_id: 0 for r in rangers}
    tasks: list[VerificationTask] = []

    ordered = sorted(events, key=lambda e: (_PRIORITY_ORDER[e.risk], e.first_seen))
    for seq, event in enumerate(ordered, 1):
        available = [r for r in rangers if load[r.ranger_id] < r.max_tasks]
        if not available:
            break  # 全员满负荷；生产系统应转入排队并向上级告警

        in_area = [r for r in available
                   if haversine_km(event.lat, event.lon, r.lat, r.lon) <= r.jurisdiction_km]
        pool = in_area or available
        chosen = min(pool, key=lambda r: (load[r.ranger_id],
                                          haversine_km(event.lat, event.lon, r.lat, r.lon)))
        load[chosen.ranger_id] += 1
        tasks.append(VerificationTask(
            task_id=f"RW-{now:%Y%m%d}-{seq:03d}",
            event=event,
            ranger=chosen,
            priority=event.risk,
            issued_at=now,
            deadline=now + timedelta(hours=DEADLINE_HOURS[event.risk]),
            cross_region=chosen not in in_area,
            checklist=[item.format(lat=event.lat, lon=event.lon) for item in CHECKLIST_TEMPLATE],
        ))
    return tasks
