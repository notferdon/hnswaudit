# Evidence receipt: hnswaudit 0.1.0

Verification recorded on 2026-10-25. The checks below distinguish executed tests, saved engine observations and unresolved questions.

## Verification run on 2026-10-25

| Check | Result |
|---|---|
| `python3 -W ignore -m unittest discover -s tests -q` | 67 tests OK. The suite also passed in a separate environment without the optional scipy |
| `python3 -m hnswaudit audit snapshots/churn-seed3-sync100/<uuid>` | status OK, exit 1; `UNREACHABLE_PROVEN` 1051, 1442, 1538; `TOMBSTONE_DEPENDENT` 15; 1,982 reachable-not-claimed |
| `python3 repro/compare_engine.py` with `sync100-A.json`, `sync100-B.json` | `soundness_holds` true; audit set equals the engine misses |
| `python3 -m hnswaudit audit snapshots/control-seed3/<uuid>` | status OK, exit 1; `UNREACHABLE_PROVEN` 1 (2824) |
| `python3 -m hnswaudit audit snapshots/churn-seed3/<uuid>` | `NOT_SETTLED`, exit 2, no per-ID verdict; persisted-only counts 0 / 9 / 1,991 |

Recorded earlier and not re-run in this pass: `repro/control.py` on a small real Chroma 1.5.9 store with three planted orphans (42, 200,
17): the audit set equals the engine's misses in each case and the untouched copy is clean. Output: `evidence/control-summary.json`. It can be rerun with `repro/control.py` and Chroma 1.5.9; the recorded run's inputs are not included, so a rerun builds a new store.

## Source index

| Claim | Where it is recorded |
|---|---|
| Settled store: three unreachable IDs, fifteen tombstone-dependent | `evidence/churn-seed3-sync100.audit.json` and `.html`; store in `snapshots/churn-seed3-sync100/` |
| The real engine misses the same three IDs in two fresh processes, at every tested `n_results` up to 4,000 | `evidence/engine/sync100-A.json`, `sync100-B.json`; summary in `evidence/ENGINE-PROBE.md` |
| Insert-only control also has one unreachable ID | `evidence/control-seed3.audit.json`, `evidence/engine/control-fresh.json`, `evidence/control-seed3.build.json` |
| Unsettled store: no verdict; engine results differ between processes | `evidence/churn-seed3.audit.json`, `evidence/engine/ksweep-A.json`, `ksweep-B.json`, `churn-seed3-reopen.json`, `snapshots/churn-seed3.build.json` |
| Same-process misses on the settled store (446, 3458, 3501) | `evidence/churn-seed3-sync100.build.json` |
| Planted-orphan control (secondary) | `evidence/control-summary.json` |
| Input integrity | `snapshots/*.src.sha256`, `evidence/*.sha256` |

## Unknowns

* Prevalence. One seeded workload per scenario, one host; engine runs for seed 3 only.
* Origin of each unreachable node: not established. The three nodes in the churn store could come from any step of the workload (adds, deletes,
  upserts); chroma-core/hnswlib PR #50 concerns `updatePoint`. Node 2824 is from an insert-only workload, so `updatePoint` is not involved;
  nmslib/hnswlib issue #522 (`mutuallyConnectNewElement`, `updatePoint`) suggests a possible link-loss mechanism at insertion, not shown here.
* Cause of the engine misses on the unsettled store: not established. Replay of queued operations on open is inferred, not traced.
* Whether a rebuild, or re-upserting an unreachable ID, restores reachability or produces new ones: not run.
* Atomic-flush consistency of the five files: not provable from hashes; the watermark, queue and id-map checks mitigate it.
* The vanilla hnswlib layout: source and unit fixtures only, never run on a real hnswlib file. Chroma versions other than 1.5.9: refused or untested.
* The traversal model comes from hnswlib source, not the 1.5.9 binary.
* `length.bin` contents are not validated. Scale beyond 4,000 nodes: not run.
