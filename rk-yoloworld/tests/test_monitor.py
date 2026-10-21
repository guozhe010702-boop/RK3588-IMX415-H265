"""Pure monitor parsing/rate tests; no camera, SSH, /proc mutation or RKNN needed."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from monitor import delta_rate, flatten, latest_metrics, npu_load, task_stat


class MonitorTests(unittest.TestCase):
    def test_counter_reset_and_baseline(self):
        self.assertIsNone(delta_rate(10, None, 1))
        self.assertIsNone(delta_rate(1, 10, 1))
        self.assertIsNone(delta_rate(10, 1, 0))
        self.assertEqual(delta_rate(50, 10, 2), 20)

    def test_missing_npu_is_not_zero(self):
        self.assertEqual(npu_load("unavailable"), [None, None, None])
        self.assertEqual(npu_load("Core0: 93%, Core1: 0%, Core2: 94%,"), [93, 0, 94])

    def test_proc_comm_can_contain_spaces_and_parentheses(self):
        fields = ["S"] + ["0"] * 21
        fields[11], fields[12], fields[19] = "120", "30", "777"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "stat"
            path.write_text("1 (name with ) parens) " + " ".join(fields))
            self.assertEqual(task_stat(path), (150, 777))

    def test_pid_filter_and_incomplete_log(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "logs").mkdir()
            (root / "logs/a.jsonl").write_text(
                json.dumps({"pid": 12, "elapsed_s": 1}) + "\n{partial"
            )
            self.assertIsNone(latest_metrics(root, 13)[0])
            self.assertEqual(latest_metrics(root, 12)[0]["elapsed_s"], 1)

    def test_csv_columns_survive_start_stop(self):
        data = {
            "time": "now",
            "running": False,
            "metrics_fresh": False,
            "host_cpu_percent": None,
            "host_memory_used_mib": None,
            "application": None,
            "metrics": None,
            "workers": [],
            "npu_core_percent": [None] * 3,
            "network": {},
        }
        before = flatten(data)
        data["application"] = {"pid": 1, "cpu_core_percent": 100, "rss_mib": 50}
        data["workers"] = [
            {
                "worker": 0,
                "tid": 2,
                "core": 0,
                "cpu_core_percent": 3,
                "completed": 9,
                "inference_fps": 4,
            }
        ]
        after = flatten(data)
        self.assertEqual(set(before), set(after))
        self.assertIsNone(before["worker0_inference_fps"])
        self.assertEqual(after["worker0_inference_fps"], 4)


if __name__ == "__main__":
    unittest.main()
