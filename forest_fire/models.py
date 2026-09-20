"""领域模型：观测、热点、火情事件、护林员与核查任务。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SourceType(str, Enum):
    TOWER = "tower"          # 瞭望塔台人工观测
    SATELLITE = "satellite"  # 卫星红外热点


@dataclass(frozen=True)
class Tower:
    tower_id: str
    name: str
    lat: float
    lon: float
    elevation_m: float = 0.0


@dataclass(frozen=True)
class TowerObservation:
    """塔台观测记录：方位角 + 估算距离定位烟点。"""
    obs_id: str
    tower_id: str
    observed_at: datetime
    azimuth_deg: float            # 烟点方位角（度，0=正北）
    distance_km: Optional[float]  # 估算距离；缺失时无法定位，仅作佐证
    smoke_color: str = "灰白"
    notes: str = ""


@dataclass(frozen=True)
class SatelliteHotspot:
    """卫星热点（兼容 NASA FIRMS 风格字段）。"""
    hotspot_id: str
    satellite: str                # 如 Suomi-NPP / NOAA-20 / Aqua
    acq_time: datetime
    lat: float
    lon: float
    frp: float = 0.0              # 火辐射功率 MW
    confidence: object = 0        # 0-100 或 low/nominal/high
    brightness_k: float = 0.0     # 亮温 K


@dataclass
class Detection:
    """归一化后的单次探测，进入融合流程的统一结构。"""
    source_type: SourceType
    source_id: str                # 观测/热点编号
    lat: float
    lon: float
    detected_at: datetime
    confidence: float             # 0~1
    loc_weight: float             # 参与位置融合的权重
    frp: float = 0.0
    detail: str = ""


class RiskLevel(str, Enum):
    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"


@dataclass
class FireEvent:
    """去重融合后的火情事件。"""
    event_id: str
    lat: float
    lon: float
    first_seen: datetime
    last_seen: datetime
    detections: list[Detection] = field(default_factory=list)
    risk: RiskLevel = RiskLevel.LOW
    risk_score: int = 0

    @property
    def sources(self) -> set[SourceType]:
        return {d.source_type for d in self.detections}


@dataclass(frozen=True)
class Ranger:
    ranger_id: str
    name: str
    station: str
    lat: float
    lon: float
    phone: str = ""
    jurisdiction_km: float = 25.0  # 责任区半径
    max_tasks: int = 3             # 单班最大并发核查任务


@dataclass
class VerificationTask:
    task_id: str
    event: FireEvent
    ranger: Ranger
    priority: RiskLevel
    issued_at: datetime
    deadline: datetime
    cross_region: bool             # 是否跨责任区支援
    checklist: list[str] = field(default_factory=list)
    status: str = "待核查"
