import os
import shutil
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np

from fixtures import graph, write_chroma, write_vanilla
from hnswaudit import layout, reach


def analyse(kw, writer=write_vanilla, name="g"):
    d = tempfile.mkdtemp()
    try:
        p = writer(os.path.join(d, name), **kw)
        g = layout.load(p)
        r = reach.analyse(g)
        cls = reach.classify(g, r, ~g.deleted)
        return g, r, cls
    finally:
        shutil.rmtree(d)


# n=6; node 4 has no in-edges; node 5 only reachable through deleted node 3
TOMB = graph(adj0={0: [1, 2], 1: [0, 3], 2: [0], 3: [5], 4: [1], 5: [0]}, deleted=[3])
# two-layer: node 3 is only reachable via node 1, which is a legal layer-0 start via layer 1
ENVELOPE = graph(n=5, levels=[1, 1, 0, 0, 0], upper={1: {0: [1], 1: [0]}}, adj0={0: [2], 1: [3], 2: [], 3: [], 4: [0]}, entry=0)


class Classes(unittest.TestCase):
    def check(self, writer):
        _, r, cls = analyse(TOMB, writer)
        self.assertEqual(cls[4], reach.UNREACHABLE_PROVEN)
        self.assertEqual(cls[5], reach.TOMBSTONE_DEPENDENT)
        for i in (0, 1, 2):
            self.assertEqual(cls[i], reach.REACHABLE_NOT_CLAIMED)
        self.assertIsNone(cls[3])  # tombstone: not a live id
        self.assertTrue(r.reach0[3] and r.reach0[5] and not r.reach0[4])

    def test_vanilla(self):
        self.check(write_vanilla)

    def test_chroma(self):
        self.check(write_chroma)

    def test_envelope_uses_upper_layers(self):
        g, r, cls = analyse(ENVELOPE)
        self.assertEqual(sorted(r.envelope.tolist()), [0, 1])
        self.assertEqual(cls[3], reach.REACHABLE_NOT_CLAIMED)  # entry-only start would wrongly flag it
        self.assertEqual(cls[4], reach.UNREACHABLE_PROVEN)

    def test_deleted_entry_all_depend_on_tombstone(self):
        kw = graph(n=3, adj0={0: [1], 1: [2], 2: []}, deleted=[0])
        _, _, cls = analyse(kw)
        self.assertEqual(cls[1], reach.TOMBSTONE_DEPENDENT)
        self.assertEqual(cls[2], reach.TOMBSTONE_DEPENDENT)

    def test_fully_connected_has_no_findings(self):
        kw = graph(n=4, adj0={0: [1], 1: [2], 2: [3], 3: [0]})
        _, r, cls = analyse(kw)
        self.assertTrue(all(c == reach.REACHABLE_NOT_CLAIMED for c in cls))
        import importlib.util
        want = (1, 4) if importlib.util.find_spec("scipy") else (None, None)  # scipy is optional: absent = "not computed"
        self.assertEqual((r.scc_count, r.scc_largest), want)

    def test_scc_reported_as_not_computed_without_scipy(self):
        import builtins
        real = builtins.__import__

        def no_scipy(name, *a, **k):
            if name.startswith("scipy"):
                raise ImportError("scipy hidden for test")
            return real(name, *a, **k)

        builtins.__import__ = no_scipy
        try:
            _, r, _ = analyse(graph(n=4, adj0={0: [1], 1: [2], 2: [3], 3: [0]}))
        finally:
            builtins.__import__ = real
        self.assertIsNone(r.scc_count)
        self.assertIsNone(r.scc_largest)

    def test_edges_only_followed_forward(self):
        # 1->0 exists but nothing points to 1 from the entry side
        kw = graph(n=2, adj0={0: [], 1: [0]})
        _, _, cls = analyse(kw)
        self.assertEqual(cls[1], reach.UNREACHABLE_PROVEN)


class FailClosed(unittest.TestCase):
    def mutate(self, writer, fn, **kw):
        d = tempfile.mkdtemp()
        try:
            p = writer(os.path.join(d, "g"), **(kw or TOMB))
            fn(p)
            with self.assertRaises(layout.FormatError):
                layout.load(p)
        finally:
            shutil.rmtree(d)

    def test_truncated_vanilla(self):
        def f(p):
            data = open(p, "rb").read()
            open(p, "wb").write(data[:-7])
        self.mutate(write_vanilla, f)

    def test_vanilla_trailing_bytes(self):
        self.mutate(write_vanilla, lambda p: open(p, "ab").write(b"x" * 8))

    def test_chroma_version(self):
        def f(p):
            h = os.path.join(p, "header.bin")
            b = bytearray(open(h, "rb").read())
            b[0] = 2
            open(h, "wb").write(b)
        self.mutate(write_chroma, f)

    def test_chroma_short_header(self):
        def f(p):
            h = os.path.join(p, "header.bin")
            open(h, "wb").write(open(h, "rb").read()[:96])
        self.mutate(write_chroma, f)

    def test_neighbour_out_of_range(self):
        def f(p):
            b = bytearray(open(p, "rb").read())
            struct.pack_into("<I", b, 96 + 4, 999)  # element 0, first neighbour slot
            open(p, "wb").write(b)
        self.mutate(write_vanilla, f)

    def test_entry_level_mismatch(self):
        def f(p):
            b = bytearray(open(p, "rb").read())
            struct.pack_into("<i", b, 48, 3)  # maxlevel field
            open(p, "wb").write(b)
        self.mutate(write_vanilla, f)

    def test_duplicate_labels(self):
        self.mutate(write_vanilla, lambda p: None, **graph(labels=[1, 1, 2, 3, 4, 5], adj0={0: [1]}))

    def test_upper_edge_to_lower_level_node(self):
        kw = graph(n=3, levels=[1, 0, 0], upper={1: {0: [1]}}, adj0={0: [1], 1: [], 2: []})
        self.mutate(write_vanilla, lambda p: None, **kw)

    def test_directory_without_header(self):
        d = tempfile.mkdtemp()
        try:
            with self.assertRaises(layout.FormatError):
                layout.load(d)
        finally:
            shutil.rmtree(d)

    def test_unknown_file(self):
        with self.assertRaises(layout.FormatError):
            layout.load("/nonexistent/path")


class LevelBound(unittest.TestCase):
    def test_huge_claimed_level_is_rejected_before_the_per_level_loop(self):
        import time
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        p = write_vanilla(os.path.join(d, "g"), **graph())
        per = 4 + 4 * 2  # maxM=2
        k = 200_000
        raw = bytearray(open(p, "rb").read())
        struct.pack_into("<I", raw, len(raw) - 4, per * k)  # last element claims k levels
        raw += b"\0" * (per * k)
        open(p, "wb").write(raw)
        real, calls = layout._upper_levels, []
        layout._upper_levels = lambda *a, **kw: calls.append(1) or real(*a, **kw)
        self.addCleanup(setattr, layout, "_upper_levels", real)
        t0 = time.time()
        with self.assertRaisesRegex(layout.FormatError, "level above maxlevel"):
            layout.load(p)
        self.assertEqual(calls, [])  # bound enforced before the O(levels x nodes) loop
        self.assertLess(time.time() - t0, 2.0)


if __name__ == "__main__":
    unittest.main()
