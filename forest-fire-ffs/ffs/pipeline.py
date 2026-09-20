"""端到端流水线：加载数据 → 融合去重 → 分级派发 → 落库并输出核查清单。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .dispatch import dispatch_events
from .fusion import (
    fuse_candidates,
    hotspot_to_candidate,
    normalize_confidence,
    observation_to_candidate,
)
from .models import Ranger, SatelliteHotspot, Tower, TowerObservation
from .store import Store


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def load_data(data_dir: str | Path):
    """从目录加载 towers.json / tower_observations.json / satellite_hotspots.json / rangers.json。"""
    data_dir = Path(data_dir)

    towers = {t["tower_id"]: Tower(**t) for t in json.loads((data_dir / "towers.json").read_text("utf-8"))}

    observations = []
    for o in json.loads((data_dir / "tower_observations.json").read_text("utf-8")):
        o = dict(o)
        o["observed_at"] = _parse_dt(o["observed_at"])
        observations.append(TowerObservation(**o))

    hotspots = []
    for h in json.loads((data_dir / "satellite_hotspots.json").read_text("utf-8")):
        h = dict(h)
        h["acquired_at"] = _parse_dt(h["acquired_at"])
        h["confidence"] = normalize_confidence(h["confidence"])
        hotspots.append(SatelliteHotspot(**h))

    rangers = [Ranger(**r) for r in json.loads((data_dir / "rangers.json").read_text("utf-8"))]
    return towers, observations, hotspots, rangers


def render_checklist(task, event: FireEvent, ranger: Ranger) -> str:
    """生成可打印/短信下发的核查清单文本。"""
    lines = [
        "=" * 56,
        f"森林火险核查清单  {task.task_id}（{task.priority}）",
        "=" * 56,
        f"事件编号：{event.event_id}    综合置信度：{event.confidence:.0%}",
        f"核查坐标：{event.lat:.5f}, {event.lon:.5f}（误差约 {event.uncertainty_m:.0f} m）",
        f"最大 FRP：{event.frp_max_mw:.1f} MW    最新探测：{event.last_detected:%Y-%m-%d %H:%M}",
        f"信息来源：{'；'.join(s['detail'] for s in event.sources)}",
        "-" * 56,
        f"执行人：{ranger.name}（{ranger.ranger_id}，{ranger.phone}）",
        f"直线距离：{task.distance_m / 1000:.1f} km    预计到达：{task.eta_min:.0f} 分钟",
        f"下发时间：{task.issued_at:%Y-%m-%d %H:%M}    核查时限：{task.deadline:%H:%M} 前",
        "-" * 56,
        "核查事项：",
    ]
    for item in task.checklist:
        mark = "□" if not item.done else "☑"
        lines.append(f"  {mark} {item.item_id}. {item.text}")
    lines.append("=" * 56)
    return "\n".join(lines)


def run_pipeline(data_dir: str | Path, db_path: str | Path, out_dir: str | Path,
                 now: datetime | None = None) -> dict:
    towers, observations, hotspots, rangers = load_data(data_dir)

    candidates = [hotspot_to_candidate(h) for h in hotspots]
    candidates += [observation_to_candidate(o, towers[o.tower_id]) for o in observations]

    events = fuse_candidates(candidates)

    # 派发时刻：默认取数据中最新的探测时间，保证演示可复现
    now = now or max((e.last_detected for e in events), default=datetime.now().astimezone())
    tasks, unassigned = dispatch_events(events, rangers, now)

    store = Store(db_path)
    store.save_events(events)
    store.save_tasks(tasks)
    store.close()

    out_dir = Path(out_dir)
    cl_dir = out_dir / "checklists"
    cl_dir.mkdir(parents=True, exist_ok=True)
    rangers_by_id = {r.ranger_id: r for r in rangers}
    events_by_id = {e.event_id: e for e in events}
    for t in tasks:
        text = render_checklist(t, events_by_id[t.event_id], rangers_by_id[t.ranger_id])
        (cl_dir / f"{t.task_id}.txt").write_text(text + "\n", "utf-8")

    summary = {
        "generated_at": now.isoformat(),
        "input": {"satellite_hotspots": len(hotspots), "tower_observations": len(observations)},
        "fused_events": len(events),
        "tasks_dispatched": len(tasks),
        "unassigned_events": [e.event_id for e in unassigned],
        "events": [
            {
                "event_id": e.event_id, "lat": round(e.lat, 5), "lon": round(e.lon, 5),
                "confidence": round(e.confidence, 3), "frp_max_mw": e.frp_max_mw,
                "priority": e.priority, "sources": len(e.sources),
                "last_detected": e.last_detected.isoformat(),
            }
            for e in events
        ],
        "tasks": [
            {"task_id": t.task_id, "event_id": t.event_id, "ranger_id": t.ranger_id,
             "priority": t.priority, "distance_km": round(t.distance_m / 1000, 2),
             "eta_min": round(t.eta_min), "deadline": t.deadline.isoformat()}
            for t in tasks
        ],
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return summary
