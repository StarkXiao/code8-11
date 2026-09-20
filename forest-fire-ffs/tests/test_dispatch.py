import unittest
from datetime import datetime, timedelta, timezone

from ffs.dispatch import assign_priority, build_checklist, dispatch_events
from ffs.models import FireEvent, Ranger

CST = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=CST)


def make_event(eid, lat, lon, conf=0.9, frp=60.0):
    return FireEvent(event_id=eid, lat=lat, lon=lon, uncertainty_m=300.0,
                     confidence=conf, frp_max_mw=frp,
                     first_detected=NOW, last_detected=NOW)


class TestPriority(unittest.TestCase):
    def test_p1_by_confidence_or_frp(self):
        self.assertEqual(assign_priority(make_event("E", 0, 0, conf=0.85, frp=5)), "P1")
        self.assertEqual(assign_priority(make_event("E", 0, 0, conf=0.6, frp=80)), "P1")

    def test_p2_and_p3(self):
        self.assertEqual(assign_priority(make_event("E", 0, 0, conf=0.6, frp=20)), "P2")
        self.assertEqual(assign_priority(make_event("E", 0, 0, conf=0.3, frp=1)), "P3")


class TestDispatch(unittest.TestCase):
    def setUp(self):
        self.rangers = [
            Ranger("R1", "甲", 24.80, 101.20, max_tasks=1),
            Ranger("R2", "乙", 24.90, 101.30, max_tasks=1),
        ]

    def test_nearest_ranger_assigned(self):
        tasks, unassigned = dispatch_events(
            [make_event("E1", 24.801, 101.201)], self.rangers, NOW)
        self.assertEqual(tasks[0].ranger_id, "R1")
        self.assertEqual(unassigned, [])

    def test_capacity_overflow_goes_unassigned(self):
        events = [make_event("E1", 24.801, 101.201),
                  make_event("E2", 24.802, 101.202),
                  make_event("E3", 24.803, 101.203)]
        tasks, unassigned = dispatch_events(events, self.rangers, NOW)
        self.assertEqual(len(tasks), 2)          # 两人各限 1 单
        self.assertEqual(len(unassigned), 1)

    def test_checklist_contents(self):
        items = build_checklist(make_event("E1", 24.8, 101.2, conf=0.9, frp=68))
        text = "\n".join(i.text for i in items)
        self.assertIn("拍照", text)
        self.assertIn("12119", text)
        self.assertIn("树冠火", text)   # 高 FRP 追加项
        self.assertGreaterEqual(len(items), 8)

    def test_low_confidence_checklist_hint(self):
        items = build_checklist(make_event("E1", 24.8, 101.2, conf=0.5, frp=5))
        self.assertIn("误报", "\n".join(i.text for i in items))

    def test_deadline_by_priority(self):
        tasks, _ = dispatch_events([make_event("E1", 24.801, 101.201)], self.rangers, NOW)
        self.assertEqual(tasks[0].deadline, NOW + timedelta(hours=2))  # P1 限时 2 小时


if __name__ == "__main__":
    unittest.main()
