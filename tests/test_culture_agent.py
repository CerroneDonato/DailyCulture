import json
import os
import tempfile
import unittest
from pathlib import Path

import culture_agent


class TestCultureAgentState(unittest.TestCase):
    def test_load_state_supports_legacy_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "history.json"
            old.write_text(json.dumps(["alpha", "beta"]), encoding="utf-8")
            culture_agent.HISTORY_FILE = old
            try:
                state = culture_agent.load_state()
            finally:
                culture_agent.HISTORY_FILE = Path("history.json")
            self.assertEqual(state["log"][0]["title"], "alpha")
            self.assertEqual(state["log"][1]["cat"], "")

    def test_save_state_keeps_only_valid_ratings(self):
        state = {
            "_last_sent": "2026-10-23",
            "_offset": 0,
            "log": [
                {"id": "1", "date": "2026-10-23", "cat": "letteratura", "key": "A", "title": "A", "recap": "x"},
                {"id": "2", "date": "2026-10-23", "cat": "storia", "key": "B", "title": "B", "recap": "y"},
            ],
            "ratings": {"1": 1, "ghost": -1},
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_file = Path(tmp) / "history.json"
            culture_agent.HISTORY_FILE = tmp_file
            try:
                culture_agent.save_state(state)
                saved = json.loads(tmp_file.read_text(encoding="utf-8"))
            finally:
                culture_agent.HISTORY_FILE = Path("history.json")
        self.assertEqual(saved["ratings"], {"1": 1})
        self.assertEqual(len(saved["log"]), 2)

    def test_should_send_blocks_duplicate_day(self):
        state = {"_last_sent": "2026-10-23"}
        old_force = os.environ.get("FORCE")
        os.environ.pop("FORCE", None)
        try:
            with unittest.mock.patch("culture_agent.datetime") as mock_dt:
                mock_dt.now.return_value = __import__("datetime").datetime(2026, 10, 23, 9, 0, 0)
                mock_dt.side_effect = lambda *args, **kwargs: __import__("datetime").datetime(*args, **kwargs)
                self.assertFalse(culture_agent.should_send(state))
        finally:
            if old_force is None:
                os.environ.pop("FORCE", None)
            else:
                os.environ["FORCE"] = old_force

    def test_entry_id_is_stable(self):
        today = __import__("datetime").date(2026, 10, 23)
        self.assertEqual(f"{today:%Y%m%d}-art", "20261023-art")


if __name__ == "__main__":
    unittest.main()
