import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runners"))
from donsetch import parse_fetch_output


class DonsetchRunnerParseTest(unittest.TestCase):
    def test_v5_json_success(self):
        stdout = json.dumps({
            "ok": True,
            "content": "# RFC 9000\nQUIC transport",
            "meta": {"ok": True, "content_ok": True, "tokens_est": 12, "ms": 84},
        })
        res = parse_fetch_output(stdout, "", 90, 0)
        self.assertTrue(res["success"])
        self.assertEqual(res["tokens"], 12)
        self.assertEqual(res["latency_ms"], 84)
        self.assertIn("QUIC transport", res["content"])

    def test_v5_json_wall_or_404_is_not_false_positive(self):
        # Long diagnostic error JSON (>100 chars) with ok=false and rc=3 must report success=False
        stdout = json.dumps({
            "ok": False,
            "error": {"kind": "walled", "message": "blocked by interactive challenge " * 5},
            "meta": {"status": 403, "verdict": "WallChallenge"},
        })
        res = parse_fetch_output(stdout, "", 220, 3)
        self.assertFalse(res["success"])
        self.assertEqual(res["content"], "")

    def test_v5_stderr_footer_and_v4_stdout_footer_fallback(self):
        res_v5 = parse_fetch_output(
            "# Example\nShort valid page",
            "[fetch] ok · 27 chars · ~7 tokens · fetch: local · ContentOk\n",
            45,
            0,
        )
        self.assertTrue(res_v5["success"])
        self.assertEqual(res_v5["tier"], "local")
        self.assertEqual(res_v5["tokens"], 7)

        res_err = parse_fetch_output("long error body " * 20, "[fetch] error · walled\n", 50, 3)
        self.assertFalse(res_err["success"])


if __name__ == "__main__":
    unittest.main()
