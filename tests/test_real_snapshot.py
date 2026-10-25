"""Regression tests against REAL Chroma 1.5.9 stores copied into snapshots/ and controls/ (skipped when absent)."""
import glob
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
from hnswaudit.audit import audit


def run_cli(s):
    return subprocess.run([sys.executable, "-m", "hnswaudit", "audit", s], cwd=ROOT, capture_output=True, text=True)


def seg(pattern):
    m = glob.glob(os.path.join(ROOT, pattern))
    return m[0] if m else None


class RealChroma(unittest.TestCase):
    def test_default_config_snapshot_is_not_settled(self):
        s = seg("snapshots/churn-seed3/*-*-*-*-*")
        if not s:
            self.skipTest("snapshot not present")
        rep, _ = audit(s)
        self.assertEqual(rep["status"], "NOT_SETTLED")
        self.assertEqual(rep["findings"], [])
        self.assertIsNone(rep["summary"]["unreachable_proven"])
        self.assertEqual(rep["operational"]["pending_operations"], 600)
        self.assertEqual((rep["operational"]["vector_segment_watermark"], rep["operational"]["metadata_segment_seq"]), (6000, 6600))
        po = rep["persisted_observations"]  # descriptive only
        self.assertEqual((po["nodes"], po["live"], po["unreachable_proven"], po["tombstone_dependent"]), (4000, 2000, 0, 9))
        self.assertEqual(run_cli(s).returncode, 2)

    def test_settled_churn_snapshot_proves_three_orphans(self):
        s = seg("snapshots/churn-seed3-sync100/*-*-*-*-*")
        if not s:
            self.skipTest("snapshot not present")
        rep, _ = audit(s)
        self.assertEqual(rep["status"], "OK")
        self.assertEqual(rep["operational"]["pending_operations"], 0)
        by = {}
        for f in rep["findings"]:
            by.setdefault(f["class"], []).append(int(f["id"]))
        self.assertEqual(sorted(by["UNREACHABLE_PROVEN"]), [1051, 1442, 1538])
        self.assertEqual(sorted(by["TOMBSTONE_DEPENDENT"]), sorted([446, 778, 1779, 1865, 1903, 2207, 2697, 2784, 2956, 3458, 3489, 3501, 3593, 3792, 3867]))
        self.assertEqual(run_cli(s).returncode, 1)

    def test_settled_insert_only_control_has_one_orphan(self):
        s = seg("snapshots/control-seed3/*-*-*-*-*")
        if not s:
            self.skipTest("snapshot not present")
        rep, _ = audit(s)
        self.assertEqual(rep["status"], "OK")
        self.assertEqual([int(f["id"]) for f in rep["findings"] if f["class"] == "UNREACHABLE_PROVEN"], [2824])

    def test_audit_equals_engine_misses_in_fresh_process_sweeps(self):
        s = seg("snapshots/churn-seed3-sync100/*-*-*-*-*")
        eng = [os.path.join(ROOT, "evidence/engine", n) for n in ("sync100-A.json", "sync100-B.json")]
        if not s or not all(os.path.exists(e) for e in eng):
            self.skipTest("evidence not present")
        proven = sorted(int(f["id"]) for f in audit(s)[0]["findings"] if f["class"] == "UNREACHABLE_PROVEN")
        for e in eng:
            self.assertEqual(sorted(json.load(open(e))["full_sweep_missing"]), proven)

    def test_planted_orphan_on_real_engine_is_flagged_exactly(self):
        s = seg("controls/run1/planted-42/*-*-*-*-*")
        if not s:
            self.skipTest("control not present (run repro/control.py)")
        rep, _ = audit(s)
        self.assertEqual([int(f["id"]) for f in rep["findings"] if f["class"] == "UNREACHABLE_PROVEN"], [42])
        self.assertEqual(rep["operational"]["pending_operations"], 0)

    def test_untouched_control_has_no_findings(self):
        s = seg("controls/run1/untouched/*-*-*-*-*")
        if not s:
            self.skipTest("control not present")
        rep, _ = audit(s)
        self.assertEqual(rep["summary"]["unreachable_proven"], 0)


if __name__ == "__main__":
    unittest.main()
