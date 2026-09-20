"""多源探测融合与去重。

流程：异构观测归一化为 Detection → 时空双阈值聚类去重 → 加权质心定位
      → 多源互证风险定级 → 输出 FireEvent。
"""
from __future__ import annotations

from datetime import timedelta

from .geo import destination_point, haversine_km
from .models import (
    Detection,
    FireEvent,
    RiskLevel,
    SatelliteHotspot,
    SourceType,
    Tower,
    TowerObservation,
)

_CONF_STR_MAP = {"low": 0.3, "nominal": 0.6, "high": 0.9,
                 "l": 0.3, "n": 0.6, "h": 0.9}


def satellite_confidence(value) -> float:
    """兼容 FIRMS 的数值（0-100）与档位（low/nominal/high）两种置信度。"""
    if isinstance(value, str):
        return _CONF_STR_MAP.get(value.strip().lower(), 0.5)
    return max(0.0, min(1.0, float(value) / 100.0))


def observation_to_detection(obs: TowerObservation, tower: Tower) -> Detection | None:
    """塔台观测 → 统一探测。缺距离估算时无法定位，返回 None（留作人工研判）。"""
    if obs.distance_km is None:
        return None
    lat, lon = destination_point(tower.lat, tower.lon, obs.azimuth_deg, obs.distance_km)
    return Detection(
        source_type=SourceType.TOWER,
        source_id=obs.obs_id,
        lat=lat,
        lon=lon,
        detected_at=obs.observed_at,
        confidence=0.7,    # 肉眼见烟可信度高
        loc_weight=0.5,    # 但距离系人工估算，定位权重低于卫星
        detail=f"{tower.name} 方位{obs.azimuth_deg:.0f}° 约{obs.distance_km:.1f}km {obs.smoke_color}烟",
    )


def hotspot_to_detection(h: SatelliteHotspot) -> Detection:
    conf = satellite_confidence(h.confidence)
    return Detection(
        source_type=SourceType.SATELLITE,
        source_id=h.hotspot_id,
        lat=h.lat,
        lon=h.lon,
        detected_at=h.acq_time,
        confidence=conf,
        loc_weight=0.5 + conf / 2,  # 0.5~1.0，置信度越高定位越可信
        frp=h.frp,
        detail=f"{h.satellite} FRP={h.frp:.1f}MW 置信度{conf:.0%}",
    )


class _Cluster:
    """增量聚类：维护加权质心与最后探测时间。"""

    __slots__ = ("detections", "_wlat", "_wlon", "_wsum", "last_time")

    def __init__(self, det: Detection):
        self.detections = [det]
        self._wlat = det.lat * det.loc_weight
        self._wlon = det.lon * det.loc_weight
        self._wsum = det.loc_weight
        self.last_time = det.detected_at

    @property
    def lat(self) -> float:
        return self._wlat / self._wsum

    @property
    def lon(self) -> float:
        return self._wlon / self._wsum

    def add(self, det: Detection) -> None:
        self.detections.append(det)
        self._wlat += det.lat * det.loc_weight
        self._wlon += det.lon * det.loc_weight
        self._wsum += det.loc_weight
        self.last_time = max(self.last_time, det.detected_at)


def fuse_detections(
    detections: list[Detection],
    spatial_km: float = 2.0,
    temporal_hours: float = 12.0,
) -> list[FireEvent]:
    """时空阈值聚类去重：同一火情的多源重复报告合并为一个事件。

    - spatial_km：空间阈值，卫星像元定位误差 + 塔台估距误差的容差
    - temporal_hours：时间窗口，超过则认为是一次新火情而非重复报告
    """
    clusters: list[_Cluster] = []
    for det in sorted(detections, key=lambda d: d.detected_at):
        best, best_dist = None, spatial_km
        for c in clusters:
            if det.detected_at - c.last_time > timedelta(hours=temporal_hours):
                continue
            d = haversine_km(det.lat, det.lon, c.lat, c.lon)
            if d <= best_dist:
                best, best_dist = c, d
        if best is None:
            clusters.append(_Cluster(det))
        else:
            best.add(det)

    events = []
    for i, c in enumerate(clusters, 1):
        score, risk = assess_risk(c.detections)
        events.append(FireEvent(
            event_id=f"EV-{i:03d}",
            lat=round(c.lat, 5),
            lon=round(c.lon, 5),
            first_seen=min(d.detected_at for d in c.detections),
            last_seen=c.last_time,
            detections=list(c.detections),
            risk=risk,
            risk_score=score,
        ))
    return events


def assess_risk(detections: list[Detection]) -> tuple[int, RiskLevel]:
    """风险评分：多源互证 + 置信度 + 火辐射功率。"""
    sources = {d.source_type for d in detections}
    max_conf = max(d.confidence for d in detections)
    max_frp = max((d.frp for d in detections), default=0.0)

    score = 0
    if SourceType.TOWER in sources and SourceType.SATELLITE in sources:
        score += 2  # 塔台与卫星互证，基本可排除单一误报
    elif SourceType.TOWER in sources:
        score += 1  # 肉眼见烟但无卫星佐证
    if max_conf >= 0.8:
        score += 2
    elif max_conf >= 0.5:
        score += 1
    if max_frp >= 50:
        score += 2
    elif max_frp >= 20:
        score += 1

    if score >= 5:
        return score, RiskLevel.HIGH
    if score >= 3:
        return score, RiskLevel.MEDIUM
    return score, RiskLevel.LOW
