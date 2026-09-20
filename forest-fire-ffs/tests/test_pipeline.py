import tempfile
import unittest
from pathlib import Path

from ffs.pipeline import run_pipeline
from ffs.store import Store

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class TestPipeline(unittest.TestCase):
    def test_end_to_end_with_sample_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ffs.db"
            summary = run_pipeline(DATA_DIR, db, Path(tmp) / "out")

            # 7 条热点 + 3 条塔台观测 → 去重后 5 起事件
            self.assertEqual(summary["input"]["satellite_hotspots"], 7)
            self.assertEqual(summary["input"]["tower_observations"], 3)
            self.assertEqual(summary["fused_events"], 5)
            self.assertEqual(summary["tasks_dispatched"], 5)
            self.assertEqual(summary["unassigned_events"], [])

            # 核查清单文件已生成
            checklists = list((Path(tmp) / "out" / "checklists").glob("T-*.txt"))
            self.assertEqual(len(checklists), 5)

            # 反馈闭环：确认火情后事件状态联动更新
            store = Store(db)
            first_task = summary["tasks"][0]["task_id"]
            result = store.record_feedback(first_task, "confirmed", "现场明火 2 处",
                                           __import__("datetime").datetime.now().astimezone())
            self.assertEqual(result["event_status"], "确认火情")
            store.close()


if __name__ == "__main__":
    unittest.main()
