import unittest
from datetime import datetime, timedelta, timezone

from ffs.fusion import (
    CandidatePoint,
    fuse_candidates,
    normalize_confidence,
    observation_to_candidate,
)
from ffs.models import Tower, TowerObservation

CST = timezone(timedelta(hours=8))
T0 = datetime(2026, 9, 20, 9, 0, tzinfo=CST)


def sat(lat, lon, minutes=0, conf=0.8, unc=375.0, frp=10.0, hid="H"):
    return CandidatePoint("satellite", lat, lon, T0 + timedelta(minutes=minutes),
                          conf, unc, [hid], frp)


class TestNormalizeConfidence(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(normalize_confidence("high"), 0.9)
        self.assertEqual(normalize_confidence(82), 0.82)
        self.assertEqual(normalize_confidence(0.45), 0.45)


class TestFusionDedup(unittest.TestCase):
    def test_nearby_hotspots_merge(self):
        events = fuse_candidates([sat(24.8, 101.2, 0, hid="A"),
                                  sat(24.8005, 101.2005, 30, hid="B")])
        self.assertEqual(len(events), 1)
        self.assertEqual(len(events[0].sources), 2)

    def test_far_hotspots_stay_separate(self):
        events = fuse_candidates([sat(24.8, 101.2, hid="A"),
                                  sat(24.9, 101.3, hid="B")])
        self.assertEqual(len(events), 2)

    def test_time_window_respected(self):
        events = fuse_candidates([sat(24.8, 101.2, 0, hid="A"),
                                  sat(24.8005, 101.2005, 400, hid="B")])  # 6.7 小时后
        self.assertEqual(len(events), 2)

    def test_confidence_fusion_and_cross_source_bonus(self):
        tower = Tower("T1", "塔", 24.835, 101.180)
        obs = TowerObservation("O1", "T1", T0, 125.9, 4400)
        cand = observation_to_candidate(obs, tower)
        events = fuse_candidates([cand, sat(cand.lat + 0.001, cand.lon + 0.001, 10, conf=0.9)])
        self.assertEqual(len(events), 1)
        # 1-(1-0.55)(1-0.9)=0.955，跨源加成 +0.1 → 封顶 0.99
        self.assertAlmostEqual(events[0].confidence, 0.99, places=2)


class TestTowerTriangulation(unittest.TestCase):
    def test_two_towers_upgrade_to_triangulation(self):
        t1 = Tower("T1", "塔1", 24.835, 101.180)
        t2 = Tower("T2", "塔2", 24.790, 101.250)
        truth = (24.812, 101.215)
        o1 = TowerObservation("O1", "T1", T0, 125.9, 4400)
        o2 = TowerObservation("O2", "T2", T0 + timedelta(minutes=4), 304.7, 4600)
        events = fuse_candidates([observation_to_candidate(o1, t1),
                                  observation_to_candidate(o2, t2)])
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev.sources[0]["type"], "tower_triangulation")
        from ffs.geo import haversine_m
        self.assertLess(haversine_m(ev.lat, ev.lon, *truth), 300.0)
        self.assertGreaterEqual(ev.confidence, 0.8)

    def test_single_tower_uses_distance_estimate(self):
        t3 = Tower("T3", "塔3", 24.760, 101.150)
        obs = TowerObservation("O3", "T3", T0, 40.0, 6000)
        events = fuse_candidates([observation_to_candidate(obs, t3)])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].sources[0]["type"], "tower_single")


if __name__ == "__main__":
    unittest.main()
