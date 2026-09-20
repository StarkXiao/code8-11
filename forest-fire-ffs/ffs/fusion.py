"""融合去重引擎：把塔台观测与卫星热点归并为同一火情事件。

处理流程：
1. 塔台观测 → 候选点（方位角 + 目测距离定位；不确定度随距离增大）；
2. 卫星热点 → 候选点（不确定度取传感器像元尺度）；
3. 时空聚类去重：两点距离 ≤ 各自不确定度之和 且 时间差 ≤ 融合窗口，
   以并查集归并为同一事件；
4. 同一事件内若有 ≥2 座塔在短时间窗内的观测，升级为三角定位，
   提高精度与置信度；
5. 逆方差加权融合位置，置信度按独立源概率合成，跨源（塔台+卫星）
   一致时给予加成。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .geo import (
    BearingLine,
    along_track_m,
    destination_point,
    haversine_m,
    triangulate,
    triangulation_residuals_m,
)
from .models import FireEvent, SatelliteHotspot, Tower, TowerObservation

# ---- 可调参数 -------------------------------------------------------------
SATELLITE_UNCERTAINTY_M = {     # 各传感器的定位不确定度（约像元尺度）
    "VIIRS": 375.0,
    "MODIS": 1000.0,
    "FY-4A": 2000.0,
    "HIMAWARI": 2000.0,
}
DEFAULT_SAT_UNCERTAINTY_M = 1000.0

TOWER_SINGLE_CONFIDENCE = 0.55        # 单塔观测基础置信度
TOWER_TRIANGULATED_CONFIDENCE = 0.80  # 多塔交会置信度
TOWER_TRIANGULATED_UNCERTAINTY_M = 300.0
DEFAULT_TOWER_DISTANCE_M = 5000.0     # 未报目测距离时的默认距离
DISTANCE_ERROR_FACTOR = 0.22          # 目测距离/方位综合误差系数
MIN_TOWER_UNCERTAINTY_M = 400.0

FUSION_TIME_WINDOW = timedelta(hours=3)        # 融合时间窗（卫星重访周期量级）
TRIANGULATION_TIME_WINDOW = timedelta(minutes=45)  # 多塔视为同一火情的上报间隔
MAX_TRIANGULATION_RESIDUAL_M = 1500.0          # 交会残差上限，超过则放弃交会

CROSS_SOURCE_BONUS = 0.10   # 塔台与卫星互相印证的置信度加成
MAX_CONFIDENCE = 0.99

_CONFIDENCE_WORDS = {"low": 0.4, "nominal": 0.7, "high": 0.9}


def normalize_confidence(raw) -> float:
    """兼容多种置信度写法：low/nominal/high、0~100 百分数、0~1 小数。"""
    if isinstance(raw, str):
        return _CONFIDENCE_WORDS.get(raw.strip().lower(), 0.5)
    value = float(raw)
    return value / 100.0 if value > 1.0 else value


@dataclass
class CandidatePoint:
    """待融合的候选火点（来自卫星或塔台）。"""

    source_type: str            # satellite / tower_single / tower_triangulation
    lat: float
    lon: float
    detected_at: datetime
    confidence: float
    uncertainty_m: float
    ref_ids: list[str] = field(default_factory=list)
    frp_mw: float = 0.0
    detail: str = ""
    # 仅塔台观测使用，供事件内三角定位：
    tower_id: str | None = None
    origin_lat: float | None = None
    origin_lon: float | None = None
    azimuth_deg: float | None = None


def hotspot_to_candidate(h: SatelliteHotspot) -> CandidatePoint:
    unc = SATELLITE_UNCERTAINTY_M.get(h.satellite.upper(), DEFAULT_SAT_UNCERTAINTY_M)
    return CandidatePoint(
        source_type="satellite",
        lat=h.lat,
        lon=h.lon,
        detected_at=h.acquired_at,
        confidence=h.confidence,
        uncertainty_m=unc,
        ref_ids=[h.hs_id],
        frp_mw=h.frp_mw,
        detail=f"{h.satellite} 热点（FRP {h.frp_mw:.1f} MW）",
    )


def observation_to_candidate(obs: TowerObservation, tower: Tower) -> CandidatePoint:
    dist = obs.distance_m if obs.distance_m and obs.distance_m > 0 else DEFAULT_TOWER_DISTANCE_M
    lat, lon = destination_point(tower.lat, tower.lon, obs.azimuth_deg, dist)
    unc = max(MIN_TOWER_UNCERTAINTY_M, DISTANCE_ERROR_FACTOR * dist)
    return CandidatePoint(
        source_type="tower_single",
        lat=lat,
        lon=lon,
        detected_at=obs.observed_at,
        confidence=TOWER_SINGLE_CONFIDENCE,
        uncertainty_m=unc,
        ref_ids=[obs.obs_id],
        detail=f"{tower.name} 单站定位（方位 {obs.azimuth_deg:.1f}°，估距 {dist:.0f} m）",
        tower_id=tower.tower_id,
        origin_lat=tower.lat,
        origin_lon=tower.lon,
        azimuth_deg=obs.azimuth_deg,
    )


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _try_triangulate(tower_members: list[CandidatePoint]) -> CandidatePoint | None:
    """同一事件内的多塔观测尝试交会定位；失败（几何退化/残差大/在塔后）返回 None。"""
    towers = {m.tower_id for m in tower_members}
    if len(towers) < 2:
        return None
    span = max(m.detected_at for m in tower_members) - min(m.detected_at for m in tower_members)
    if span > TRIANGULATION_TIME_WINDOW:
        return None
    lines = [BearingLine(m.origin_lat, m.origin_lon, m.azimuth_deg) for m in tower_members]
    point = triangulate(lines)
    if point is None:
        return None
    lat, lon = point
    # 交会点必须在各塔观测方向前方，且残差可接受
    for m, line in zip(tower_members, lines):
        if along_track_m(line, lat, lon) < -500.0:
            return None
    if max(triangulation_residuals_m(lines, lat, lon)) > MAX_TRIANGULATION_RESIDUAL_M:
        return None
    names = "、".join(sorted(towers))
    return CandidatePoint(
        source_type="tower_triangulation",
        lat=lat,
        lon=lon,
        detected_at=max(m.detected_at for m in tower_members),
        confidence=TOWER_TRIANGULATED_CONFIDENCE,
        uncertainty_m=TOWER_TRIANGULATED_UNCERTAINTY_M,
        ref_ids=[rid for m in tower_members for rid in m.ref_ids],
        detail=f"多塔交会定位（{names}）",
    )


def _build_event(event_id: str, members: list[CandidatePoint]) -> FireEvent:
    satellites = [m for m in members if m.source_type == "satellite"]
    tower_singles = [m for m in members if m.source_type == "tower_single"]

    tri = _try_triangulate(tower_singles)
    # 参与位置/置信度融合的组成成分：卫星点 + （交会点 或 各单塔点）
    components = satellites + ([tri] if tri else tower_singles)

    # 逆方差加权质心
    weights = [1.0 / (c.uncertainty_m ** 2) for c in components]
    w_sum = sum(weights)
    lat = sum(c.lat * w for c, w in zip(components, weights)) / w_sum
    lon = sum(c.lon * w for c, w in zip(components, weights)) / w_sum
    unc = 1.0 / (w_sum ** 0.5)

    # 置信度：独立源概率合成 + 跨源加成
    fused = 1.0
    for c in components:
        fused *= 1.0 - c.confidence
    confidence = 1.0 - fused
    types = {c.source_type for c in components}
    if "satellite" in types and types & {"tower_single", "tower_triangulation"}:
        confidence += CROSS_SOURCE_BONUS
    confidence = min(MAX_CONFIDENCE, confidence)

    sources = []
    for c in components:
        sources.append({
            "type": c.source_type,
            "ref_ids": c.ref_ids,
            "time": c.detected_at.isoformat(),
            "confidence": round(c.confidence, 3),
            "detail": c.detail,
        })

    return FireEvent(
        event_id=event_id,
        lat=lat,
        lon=lon,
        uncertainty_m=unc,
        confidence=confidence,
        frp_max_mw=max((m.frp_mw for m in members), default=0.0),
        first_detected=min(m.detected_at for m in members),
        last_detected=max(m.detected_at for m in members),
        sources=sources,
    )


def fuse_candidates(
    candidates: list[CandidatePoint],
    time_window: timedelta = FUSION_TIME_WINDOW,
) -> list[FireEvent]:
    """时空聚类去重，输出融合火情事件列表（按发现时间编号）。"""
    if not candidates:
        return []
    uf = _UnionFind(len(candidates))
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            a, b = candidates[i], candidates[j]
            if abs(a.detected_at - b.detected_at) > time_window:
                continue
            if haversine_m(a.lat, a.lon, b.lat, b.lon) <= a.uncertainty_m + b.uncertainty_m:
                uf.union(i, j)

    clusters: dict[int, list[CandidatePoint]] = {}
    for idx, c in enumerate(candidates):
        clusters.setdefault(uf.find(idx), []).append(c)

    ordered = sorted(clusters.values(), key=lambda ms: (min(m.detected_at for m in ms), ms[0].lat))
    return [_build_event(f"E-{k + 1:04d}", members) for k, members in enumerate(ordered)]
