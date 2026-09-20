"""派发引擎：定优先级、就近派单、生成核查清单。"""
from __future__ import annotations

from datetime import datetime, timedelta

from .geo import haversine_m
from .models import ChecklistItem, FireEvent, Ranger, VerificationTask

# ---- 可调参数 -------------------------------------------------------------
DEADLINE_HOURS = {"P1": 2, "P2": 4, "P3": 8}   # 各级任务的核查时限
AVG_SPEED_KMH = 25.0                            # 山区车+徒步综合平均速度
P1_CONFIDENCE = 0.80
P2_CONFIDENCE = 0.50
P1_FRP_MW = 50.0
P2_FRP_MW = 10.0


def assign_priority(event: FireEvent) -> str:
    """按置信度与火点辐射功率分级：P1 最紧急。"""
    if event.confidence >= P1_CONFIDENCE or event.frp_max_mw >= P1_FRP_MW:
        return "P1"
    if event.confidence >= P2_CONFIDENCE or event.frp_max_mw >= P2_FRP_MW:
        return "P2"
    return "P3"


def build_checklist(event: FireEvent) -> list[ChecklistItem]:
    """生成标准化核查清单，并按事件特征追加针对性条目。"""
    items = [
        f"规划路线，安全抵达核查坐标（{event.lat:.5f}, {event.lon:.5f}，定位误差约 {event.uncertainty_m:.0f} m）",
        "现场瞭望：确认有无烟柱 / 明火 / 炭化痕迹，记录其方位与距离",
        "拍照取证：全景、近景各不少于 2 张（开启 GPS 水印）",
        "记录植被类型、可燃物载量、坡度坡向",
        "观测风向风速，判断可能蔓延方向",
        "评估周边威胁：居民点、输电线路、景区设施的距离",
        "通过系统上报核查结论（确认火情 / 误报 / 需增援）",
    ]
    if event.frp_max_mw >= P1_FRP_MW:
        items.append(f"热点辐射功率较高（{event.frp_max_mw:.0f} MW），警惕树冠火，保持安全距离")
    if event.confidence < 0.60:
        items.append("该事件置信度偏低，可能为农事用火 / 云影等误报，注意甄别")
    items.append("安全提示：保持通信畅通，火势突变立即撤至安全区并拨打 12119")
    return [ChecklistItem(item_id=f"C{k + 1}", text=t, required=(k < 7)) for k, t in enumerate(items)]


def dispatch_events(
    events: list[FireEvent],
    rangers: list[Ranger],
    now: datetime,
) -> tuple[list[VerificationTask], list[FireEvent]]:
    """按（优先级, 置信度, 最新发现时间）排序派单；护林员就近且不超过在办上限。

    返回 (任务列表, 未能派发的事件列表)。
    """
    for event in events:
        event.priority = assign_priority(event)
    rank = {"P1": 0, "P2": 1, "P3": 2}
    ordered = sorted(events, key=lambda e: (rank.get(e.priority, 3), -e.confidence, e.last_detected))
    load = {r.ranger_id: 0 for r in rangers}
    tasks: list[VerificationTask] = []
    unassigned: list[FireEvent] = []

    for event in ordered:
        available = [r for r in rangers if load[r.ranger_id] < r.max_tasks]
        if not available:
            unassigned.append(event)
            continue
        nearest = min(available, key=lambda r: haversine_m(r.lat, r.lon, event.lat, event.lon))
        dist = haversine_m(nearest.lat, nearest.lon, event.lat, event.lon)
        eta_min = dist / 1000.0 / AVG_SPEED_KMH * 60.0
        load[nearest.ranger_id] += 1
        tasks.append(VerificationTask(
            task_id=f"T-{len(tasks) + 1:04d}",
            event_id=event.event_id,
            ranger_id=nearest.ranger_id,
            priority=event.priority,
            issued_at=now,
            deadline=now + timedelta(hours=DEADLINE_HOURS[event.priority]),
            distance_m=dist,
            eta_min=eta_min,
            checklist=build_checklist(event),
        ))
    return tasks, unassigned
