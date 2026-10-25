# Engine probe: Chroma 1.5.9 query results against the audit

This file summarises raw outputs kept in `evidence/engine/` and `evidence/*.build.json`. Observations are separated from inference.
Every number below can be read from the named JSON file. The scripts that built the stores and ran the queries are not part of this
repository; the stores and the raw outputs are.

## What was run (observation)

* Chroma 1.5.9 (`PersistentClient`), Python 3.12.3, one host. Collection metadata `{"hnsw:space": "l2"}`, plus `hnsw:sync_threshold=100`
  and `hnsw:batch_size=100` for the settled store.
* Workload, seed 3: 4,000 random 32-dimensional vectors added in batches of 500; for the churn stores, 2,000 random deletes, then 600
  upserts (30% of the survivors) with fresh random vectors. The insert-only control skips the deletes and upserts.
* Check: for every live ID, `query()` with that ID's own stored embedding at `n_results=k`. An ID is a miss if it is absent from the result.
* Opening a Chroma store rewrites `chroma.sqlite3`, so every engine run after the build used a copy of the snapshot.

## Settled store: `snapshots/churn-seed3-sync100`

Vector and metadata segment sequence numbers are equal (6,600) and nothing is queued: `evidence/churn-seed3-sync100.audit.json`.

| Run | `n_results` | IDs missed | File |
|---|---|---|---|
| Fresh process A, separate copy | 1000 | 1051, 1442, 1538 | `evidence/engine/sync100-A.json` |
| Fresh process B, separate copy | 1000 | 1051, 1442, 1538 | `evidence/engine/sync100-B.json` |
| Process that built the store | 100 | 1, 446, 1051, 1442, 1538, 1713, 3458, 3501 | `evidence/churn-seed3-sync100.build.json` |
| Process that built the store | 1000 | 446, 1051, 1442, 1538, 3458, 3501 | same file |

* A and B agree in every field except elapsed time.
* Targeted sweep (`targeted` in A and B) at `n_results` = 10, 100, 500, 1000, 1500, 2000 and 4000 (4,000 is above the 2,000 live
  records): 1051, 1442 and 1538 are never returned. 446 and 1713 are returned at every `n_results`. 3458, 3501 and 1 are returned from
  500 upward but not at 10 or 100.
* In the building process, `get()` returned all six IDs missed at `n_results=1000` (`get_finds_missing_top1000` in the build file).
* The audit of the same files lists exactly 1051, 1442 and 1538 as `UNREACHABLE_PROVEN` (`evidence/churn-seed3-sync100.audit.json`);
  `python3 repro/compare_engine.py` compares the two and reports `soundness_holds: true`.

## Insert-only control: `snapshots/control-seed3`

4,000 live records, no deletes or upserts, settled.

| Run | `n_results` | IDs missed | File |
|---|---|---|---|
| Fresh process | 1000 | 2824 | `evidence/engine/control-fresh.json` |
| Process that built the store | 100 | 522, 1722, 1785, 1958, 2824 | `evidence/control-seed3.build.json` |
| Process that built the store | 1000 | 2824 | same file |

* 2824 is never returned at `n_results` 10 to 4000. 522, 1722, 1785 and 1958 are returned from 500 upward.
* The audit lists 2824 as `UNREACHABLE_PROVEN` (`evidence/control-seed3.audit.json`).

## Unsettled store: `snapshots/churn-seed3`

Same workload with Chroma's default `sync_threshold`. The audit reads vector segment sequence 6,000, metadata segment sequence 6,600
and 600 queued UPSERTs (`evidence/churn-seed3.audit.json`, `operational`).

| Run | `n_results` | IDs missed | File |
|---|---|---|---|
| Process that built the store | 1000 | 446, 1051, 1442, 1538, 2908 | `snapshots/churn-seed3.build.json` |
| Fresh process, first reopen of a copy | 1000 | 1051, 2908 | `evidence/engine/churn-seed3-reopen.json` |
| Fresh process A, separate copy | 2000 | 305, 1051, 2908 | `evidence/engine/ksweep-A.json` |
| Fresh process B, separate copy | 2000 | 1051, 1903, 2475 | `evidence/engine/ksweep-B.json` |

* A and B differ in the targeted sweep too: 305 and 2908 are never returned in A and returned at every `n_results` in B; 1903 is returned
  from 500 upward in A and never in B; 1538 is returned from 500 upward in A and at every `n_results` in B. 1051 is never returned in
  either.
* The probe log recorded that opening a copy changed only `chroma.sqlite3`, not the HNSW files. The copies are not shipped, so this
  cannot be re-checked from the repository.

## Inference (not observed)

* One possible explanation for the differing results between fresh processes on the unsettled store is that Chroma replays the 600 queued upserts
  onto the loaded graph at each open, non-deterministically; this was not traced in the 1.5.9 binary. The audit's NO CERTIFICATE follows directly from
  the 600 queued operations being newer than the vector segment watermark (6,000), with the metadata segment sequence (6,600) above it, whatever the
  reason the engine runs diverge.
* For the settled store, the agreement between the audit and the engine supports the traversal model used by the audit. It does not
  prove the model matches the 1.5.9 binary.

## Scope and limits

* One seeded workload per scenario, one host. Engine runs exist for seed 3 only.
* Not tested: whether re-upserting an unreachable ID, or rebuilding the index, restores reachability.
* The same-process misses 446, 3458 and 3501 are not unreachable in the audit's sense; they were returned by fresh processes at
  `n_results` 500 and above.
