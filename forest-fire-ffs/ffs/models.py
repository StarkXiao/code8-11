"""数据模型：瞭望塔、塔台观测、卫星热点、融合火情事件、护林员、核查任务。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Tower:
    """瞭望塔。"""

    tower_id: str
    name: str
    lat: float
    lon: float
    elevation_m: float = 0.0


@dataclass
class TowerObservation:
    """塔台观测上报：方位角 + 目测距离（可选）。"""

    obs_id: str
    tower_id: str
    observed_at: datetime
    azimuth_deg: float          # 真北方位角，0~360
    distance_m: float | None = None   # 目测距离；缺省时按默认距离处理
    smoke_color: str = ""
    note: str = ""


@dataclass
class SatelliteHotspot:
    """卫星热点（VIIRS / MODIS / FY-4A 等）。"""

    hs_id: str
    satellite: str
    lat: float
    lon: float
    acquired_at: datetime
    confidence: float           # 归一化到 0~1
    frp_mw: float = 0.0         # 火点辐射功率
    brightness_k: float = 0.0   # 亮温


@dataclass
class FireEvent:
    """融合去重后的火情事件。"""

    event_id: str
    lat: float
    lon: float
    uncertainty_m: float        # 定位不确定度（米）
    confidence: float           # 综合置信度 0~1
    frp_max_mw: float           # 各卫星热点中的最大 FRP
    first_detected: datetime
    last_detected: datetime
    sources: list[dict] = field(default_factory=list)   # 来源明细
    priority: str = "P3"        # P1 最紧急
    status: str = "待核查"       # 待核查 / 确认火情 / 误报 / 需增援


@dataclass
class Ranger:
    """一线护林员。"""

    ranger_id: str
    name: str
    lat: float
    lon: float
    phone: str = ""
    max_tasks: int = 2          # 同时在办任务上限


@dataclass
class ChecklistItem:
    """核查清单条目。"""

    item_id: str
    text: str
    required: bool = True
    done: bool = False


@dataclass
class VerificationTask:
    """派发给护林员的核查任务（含核查清单）。"""

    task_id: str
    event_id: str
    ranger_id: str
    priority: str
    issued_at: datetime
    deadline: datetime
    distance_m: float           # 护林员驻点到火场的直线距离
    eta_min: float              # 按山区平均速度估算的到达时间
    checklist: list[ChecklistItem] = field(default_factory=list)
    status: str = "待核查"       # 待核查 / 已完成
