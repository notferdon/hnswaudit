import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))

from fixtures import graph, write_chroma, write_chroma_sqlite, write_vanilla
from hnswaudit import safepickle
from hnswaudit.audit import audit
from hnswaudit.html_report import render

TOMB = graph(adj0={0: [1, 2], 1: [0, 3], 2: [0], 3: [5], 4: [1], 5: [0]}, deleted=[3])


def run_cli(*args):
    return subprocess.run([sys.executable, "-m", "hnswaudit", *args], cwd=ROOT, capture_output=True, text=True)


def cli_status(r):
    for line in r.stdout.splitlines():
        if line.startswith("status   :"):
            return line.split(":", 1)[1].split()[0]
    return None


def tree_hash(p):
    h = hashlib.sha256()
    files = [p] if os.path.isfile(p) else sorted(os.path.join(p, n) for n in os.listdir(p))
    for f in files:
        with open(f, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()


class AuditReport(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)

    def test_report_findings_and_ids(self):
        p = write_vanilla(os.path.join(self.d, "i.idx"), **TOMB)
        rep, _ = audit(p)
        self.assertEqual(rep["status"], "OK")
        by = {f["id"]: f for f in rep["findings"]}
        self.assertEqual(by[104]["class"], "UNREACHABLE_PROVEN")
        self.assertEqual(by[105]["class"], "TOMBSTONE_DEPENDENT")
        self.assertEqual(rep["summary"]["unreachable_proven"], 1)
        self.assertEqual(by[104]["in_neighbours_layer0"], [])
        self.assertNotIn("REBUILD INDICATED", rep["summary"]["verdict"])
        self.assertIn("not verified", rep["summary"]["verdict"].replace("has not verified", "not verified"))
        self.assertNotIn("ef or filter", rep["summary"]["verdict"])  # no any-filter guarantee
        self.assertTrue(by[105]["in_neighbours_layer0"][0]["deleted"])
        json.dumps(rep)  # serialisable

    def test_cli_exit_codes_and_outputs(self):
        p = write_vanilla(os.path.join(self.d, "i.idx"), **TOMB)
        before = tree_hash(p)
        out_j, out_h = os.path.join(self.d, "r.json"), os.path.join(self.d, "r.html")
        r = run_cli("audit", p, "--json", out_j, "--html", out_h)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(tree_hash(p), before)  # read-only
        self.assertIn("UNREACHABLE_PROVEN=1", r.stdout)
        self.assertEqual(cli_status(r), "OK")
        data = json.load(open(out_j))
        self.assertEqual(data["schema"], "hnswaudit.report/1")
        html = open(out_h).read()
        self.assertIn('id="data"', html)
        self.assertNotIn("http://", html.replace("http://www.w3.org", ""))  # no remote assets
        self.assertNotIn("<script src", html)
        # refuse overwrite and writing into snapshot
        self.assertEqual(run_cli("audit", p, "--json", out_j).returncode, 3)

    def test_nonexistent_snapshot_never_reports_unreachable(self):
        path = os.path.join(self.d, "does-not-exist.idx")
        r = run_cli("audit", path)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("snapshot not found", r.stderr)
        self.assertIsNone(cli_status(r))
        self.assertNotIn("UNREACHABLE_PROVEN", r.stdout)

    def test_report_write_failure_never_reports_unreachable(self):
        p = write_vanilla(os.path.join(self.d, "i.idx"), **TOMB)
        impossible = os.path.join(self.d, "missing-parent", "result.json")
        r = run_cli("audit", p, "--json", impossible)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("cannot audit", r.stderr)
        self.assertIsNone(cli_status(r))
        self.assertNotIn("UNREACHABLE_PROVEN", r.stdout)

    def test_missing_numpy_is_no_verdict(self):
        p = write_vanilla(os.path.join(self.d, "i.idx"), **TOMB)
        stub = os.path.join(self.d, "stub")
        os.mkdir(stub)
        open(os.path.join(stub, "numpy.py"), "w").write("raise ModuleNotFoundError('blocked', name='numpy')\n")
        env = dict(os.environ, PYTHONPATH=stub)
        r = subprocess.run([sys.executable, "-m", "hnswaudit", "audit", p], cwd=ROOT, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("missing Python dependency", r.stderr)
        self.assertIsNone(cli_status(r))

    def test_clean_graph_exit_zero(self):
        p = write_vanilla(os.path.join(self.d, "i.idx"), **graph(n=4, adj0={0: [1], 1: [2], 2: [3], 3: [0]}))
        r = run_cli("audit", p)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_refused_snapshot_exit_two_without_findings(self):
        p = write_vanilla(os.path.join(self.d, "i.idx"), **TOMB)
        with open(p, "ab") as f:
            f.write(b"junk")
        out_j = os.path.join(self.d, "r.json")
        r = run_cli("audit", p, "--json", out_j)
        self.assertEqual(r.returncode, 2)
        rep = json.load(open(out_j))
        self.assertEqual(rep["status"], "UNSUPPORTED_OR_CORRUPT")
        self.assertEqual(rep["findings"], [])
        self.assertIn("NO VERDICT", rep["summary"]["verdict"])

    def test_chroma_without_idmap_makes_no_live_claim(self):
        p = write_chroma(os.path.join(self.d, "seg"), **TOMB)
        write_chroma_sqlite(self.d, "seg")  # settled store, but no index_metadata.pickle
        rep, _ = audit(p)
        self.assertEqual(rep["status"], "OK_NO_IDMAP")
        self.assertEqual(run_cli("audit", p).returncode, 2)
        self.assertEqual(rep["findings"], [])
        self.assertEqual(rep["summary"]["live"], 0)
        self.assertIn("CONSERVATIVE", rep["summary"]["verdict"])
        self.assertEqual(rep["native_unreachable"], [104])

    def test_html_escapes_script_close(self):
        rep, _ = audit(write_vanilla(os.path.join(self.d, "i.idx"), **TOMB))
        rep["path"] = "</script><b>x"
        html = render(rep)
        self.assertEqual(html.count("</script>"), 2)  # data block + code block only


def chroma_with_map(d, kw, id_to_label, dim=2, settled=True):
    import pickle
    seg = write_chroma(os.path.join(d, "seg"), **kw)
    meta = {"dimensionality": dim, "total_elements_added": len(id_to_label), "max_seq_id": 7,
            "id_to_label": id_to_label, "label_to_id": {v: k for k, v in id_to_label.items()}}
    with open(os.path.join(seg, "index_metadata.pickle"), "wb") as f:
        pickle.dump(meta, f, protocol=4)
    if settled:
        write_chroma_sqlite(d, "seg", ids=list(id_to_label))
    return seg


class ChromaIdMap(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)

    def test_consistent_map_reports_user_ids_and_graph_only_claim(self):
        live = {"a": 100, "b": 101, "c": 102, "e": 104, "f": 105}  # label 103 is the tombstone, not mapped
        seg = chroma_with_map(self.d, TOMB, live)
        rep, _ = audit(seg)
        self.assertEqual(rep["status"], "OK")
        by = {f["id"]: f for f in rep["findings"]}
        self.assertEqual(by["e"]["class"], "UNREACHABLE_PROVEN")
        self.assertEqual(by["f"]["class"], "TOMBSTONE_DEPENDENT")
        self.assertNotIn("get()", rep["summary"]["verdict"])
        self.assertTrue(rep["api_status"].startswith("UNKNOWN"))
        self.assertEqual(rep["snapshot_consistency"]["atomic_flush"], "UNPROVEN")

    def _refused(self, id_to_label, kw=TOMB, dim=2):
        rep, _ = audit(chroma_with_map(self.d, kw, id_to_label, dim))
        self.assertEqual(rep["status"], "INCONSISTENT_SNAPSHOT", rep.get("reason"))
        self.assertEqual(rep["findings"], [])
        self.assertIn("NO CERTIFICATE", rep["summary"]["verdict"])
        self.assertIsNone(rep["summary"]["unreachable_proven"])
        return rep

    def test_mapped_but_tombstoned_refuses_everything(self):
        self._refused({"a": 100, "b": 101, "c": 102, "d": 103, "e": 104, "f": 105})

    def test_native_live_without_id_refuses(self):
        self._refused({"a": 100, "b": 101, "c": 102, "e": 104})

    def test_mapped_label_missing_in_graph_refuses(self):
        self._refused({"a": 100, "b": 101, "c": 102, "e": 104, "f": 105, "ghost": 999})

    def test_dimension_mismatch_refuses(self):
        self._refused({"a": 100, "b": 101, "c": 102, "e": 104, "f": 105}, dim=7)

    def test_cli_exit_two_on_inconsistency(self):
        seg = chroma_with_map(self.d, TOMB, {"a": 100})
        self.assertEqual(run_cli("audit", seg).returncode, 2)

    def test_hostile_pickle_refused_without_execution(self):
        import pickle

        class Evil:
            def __reduce__(self):
                return (os.system, ("echo pwned > /tmp/hnswaudit_pwned2",))

        seg = write_chroma(os.path.join(self.d, "seg"), **TOMB)
        write_chroma_sqlite(self.d, "seg")  # settled store, so the only open problem is the refused id map
        with open(os.path.join(seg, "index_metadata.pickle"), "wb") as f:
            pickle.dump(Evil(), f)
        rep, _ = audit(seg)
        self.assertEqual(rep["status"], "OK_NO_IDMAP")
        self.assertFalse(os.path.exists("/tmp/hnswaudit_pwned2"))
        self.assertEqual(rep["findings"], [])


class Settledness(unittest.TestCase):
    LIVE = {"a": 100, "b": 101, "c": 102, "e": 104, "f": 105}

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)

    def _check_refused(self, rep, status):
        self.assertEqual(rep["status"], status)
        self.assertEqual(rep["findings"], [])
        self.assertIsNone(rep["summary"]["unreachable_proven"])
        self.assertIn("NO CERTIFICATE", rep["summary"]["verdict"])
        self.assertNotIn("REBUILD", rep["summary"]["verdict"])
        # persisted-only structure is preserved as DESCRIPTIVE observations, not a verdict
        self.assertEqual(rep["persisted_observations"]["unreachable_proven"], 1)
        self.assertEqual({f["id"] for f in rep["persisted_only_findings"] if f["class"] == "UNREACHABLE_PROVEN"}, {"e"})

    def test_pending_queue_is_not_settled(self):
        seg = chroma_with_map(self.d, TOMB, self.LIVE, settled=False)
        write_chroma_sqlite(self.d, "seg", watermark=10, meta_seq=12, queue_seqs=(11, 12), ids=list(self.LIVE))
        rep, _ = audit(seg)
        self._check_refused(rep, "NOT_SETTLED")
        self.assertEqual(rep["operational"]["pending_operations"], 2)
        r = run_cli("audit", seg)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(cli_status(r), "NOT_SETTLED")
        self.assertIn("descriptive", r.stdout)

    def test_metadata_segment_ahead_is_not_settled(self):
        seg = chroma_with_map(self.d, TOMB, self.LIVE, settled=False)
        write_chroma_sqlite(self.d, "seg", watermark=10, meta_seq=15, queue_seqs=(10,), ids=list(self.LIVE))
        rep, _ = audit(seg)
        self._check_refused(rep, "NOT_SETTLED")

    def test_unreadable_sqlite_is_settlement_unknown(self):
        seg = chroma_with_map(self.d, TOMB, self.LIVE, settled=False)  # no chroma.sqlite3 at all
        rep, _ = audit(seg)
        self._check_refused(rep, "SETTLEMENT_UNKNOWN")

    def test_hot_journal_is_settlement_unknown(self):
        seg = chroma_with_map(self.d, TOMB, self.LIVE)
        open(os.path.join(self.d, "chroma.sqlite3-journal"), "wb").write(b"x")
        rep, _ = audit(seg)
        self._check_refused(rep, "SETTLEMENT_UNKNOWN")

    def test_settled_store_still_certifies(self):
        rep, _ = audit(chroma_with_map(self.d, TOMB, self.LIVE))
        self.assertEqual(rep["status"], "OK")
        self.assertEqual(rep["summary"]["unreachable_proven"], 1)
        self.assertEqual(rep["operational"]["pending_operations"], 0)

    def test_html_marks_descriptive_only(self):
        seg = chroma_with_map(self.d, TOMB, self.LIVE, settled=False)
        write_chroma_sqlite(self.d, "seg", watermark=10, meta_seq=12, queue_seqs=(11, 12), ids=list(self.LIVE))
        html = render(audit(seg)[0])
        self.assertIn("Descriptive only", html)
        self.assertIn("NOT_SETTLED", html)


class Surface(unittest.TestCase):
    """Release surface is `audit` and `version` only; the experimental reconcile/simulate tooling is not shipped."""

    def test_reconcile_is_not_a_command(self):
        r = run_cli("reconcile", "x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("invalid choice", r.stderr)
        self.assertNotIn("reconcile", run_cli("--help").stdout)

    def test_experimental_modules_are_gone(self):
        pkg = os.path.join(ROOT, "hnswaudit")
        for n in ("reconcile.py", "simulate.py"):
            self.assertFalse(os.path.exists(os.path.join(pkg, n)), n)

    def test_audit_and_version_remain(self):
        self.assertEqual(run_cli("version").returncode, 0)
        self.assertIn("audit", run_cli("--help").stdout)


class ReportPrivacy(unittest.TestCase):
    """The report is meant to be shared: it must not carry the auditor's absolute paths."""

    def test_json_path_is_the_segment_basename_and_no_absolute_root_leaks(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        d = os.path.join(root, "private-user-dir")
        os.makedirs(d)
        seg = chroma_with_map(d, TOMB, {"a": 100, "b": 101, "c": 102, "e": 104, "f": 105})
        out = os.path.join(root, "r.json")
        r = run_cli("audit", os.path.abspath(seg) + os.sep, "--json", out)  # trailing slash: normalised basename still "seg"
        self.assertEqual(r.returncode, 1, r.stderr)
        text = open(out).read()
        rep = json.loads(text)
        self.assertEqual(rep["path"], "seg")
        self.assertNotIn(root, text)
        self.assertNotIn("private-user-dir", text)
        self.assertNotIn(os.path.expanduser("~"), text)
        want = {n: hashlib.sha256(open(os.path.join(seg, n), "rb").read()).hexdigest() for n in os.listdir(seg)}
        self.assertEqual({i["file"]: i["sha256"] for i in rep["inputs"]}, want)  # hashes unaffected

    def test_vanilla_file_path_is_basename(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        p = write_vanilla(os.path.join(root, "idx.bin"), **TOMB)
        rep, _ = audit(p)
        self.assertEqual(rep["path"], "idx.bin")


class EngineWording(unittest.TestCase):
    """Claims stay at what was measured: structure under a stated model; a sequence gap, not an asserted mechanism."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)

    def test_assumptions_scope_the_unreachable_claim_to_graph_search(self):
        rep, _ = audit(chroma_with_map(self.d, TOMB, {"a": 100, "b": 101, "c": 102, "e": 104, "f": 105}))
        text = " ".join(rep["engine_assumptions"])
        self.assertNotIn("no query can return it", text)
        self.assertIn("under the stated traversal model, no graph search can visit or return", text)
        self.assertIn("brute-force", text)
        self.assertIn("not measured", text)

    def test_not_settled_reports_the_gap_and_does_not_assert_a_mechanism(self):
        live = {"a": 100, "b": 101, "c": 102, "e": 104, "f": 105}
        seg = chroma_with_map(self.d, TOMB, live, settled=False)
        write_chroma_sqlite(self.d, "seg", watermark=10, meta_seq=12, queue_seqs=(11, 12), ids=list(live))
        rep, _ = audit(seg)
        self.assertEqual(rep["status"], "NOT_SETTLED")
        reason = rep["reason"]
        self.assertIn("2 queued operation(s) newer than the vector segment watermark", reason)
        self.assertIn("metadata segment seq 12 > vector segment seq 10", reason)  # the objective sequence gap, unchanged
        self.assertIn("sequence gap", reason)
        self.assertIn("cannot be certified from the persisted files alone", reason)
        self.assertNotRegex(reason + rep["summary"]["verdict"], r"(?i)replay")
        self.assertNotRegex(reason + rep["summary"]["verdict"], r"(?i)inference|may apply|opens the store|when it opens")  # no mechanism, not even hedged
        self.assertTrue(reason.endswith("cannot be certified from the persisted files alone"), reason)
        self.assertEqual(rep["summary"]["verdict"].split(":")[0], "NO CERTIFICATE (NOT_SETTLED)")

    def test_source_does_not_assert_replay_as_fact(self):
        import hnswaudit.audit as m
        self.assertNotRegex(open(m.__file__).read(), r"(?i)replay")


class SpecialPaths(unittest.TestCase):
    """The SQLite URI must be built from an escaped path: no stray files, no wrong-store reads."""
    LIVE = {"a": 100, "b": 101, "c": 102, "e": 104, "f": 105}

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)

    def _store(self, name):
        d = os.path.join(self.root, name)
        os.makedirs(d)
        return chroma_with_map(d, TOMB, self.LIVE)

    def test_uri_special_characters_do_not_create_files_or_change_result(self):
        for name in ("x y", "x#y", "x?y", "x%41y", "x%2Fy"):
            with self.subTest(name=name):
                seg = self._store(name)
                before = sorted(os.listdir(self.root))
                rep, _ = audit(seg)
                self.assertEqual(sorted(os.listdir(self.root)), before)  # nothing created beside the snapshot dir
                self.assertEqual(rep["status"], "OK", rep.get("reason"))
                self.assertEqual(rep["summary"]["unreachable_proven"], 1)
                self.assertEqual(rep["operational"]["pending_operations"], 0)

    def test_percent_escape_does_not_read_a_sibling_store(self):
        decoy = os.path.join(self.root, "xAy")  # what an unescaped "%41" would decode to; deliberately NOT settled
        os.makedirs(decoy)
        chroma_with_map(decoy, TOMB, self.LIVE, settled=False)
        write_chroma_sqlite(decoy, "seg", watermark=10, meta_seq=12, queue_seqs=(11, 12), ids=list(self.LIVE))
        own = self._store("x%41y")  # settled; must be judged by its own sqlite, not the decoy's
        rep, _ = audit(own)
        self.assertEqual(rep["status"], "OK", rep.get("reason"))


class SafePickle(unittest.TestCase):
    def test_plain_dict_roundtrip(self):
        import pickle
        o = {"id_to_label": {"a": 1, "b": 2}, "label_to_id": {1: "a", 2: "b"}, "dimensionality": 4}
        for proto in (2, 3, 4, 5):
            self.assertEqual(safepickle.loads(pickle.dumps(o, protocol=proto)), o)

    def test_refuses_code_execution_payloads(self):
        import pickle

        class Evil:
            def __reduce__(self):
                return (os.system, ("echo pwned > /tmp/hnswaudit_pwned",))

        for proto in (0, 2, 4):
            with self.assertRaises(safepickle.PickleRefused):
                safepickle.loads(pickle.dumps(Evil(), protocol=proto))
        self.assertFalse(os.path.exists("/tmp/hnswaudit_pwned"))

    def test_refuses_truncated_and_unknown(self):
        import pickle
        with self.assertRaises(safepickle.PickleRefused):
            safepickle.loads(pickle.dumps({"a": 1})[:-3])
        with self.assertRaises(safepickle.PickleRefused):
            safepickle.loads(b"\x80\x04\x95\x00\x00\x00\x00\x00\x00\x00\x00\x91.")  # FROZENSET opcode not allow-listed


if __name__ == "__main__":
    unittest.main()
