"""Presentation tests for the standalone HTML report (content/guards only; layout is checked by screenshots)."""
import json
import os
import re
import shutil
import tempfile
import unittest

from hnswaudit.html_report import render

SYN = {"schema": "hnswaudit.report/1", "version": "0", "elapsed_s": 0.1, "layout": "chroma", "inputs": [{"file": "header.bin", "bytes": 100, "sha256": "ab" * 32}],
       "path": "/home/someone/Downloads/secret/seg-uuid", "status": "OK", "engine_assumptions": [], "not_checked": [],
       "operational": {"sqlite": "read", "vector_segment_watermark": 5, "metadata_segment_seq": 5, "queue_max_seq": 5, "pending_operations": 0, "pending_by_op": {}, "pending_id_count": 0},
       "summary": {"nodes": 10, "live": 5, "unreachable_proven": 1, "tombstone_dependent": 1, "reachable_not_claimed": 3, "verdict": "v",
                   "envelope_size": 1, "reach0_size": 9, "reach_live_only_size": 8, "entry_internal": 0, "entry_deleted": False, "maxlevel": 1,
                   "scc_count": None, "scc_largest": None, "layer0_zero_in_degree_live": 1},
       "findings": [{"id": "a", "label": 1, "internal": 1, "class": "UNREACHABLE_PROVEN", "level": 0, "in_degree_layer0": 0, "out_degree_layer0": 2, "in_neighbours_layer0": [], "why": "no node has a layer-0 edge to it"},
                    {"id": "b", "label": 2, "internal": 2, "class": "TOMBSTONE_DEPENDENT", "level": 0, "in_degree_layer0": 1, "out_degree_layer0": 2,
                     "in_neighbours_layer0": [{"internal": 7, "label": 8, "deleted": True, "reachable": True}], "why": "reachable only by routing through deleted nodes"}]}


class HtmlReport(unittest.TestCase):
    def test_no_local_path_no_network_and_script_balance(self):
        html = render(SYN)
        self.assertNotIn("/home/someone", html)
        self.assertNotIn("Downloads", html)
        self.assertIn("seg-uuid", html)
        self.assertEqual(html.count("</script>"), 2)
        self.assertNotRegex(html, r"https?://(?!tug\.org)[^\s\"']*\.(js|css|woff2?|otf)")
        self.assertNotRegex(html, r"""(src|href)=["']https?:""")

    def test_font_is_inlined_with_licence_files_present(self):
        html = render(SYN)
        self.assertEqual(html.count("@font-face"), 2)
        self.assertIn("data:font/otf;base64,", html)
        fonts = os.path.join(os.path.dirname(__import__("hnswaudit").__file__), "fonts")
        for n in ("GUST-FONT-LICENSE.txt", "README.txt", "texgyreheros-regular.otf", "texgyreheros-bold.otf"):
            self.assertTrue(os.path.isfile(os.path.join(fonts, n)), n)

    def test_signature_and_core_sections(self):
        html = render(SYN)
        for s in ("FERDON / hnswaudit", "Verdict", "Settled", "Reach", "Selected", "Inputs (SHA-256)", "NO CERTIFICATE."):
            self.assertIn(s, html)
        self.assertNotIn("<svg", html)
        self.assertNotIn("<img", html)

    def test_refusal_is_no_certificate_and_descriptive(self):
        rep = dict(SYN, status="NOT_SETTLED", reason="behind", persisted_observations=dict(SYN["summary"]), persisted_only_findings=SYN["findings"], findings=[])
        rep["summary"] = dict(SYN["summary"], unreachable_proven=None, tombstone_dependent=None)
        html = render(rep)
        self.assertIn("Descriptive only", html)
        self.assertIn("NO CERTIFICATE.", html)
        self.assertEqual(json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))["status"], "NOT_SETTLED")

    def test_keyboard_selection_keeps_focus_and_has_visible_ring(self):
        html = render(SYN)
        self.assertIn("pick(+tr.dataset.i,true)", html)  # Enter/Space path re-focuses the rebuilt row
        self.assertIn("r.focus({preventScroll:true})", html)
        self.assertIn("tr.onclick=()=>pick(+tr.dataset.i)", html)  # mouse path does not force focus
        self.assertIn("tr.f.sel td:first-child{box-shadow:inset 2px 0 var(--fg)}", html)  # black row, white left mark
        self.assertNotIn("tr.f.sel td{background:var(--fg)", html)  # no white strip
        self.assertIn("tr.f:focus-visible{outline:1px solid var(--fg)", html)

    def test_identity_and_status_micro_caps_but_ids_keep_case(self):
        html = render(SYN)
        self.assertIn("font-weight:700;font-size:11px;letter-spacing:.08em;text-transform:uppercase", html)  # signature
        self.assertIn(".up,#status,.foot .mid{", html)
        self.assertIn("seg-uuid", html)  # path/uuid rendered outside the uppercase span
        self.assertIn("--gap:clamp(32px,3vw,48px)", html)

    def test_no_unproved_mechanism_claims_and_refusal_stays_no_certificate(self):
        pend = dict(SYN["operational"], pending_operations=2, pending_by_op={"UPSERT": 2}, pending_id_count=2, vector_segment_watermark=5, metadata_segment_seq=7)
        rep = dict(SYN, status="NOT_SETTLED", reason="gap", operational=pend, persisted_observations=dict(SYN["summary"]),
                   persisted_only_findings=SYN["findings"], findings=[])
        html = render(rep)
        self.assertNotRegex(html, r"(?i)replay")  # the renderer must not assert what Chroma does on open
        self.assertIn("a sequence gap", html)
        self.assertIn("cannot be certified from the persisted files alone", html)
        self.assertIn("NO CERTIFICATE.", html)
        self.assertIn("Descriptive only", html)
        self.assertIn("not measured by this audit", html)  # get()/query() stays explicitly unmeasured

    def test_missing_font_files_degrade_to_system_sans(self):
        import hnswaudit.html_report as m
        real = m.os.path.dirname
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        m.os.path.dirname = lambda p: d
        try:
            html = render(SYN)
        finally:
            m.os.path.dirname = real
        self.assertNotIn("@font-face{", html)
        self.assertIn("Helvetica", html)


if __name__ == "__main__":
    unittest.main()
