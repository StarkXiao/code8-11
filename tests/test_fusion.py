import unittest
from datetime import datetime, timedelta

from forest_fire.fusion import (
    fuse_detections,
    hotspot_to_detection,
    observation_to_detection,
    satellite_confidence,
)
from forest_fire.geo import haversine_km
from forest_fire.models import (
    RiskLevel,
    SatelliteHotspot,
    SourceType,
    Tower,
    TowerObservation,
)

BASE = datetime(2026, 9, 20, 9, 0)


def hs(hid, lat, lon, minutes=0, frp=30.0, conf=80):
    return SatelliteHotspot(hid, "TEST-SAT", BASE + timedelta(minutes=minutes),
                            lat, lon, frp=frp, confidence=conf)


class TestConfidence(unittest.TestCase):
    def test_numeric_and_label(self):
        self.assertAlmostEqual(satellite_confidence(80), 0.8)
        self.assertAlmostEqual(satellite_confidence("high"), 0.9)
        self.assertAlmostEqual(satellite_confidence("low"), 0.3)


class TestFusion(unittest.TestCase):
    def test_close_points_merge(self):
        dets = [hotspot_to_detection(hs("A", 42.10, 127.90)),
                hotspot_to_detection(hs("B", 42.101, 127.901, minutes=30))]
        events = fuse_detections(dets, spatial_km=2.0)
        self.assertEqual(len(events), 1)
        self.assertEqual(len(events[0].detections), 2)

    def test_far_points_split(self):
        dets = [hotspot_to_detection(hs("A", 42.10, 127.90)),
                hotspot_to_detection(hs("B", 42.30, 128.10))]
        self.assertEqual(len(fuse_detections(dets)), 2)

    def test_time_window_split(self):
        # 空间上很近但相隔 20 小时，超出 12h 窗口 → 视为两次火情
        dets = [hotspot_to_detection(hs("A", 42.10, 127.90)),
                hotspot_to_detection(hs("B", 42.101, 127.901, minutes=20 * 60))]
        events = fuse_detections(dets, temporal_hours=12.0)
        self.assertEqual(len(events), 2)

    def test_multi_source_event_is_high_risk(self):
        tower = Tower("T01", "北岭瞭望塔", 42.150, 127.860)
        obs = TowerObservation("OB-1", "T01", BASE, azimuth_deg=141.2, distance_km=6.9)
        dets = [observation_to_detection(obs, tower),
                hotspot_to_detection(hs("A", 42.102, 127.905, frp=60, conf=95))]
        events = fuse_detections(dets)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev.sources, {SourceType.TOWER, SourceType.SATELLITE})
        self.assertEqual(ev.risk, RiskLevel.HIGH)

    def test_low_conf_single_source_is_low_risk(self):
        events = fuse_detections([hotspot_to_detection(hs("A", 42.10, 127.90, frp=5, conf=20))])
        self.assertEqual(events[0].risk, RiskLevel.LOW)

    def test_tower_observation_locates_near_truth(self):
        tower = Tower("T01", "北岭瞭望塔", 42.150, 127.860)
        obs = TowerObservation("OB-1", "T01", BASE, azimuth_deg=141.2, distance_km=6.9)
        det = observation_to_detection(obs, tower)
        self.assertIsNotNone(det)
        # 推算点应落在红松洼真实火点 1km 以内
        self.assertLess(haversine_km(det.lat, det.lon, 42.102, 127.905), 1.0)

    def test_observation_without_distance_dropped(self):
        tower = Tower("T01", "北岭瞭望塔", 42.150, 127.860)
        obs = TowerObservation("OB-1", "T01", BASE, azimuth_deg=141.2, distance_km=None)
        self.assertIsNone(observation_to_detection(obs, tower))


if __name__ == "__main__":
    unittest.main()
