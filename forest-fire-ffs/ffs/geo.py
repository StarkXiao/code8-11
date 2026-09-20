"""地理计算工具：球面距离、方位角定位、多塔方位线三角定位。

所有角度使用度（°），距离使用米（m），坐标为 WGS-84 经纬度。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两经纬度点之间的球面距离（米）。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """点1 望向 点2 的方位角（真北为 0°，顺时针，0~360）。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def destination_point(lat: float, lon: float, azimuth_deg: float, dist_m: float) -> tuple[float, float]:
    """从某点沿方位角行进指定距离后的经纬度（瞭望塔单站定位用）。"""
    d = dist_m / EARTH_RADIUS_M
    b = math.radians(azimuth_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(
        math.sin(b) * math.sin(d) * math.cos(p1),
        math.cos(d) - math.sin(p1) * math.sin(p2),
    )
    return math.degrees(p2), math.degrees(l2)


@dataclass
class BearingLine:
    """一条方位线：从 (lat, lon) 沿 azimuth_deg 方向的射线。"""

    lat: float
    lon: float
    azimuth_deg: float


def _to_enu(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """经纬度 → 以 (lat0, lon0) 为原点的局部平面坐标（东x/北y，米）。"""
    x = math.radians(lon - lon0) * EARTH_RADIUS_M * math.cos(math.radians(lat0))
    y = math.radians(lat - lat0) * EARTH_RADIUS_M
    return x, y


def _to_latlon(x: float, y: float, lat0: float, lon0: float) -> tuple[float, float]:
    """局部平面坐标 → 经纬度。"""
    lat = lat0 + math.degrees(y / EARTH_RADIUS_M)
    lon = lon0 + math.degrees(x / (EARTH_RADIUS_M * math.cos(math.radians(lat0))))
    return lat, lon


def triangulate(lines: list[BearingLine]) -> tuple[float, float] | None:
    """多塔方位线最小二乘交会定位。

    在局部平面坐标下，对每条方位线构造投影矩阵 P = I - d·dᵀ，
    求解使得到各线垂直距离平方和最小的点。方位线少于 2 条或
    几何形态退化（近乎平行）时返回 None。
    """
    if len(lines) < 2:
        return None
    lat0 = sum(l.lat for l in lines) / len(lines)
    lon0 = sum(l.lon for l in lines) / len(lines)

    a00 = a01 = a11 = 0.0
    b0 = b1 = 0.0
    for ln in lines:
        px, py = _to_enu(ln.lat, ln.lon, lat0, lon0)
        dx = math.sin(math.radians(ln.azimuth_deg))
        dy = math.cos(math.radians(ln.azimuth_deg))
        pxx, pxy, pyy = 1 - dx * dx, -dx * dy, 1 - dy * dy
        a00 += pxx
        a01 += pxy
        a11 += pyy
        b0 += pxx * px + pxy * py
        b1 += pxy * px + pyy * py

    det = a00 * a11 - a01 * a01
    if abs(det) < 1e-9:  # 方位线近乎平行，交会失败
        return None
    x = (b0 * a11 - b1 * a01) / det
    y = (a00 * b1 - a01 * b0) / det
    return _to_latlon(x, y, lat0, lon0)


def triangulation_residuals_m(lines: list[BearingLine], lat: float, lon: float) -> list[float]:
    """交会点到每条方位线的垂直距离（米），用于评估交会质量。"""
    lat0, lon0 = lat, lon
    residuals = []
    for ln in lines:
        px, py = _to_enu(ln.lat, ln.lon, lat0, lon0)
        dx = math.sin(math.radians(ln.azimuth_deg))
        dy = math.cos(math.radians(ln.azimuth_deg))
        # 点到方位线的垂直距离 = |方向向量 × 位移向量|
        residuals.append(abs(dx * py - dy * px))
    return residuals


def along_track_m(line: BearingLine, lat: float, lon: float) -> float:
    """点投影到方位线上的沿程距离（米）；负值表示在观测者背后。"""
    px, py = _to_enu(lat, lon, line.lat, line.lon)
    dx = math.sin(math.radians(line.azimuth_deg))
    dy = math.cos(math.radians(line.azimuth_deg))
    return px * dx + py * dy
