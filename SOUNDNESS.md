# Soundness and format assumptions

This file restates what `hnswaudit/reach.py`, `hnswaudit/layout.py` and `hnswaudit/audit.py` do and what has to be true for their
output to mean what the README says. It introduces no new theorem: each step is a line of code you can read. What was *not*
established is listed at the end.

## 1. The claim

For a **settled** Chroma 1.5.9 segment, a live ID classed `UNREACHABLE_PROVEN` is never visited by an HNSW graph search over the
persisted graph, at any `ef`, `k`, filter or distance metric. The claim is about the **persisted graph** only. It is not a statement
about what `query()` returns: Chroma may answer some queries by other paths (for example brute force over small or filtered candidate
sets), and the API is never called by the tool.

## 2. The search model the tool assumes

Taken from reading hnswlib's `searchKnn` / `searchBaseLayerST` (`chroma-core/hnswlib` rev `e6db8c2`, `nmslib/hnswlib` rev `ca42672`).
The `chroma-core/hnswlib` revision `e6db8c2` is dated 2026-10-05, after the Chroma 1.5.9 tag commit (2026-05-04), so it is not shown to be the source
that 1.5.9 was built from. This is **not** a reading of the 1.5.9 binary: whether that binary traverses identically is unverified, and no
compatibility with other Chroma versions is claimed.

1. Start at the header's `enterpoint`, which sits at `maxlevel`.
2. For each layer `maxlevel .. 1`, greedily move to a neighbour along *that layer's* edges while it is closer to the query.
3. At layer 0, run a beam search from the node that descent ended on. It only ever visits neighbours of nodes it has expanded.
   Deleted (tombstoned) nodes are expanded like any other; they are only withheld from the result set.

## 3. The computation (`reach.analyse`)

* **Entry envelope.** Start with `{enterpoint}`. For each layer `maxlevel .. 1`, replace the set with everything reachable from it along
  that layer's edges, **ignoring the "strictly closer" rule**. A real greedy descent only moves along edges, so the node it ends on is
  always in this set. It over-approximates the possible layer-0 start nodes.
* **`reach0`.** The directed forward closure of the envelope along layer-0 edges, with deleted nodes expanded. Any node a layer-0
  beam search visits is a neighbour of an expanded node, so it lies in this set.
* **`reach0_live`.** The same closure, except deleted nodes are visited but not expanded.
* **Classes, for live IDs only** (`reach.classify`):
  * `UNREACHABLE_PROVEN`: live and not in `reach0`. By the two bullets above, no graph search visits it.
  * `TOMBSTONE_DEPENDENT`: in `reach0` but not in `reach0_live`. Reachable only by routing through deleted nodes. No claim is made that
    it is unreachable, only that it stops being reachable if tombstones stop being traversed (for example after compaction).
  * `REACHABLE_NOT_CLAIMED`: in `reach0_live`. Necessary, not sufficient, for retrieval: a particular query can still miss it (beam
    width, filters).
* **Layer-0 in-degree** is reported next to each finding but is not part of the proof. A node can have in-edges and still be outside
  `reach0` (a side component); the three IDs in the README example have zero layer-0 in-edges, which is a stronger observation than the
  closure needs.
* **Live** means not tombstoned in the graph *and* present in Chroma's id map (`index_metadata.pickle`). With no readable id map the tool
  makes no live-ID claim at all.

Why filters, `ef`, `k` and the metric cannot matter: they only prune what a search visits or returns; none of them can add an edge.

## 4. Preconditions the tool checks before it speaks

* **Strict format.** Chroma persistence version 1, a 100-byte header, little-endian LP64 only, and header fields that agree with each
  other and with the file sizes (`layout._validate_header`, `load_chroma`). Level-0 and upper-layer neighbour counts are within
  `maxM0`/`maxM`, all neighbour IDs are in range, upper-layer edges point to nodes that exist at that layer, the entry point is at
  `maxlevel`, native labels are unique. `length.bin` is only checked for size (at least 4 bytes per element); its contents are not read. Anything else raises `FormatError` and the status is `UNSUPPORTED_OR_CORRUPT`, with no verdict.
* **No code execution from the snapshot.** `index_metadata.pickle` is parsed symbolically with an allow-list; anything else is refused
  (`safepickle`). `chroma.sqlite3` is opened `mode=ro&immutable=1` and only ever on a copy; a `-wal`, `-shm` or `-journal` sidecar is a
  refusal.
* **Id map and graph agree** (no mapped-but-tombstoned label, no live native label without an id, no mapped label absent from the
  graph, matching dimensionality), otherwise `INCONSISTENT_SNAPSHOT`.
* **Settled.** The vector segment's `max_seq_id` is not behind the metadata segment's, and no queue entries are newer than it. Otherwise `NOT_SETTLED`
  (or `SETTLEMENT_UNKNOWN` if SQLite cannot be read). The persisted files then do not contain every committed operation, so no verdict is given;
  the counts are kept only as a labelled description.
* **Files unchanged while auditing** (sha-256 before and after), otherwise `SNAPSHOT_CHANGED_DURING_AUDIT`.

## 5. What is not established

* That Chroma 1.5.9's traversal matches the hnswlib source revisions above.
* The contents of `length.bin` (size-checked only), and any corruption inside `data_level0.bin` or `link_lists.bin` that leaves a structurally
  legal graph. The sha-256 table in the report records which bytes were read; it does not prove they were correct.
* That the SQLite copy is complete: a copy of a WAL-mode database made without its `-wal` file looks like a clean database. Audit a copy of a
  stopped store.
* That the five files came from one atomic flush. Equal hashes before and after only show they did not change during the audit; the
  watermark, queue and id-map checks mitigate this but do not prove it.
* Anything about vanilla hnswlib files on real data: that layout is implemented from source and unit fixtures, and has never been run on
  a real hnswlib file.
* Chroma versions other than 1.5.9, graphs larger than 4,000 nodes, and any rebuild or repair outcome.
* The engine agreement shown in `evidence/engine/` is an empirical check on one seeded workload per scenario. It supports soundness
  (every proven ID was missed by the real engine) and does not replace the argument above.
