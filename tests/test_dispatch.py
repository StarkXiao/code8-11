import unittest
from datetime import datetime, timedelta

from forest_fire.dispatch import DEADLINE_HOURS, dispatch_events
from forest_fire.fusion import (
    fuse_detections,
    hotspot_to_detection,
    observation_to_detection,
)
from forest_fire.models import (
    Ranger,
    RiskLevel,
    SatelliteHotspot,
    Tower,
    TowerObservation,
)

BASE = datetime(2026, 9, 20, 10, 30)


def make_event(lat, lon, frp=80, conf=95):
    h = SatelliteHotspot("HS", "SAT", BASE - timedelta(hours=1), lat, lon,
                         frp=frp, confidence=conf)
    return fuse_detections([hotspot_to_detection(h)])[0]


class TestDispatch(unittest.TestCase):
    def setUp(self):
        self.rangers = [
            Ranger("R1", "甲", "一站", 42.10, 127.90),
            Ranger("R2", "乙", "二站", 42.50, 128.30),
        ]

    def test_nearest_ranger_assigned(self):
        event = make_event(42.101, 127.902)
        tasks = dispatch_events([event], self.rangers, now=BASE)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].ranger.ranger_id, "R1")
        self.assertFalse(tasks[0].cross_region)

    def test_cross_region_flagged(self):
        event = make_event(42.30, 128.10)  # 距两站均超过默认责任区 25km
        tasks = dispatch_events([event], self.rangers, now=BASE)
        self.assertEqual(len(tasks), 1)
        self.assertTrue(tasks[0].cross_region)

    def test_max_tasks_respected(self):
        rangers = [Ranger("R1", "甲", "一站", 42.10, 127.90, max_tasks=1),
                   Ranger("R2", "乙", "二站", 42.12, 127.92, max_tasks=1)]
        events = [make_event(42.100, 127.900), make_event(42.101, 127.901)]
        tasks = dispatch_events(events, rangers, now=BASE)
        self.assertEqual({t.ranger.ranger_id for t in tasks}, {"R1", "R2"})

    def test_high_risk_dispatched_first(self):
        # 高风险：塔台+卫星互证；低风险：单一低置信卫星热点
        tower = Tower("T", "瞭望塔", 42.15, 127.86)
        obs = TowerObservation("OB", "T", BASE - timedelta(hours=1),
                               azimuth_deg=141.2, distance_km=6.9)
        high = fuse_detections([
            observation_to_detection(obs, tower),
            hotspot_to_detection(SatelliteHotspot(
                "HS-H", "SAT", BASE - timedelta(hours=1), 42.102, 127.905,
                frp=80, confidence=95)),
        ])[0]
        low = make_event(42.100, 127.900, frp=5, conf=20)
        tasks = dispatch_events([low, high], self.rangers, now=BASE)
        self.assertEqual(high.risk, RiskLevel.HIGH)
        self.assertEqual(tasks[0].priority, RiskLevel.HIGH)

    def test_deadline_and_checklist(self):
        event = make_event(42.101, 127.902)
        task = dispatch_events([event], self.rangers, now=BASE)[0]
        self.assertEqual(task.deadline - task.issued_at,
                         timedelta(hours=DEADLINE_HOURS[task.priority]))
        self.assertTrue(any("42.10100" in item for item in task.checklist))
        self.assertEqual(task.status, "待核查")


if __name__ == "__main__":
    unittest.main()
