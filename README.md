# FERDON / hnswaudit

Read-only audit of a persisted Chroma 1.5.9 HNSW segment. It lists the live IDs that no graph search can reach at any `k` or `ef`,
proven from the graph in the files, under hnswlib's search rules as read from its source (not from the Chroma 1.5.9 binary; see
[`SOUNDNESS.md`](SOUNDNESS.md) §2). If the files do not represent the whole store, it says so and gives no verdict.

Setup, from the repository root: Python ≥ 3.10 and `python3 -m pip install numpy` (`scipy` is optional, for SCC counts). First run, from the same
directory:

```bash
python3 -m hnswaudit audit snapshots/churn-seed3-sync100/038ea505-c6a6-42e1-b1f7-0bb553f34c89 --json hero.json --html hero.html
```

It writes `hero.json` and `hero.html` in the current directory; a second run needs `--force`. The `path` in a fresh JSON report is the segment or file basename, so the report is portable; its input-file hashes are the real ones. Exit code `1` means unreachable live IDs were found.

|  |  |
|---|---|
| Input | a stopped, copied Chroma 1.5.9 store (never audit a live one) |
| Returns | per live ID: `UNREACHABLE_PROVEN`, `TOMBSTONE_DEPENDENT` or `REACHABLE_NOT_CLAIMED` |
| Refuses | when queued operations are not in the HNSW files, the id map disagrees, or the format is unsupported |
| Does not | call the Chroma API, write to the snapshot, repair, rebuild, or estimate recall or prevalence |
| Method | [`SOUNDNESS.md`](SOUNDNESS.md) |

## Result

The example is a settled Chroma 1.5.9 store: 4,000 seeded-random 32-d vectors, 2,000 deleted, 600 upserted, seed 3, built with
`hnsw:sync_threshold=100` so the HNSW files hold every operation. It follows the recipe in
[chroma-core/chroma#7758](https://github.com/chroma-core/chroma/issues/7758) (live records `query()` never returns while `get()` does);
it is our re-implementation, not the issue's script. The vectors are synthetic and were run through the real engine.

Output, abbreviated (the real run also prints a `verdict` line, an `api` line and up to ten findings):

```
status   : OK
layout   : chroma   nodes 4000   live 2000
findings : UNREACHABLE_PROVEN=3  TOMBSTONE_DEPENDENT=15  reachable_not_claimed=1982
  UNREACHABLE_PROVEN   id='1051'  label=1052  in-edges(L0)=0  no node has a layer-0 edge to it
  UNREACHABLE_PROVEN   id='1442'  label=1443  in-edges(L0)=0  ...
  UNREACHABLE_PROVEN   id='1538'  label=1539  in-edges(L0)=0  ...
```

`status OK` means the snapshot parsed and was settled (0 pending operations). It does not mean the index is healthy.
The HTML report is self-contained (no network, but it needs JavaScript) and shows the same result with the in-edges of each ID; a saved copy is
`evidence/churn-seed3-sync100.audit.html`. Its table abbreviates `TOMBSTONE_DEPENDENT` to `TOMBSTONE_DEP`.

The 15 tombstone-dependent IDs are a different class: reachable only by routing through deleted nodes. No claim is made that they are lost.

## Engine check

Fresh-process runs of the real Chroma 1.5.9 API on copies of the settled snapshot: `query()` with each live ID's own vector at
`n_results=1000`. The five HNSW files in copy A match the shipped snapshot byte for byte; SQLite did not, and equivalent file hashes
for copy B were not recorded.

```bash
python3 repro/compare_engine.py snapshots/churn-seed3-sync100/038ea505-c6a6-42e1-b1f7-0bb553f34c89 \
        evidence/engine/sync100-A.json evidence/engine/sync100-B.json
```

| | audit (files only) | engine, process A | engine, process B |
|---|---|---|---|
| IDs missed | 1051, 1442, 1538 | 1051, 1442, 1538 | 1051, 1442, 1538 |

All three are also absent at every tested `n_results` up to 4,000 (more than the live count). In every comparison made, each proven ID was
missed by the engine. In the process that built the store, `get()` returned each of the IDs missed at `n_results=1000`
(`evidence/churn-seed3-sync100.build.json`). Raw outputs are in `evidence/engine/`; [`evidence/ENGINE-PROBE.md`](evidence/ENGINE-PROBE.md)
lists what was run and what each file shows.

An insert-only store from the same seed (`snapshots/control-seed3`, no deletes or upserts) also has a proven unreachable ID (`2824`),
engine-confirmed. That one store shows churn is not required for an unreachable node. These three IDs have zero layer-0 in-edges, the isolated-node case described in
[nmslib/hnswlib#352](https://github.com/nmslib/hnswlib/issues/352).

## Refusal

`snapshots/churn-seed3/` is the same workload with Chroma's default `sync_threshold`. The HNSW files are at seq 6000 and the store is at 6600
(600 upserts only in SQLite's queue), so the files do not contain every committed operation and no verdict is given. Two fresh processes on
copies of the same snapshot returned different query results; the cause was not traced (see [`evidence/ENGINE-PROBE.md`](evidence/ENGINE-PROBE.md)).

```bash
python3 -m hnswaudit audit snapshots/churn-seed3/8f729af2-7352-4293-99e8-6f4f4f005de8 --json refused.json
```

```
status   : NOT_SETTLED (... 600 queued operation(s) ...; metadata segment seq 6600 > vector segment seq 6000)
verdict  : NO CERTIFICATE (NOT_SETTLED): the effective-store graph is unknown; structural counts below describe the persisted files only ...
persisted-files-only (descriptive, NOT a verdict): unreachable_proven=0 tombstone_dependent=9 reachable_not_claimed=1991
```

Exit code `2`, no per-ID verdict. The persisted-only counts stay in the JSON as description. The refusal is covered by `tests/test_audit_cli.py` and `tests/test_real_snapshot.py`.

## Exit codes and statuses

`0` no structurally unreachable live IDs · `1` unreachable live IDs found · `2` no verdict · `3` usage error (including an existing output file without `--force`).
A missing subcommand also exits `2` (argparse). Refusal statuses: `UNSUPPORTED_OR_CORRUPT`, `INCONSISTENT_SNAPSHOT`, `NOT_SETTLED`, `SETTLEMENT_UNKNOWN`, `OK_NO_IDMAP`, `SNAPSHOT_CHANGED_DURING_AUDIT`.

## Reading order

1. [`SOUNDNESS.md`](SOUNDNESS.md): the claim and its assumptions.
2. `hnswaudit/layout.py`: strict parse of the persisted files; anything unexpected is refused.
3. `hnswaudit/reach.py`: the reachability computation and the three classes.
4. `hnswaudit/audit.py`: id map, settledness, findings, status. `chroma_sqlite.py` and `safepickle.py` are its read-only inputs.
5. `hnswaudit/cli.py` and `html_report.py`: output only.
6. `tests/`: `fixtures.py` builds small graphs; `test_core.py` covers reachability, `test_audit_cli.py` refusals and exit codes,
   `test_real_snapshot.py` the committed stores.

## Checks

```bash
python3 -W ignore -m unittest discover -s tests -q
python3 repro/control.py --chroma-python /path/to/python-with-chromadb-1.5.9 --work controls/run1
```

The second command is a secondary planted-orphan control. Its recorded run is in `evidence/control-summary.json`: the audit set equals the engine's
misses (ids 42, 200, 17) and the untouched copy is clean. It can be rerun with `repro/control.py` and Chroma 1.5.9; the recorded run's inputs are not
included, so a rerun builds a new store. `controls/` is regenerated, not committed. Full evidence index and unknowns: `evidence/RECEIPT.md`.

## Limits

* Chroma 1.5.9 only (persistence version 1, 100-byte header, its SQLite schema). Other versions fail closed or are untested. The vanilla
  hnswlib layout is implemented from source and unit fixtures and has never been run on a real hnswlib file.
* One seeded workload per scenario on one host; engine confirmation is for seed 3 only. No prevalence claim.
* The claims are about graph semantics of settled files. Chroma may answer some queries by other paths (brute force over small or
  filtered candidate sets); those are not covered. Three other IDs missed in the building process (446, 3458, 3501) are
  `TOMBSTONE_DEPENDENT` in the audit. In the fresh processes 446 is returned at every tested `n_results`, and 3458 and 3501 from 500 upward
  (`evidence/engine/sync100-A.json`, `sync100-B.json`).
* The traversal model comes from hnswlib source, not the 1.5.9 binary. Atomic-flush consistency of the five files is not provable from hashes.
* `length.bin` is only size-checked (at least 4 bytes per element); its contents are not interpreted or validated.
* Largest store audited: 4,000 nodes (about 0.6 s). No scale or memory benchmark.
* Remedy not verified: no rebuild was run, an insert-only build also produced an orphan, and re-upserting an orphan was not tested.

## Related

* [chroma#7758](https://github.com/chroma-core/chroma/issues/7758) reports the symptom above. PR #7845 proposes a query fallback; it does not change the graph.
* hnswlib's `checkIntegrity()` (on load since Chroma #3369) checks range, self-loops and duplicates; its in-degree check is an `assert` and
  not a walk from the entry point. Whether it is active in 1.5.9 or would flag these IDs was not tested.
* `chromadb-ops` (source read, not run) reports a deleted-ratio fragmentation figure and has no reachability analysis.

## Licences

* **Code:** the original software (`hnswaudit/*.py`, `repro/`, `tests/`) is MIT licensed, see `LICENSE`.
* **Artifacts:** the synthetic snapshots in `snapshots/` and the raw engine outputs and sample report data in `evidence/` are not covered by the MIT
  licence; they are included for reproducible review.
* **Fonts:** TeX Gyre Heros Regular and Bold in `hnswaudit/fonts/` keep their own terms (GUST Font License, with LPPL 1.3c), see `NOTICE.md`.
