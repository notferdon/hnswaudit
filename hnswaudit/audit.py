"""Orchestrates one read-only audit and builds the machine-readable report."""
import hashlib
import os
import time

import numpy as np

from . import __version__, chroma_sqlite, layout, reach, safepickle

SCHEMA = "hnswaudit.report/1"
ENGINE_ASSUMPTIONS = [
    "Search starts at header.enterpoint and descends layers maxlevel..1 along that layer's edges; layer 0 is a beam search "
    "that only visits neighbours of nodes it has expanded, and deleted (tombstoned) nodes are expanded (hnswlib "
    "searchKnn/searchBaseLayerST, chroma-core/hnswlib rev e6db8c2 and nmslib/hnswlib ca42672).",
    "Statements describe the FILES in the snapshot, not a running process: in-memory state, un-flushed WAL records, and "
    "partially persisted dirty lists are outside the proof.",
    "Reachable (REACHABLE_NOT_CLAIMED) is necessary, not sufficient: a particular graph search can still miss a node (ef/beam, "
    "filters). Only UNREACHABLE_PROVEN is a structural claim: under the stated traversal model, no graph search can visit or return it, "
    "and only for this graph. Brute-force or filtered code paths and Chroma API behaviour were not measured.",
    "Metadata filters, ef, k and the distance metric cannot make the graph traversal visit a node it never reaches. Only graph search is covered: any other path Chroma may use (e.g. brute-force search over small or filtered candidate sets) is not.",
]
SNAPSHOT_CONSISTENCY_NOTE = (
    "Identical file hashes before and after the audit prove only that the files did not change WHILE auditing. They do not "
    "prove the five Chroma files came from one atomic flush (persistDirty writes the header first, other files are seeked "
    "over, no fsync). Cross-file structural checks passed, but atomic-flush consistency is UNPROVEN.")
API_STATUS = ("UNKNOWN: whether Chroma get()/query() return these IDs was NOT measured by this audit; the claims here concern "
              "graph structure only")
NOT_CHECKED = [
    "whether Chroma get() returns any listed ID (SQLite / API not consulted)",
    "writes held only in the memory of a running Chroma process (the audit assumes a stopped, copied store; queued-but-unflushed operations are checked and, if present, block the verdict)",
    "whether Chroma main (PR #7845) would serve exact/overfetched results even when the graph is disconnected",
    "the engine commit that wrote the snapshot (a snapshot stores only PERSISTENCE_VERSION)",
]


def sha256(path, chunk=1 << 22):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _files(path):
    if os.path.isdir(path):
        names = sorted(n for n in os.listdir(path) if os.path.isfile(os.path.join(path, n)))
        return [os.path.join(path, n) for n in names]
    return [path]


def _idmap(path):
    """Chroma id<->label map from index_metadata.pickle (symbolic parse only)."""
    p = os.path.join(path, "index_metadata.pickle")
    if not os.path.isfile(p):
        return None, "index_metadata.pickle missing"
    try:
        with open(p, "rb") as f:
            obj = safepickle.loads(f.read())
    except safepickle.PickleRefused as e:
        return None, f"pickle refused: {e}"
    except Exception as e:  # malformed
        return None, f"pickle unreadable: {type(e).__name__}: {e}"
    state = obj.state if isinstance(obj, safepickle.Inert) else obj
    if isinstance(state, tuple) and len(state) == 2 and isinstance(state[1], dict):
        state = state[1]
    if not isinstance(state, dict) or "id_to_label" not in state:
        return None, "pickle does not contain id_to_label"
    i2l = state["id_to_label"]
    l2i = state.get("label_to_id")
    if not isinstance(i2l, dict) or (l2i is not None and not isinstance(l2i, dict)):
        return None, "id map has unexpected types"
    if l2i is not None and (len(i2l) != len(l2i) or any(l2i.get(v) != k for k, v in i2l.items())):
        return None, "id_to_label and label_to_id disagree"
    meta = {k: state.get(k) for k in ("dimensionality", "total_elements_added", "max_seq_id", "checkpoint_seq_id") if k in state}
    return {"id_to_label": i2l, "meta": meta}, None


def audit(path, max_findings=100000):
    t0 = time.time()
    path = os.path.abspath(path)
    files = _files(path)
    before = {f: sha256(f) for f in files}
    rep = {"schema": SCHEMA, "tool": "hnswaudit", "version": __version__, "path": os.path.basename(os.path.normpath(path)),  # portable name only; the absolute path is used for reading, never reported
           "status": None, "reason": None, "engine_assumptions": ENGINE_ASSUMPTIONS, "not_checked": NOT_CHECKED,
           "inputs": [{"file": os.path.basename(f), "bytes": os.path.getsize(f), "sha256": before[f]} for f in files]}
    try:
        g = layout.load(path)
    except layout.FormatError as e:
        rep.update(status="UNSUPPORTED_OR_CORRUPT", reason=str(e), findings=[], summary={"verdict": "NO VERDICT: snapshot refused (fail closed)"})
        rep["elapsed_s"] = round(time.time() - t0, 3)
        return rep, None
    r = reach.analyse(g)

    idinfo, iderr = (None, None)
    if g.layout == "chroma":
        idinfo, iderr = _idmap(path)
    deleted = g.deleted
    labels = g.labels.astype(np.int64) if g.cur else g.labels
    consistency = {"idmap": "n/a (vanilla hnswlib: native label is the user id)" if g.layout == "vanilla" else ("ok" if idinfo else iderr)}
    ids_by_label = None
    if idinfo is not None:
        i2l = idinfo["id_to_label"]
        ids_by_label = {int(l): k for k, l in i2l.items()}
        mapped = np.fromiter((int(l) in ids_by_label for l in labels), dtype=bool, count=g.cur)
        mapped_deleted = np.nonzero(mapped & deleted)[0]
        unmapped_active = np.nonzero(~mapped & ~deleted)[0]
        native = set(labels.tolist())
        missing = [l for l in ids_by_label if l not in native]
        consistency.update(mapped_but_tombstoned=[{"id": ids_by_label[int(labels[i])], "label": int(labels[i])} for i in mapped_deleted[:1000]],
                           mapped_but_tombstoned_count=int(len(mapped_deleted)),
                           native_active_without_id_count=int(len(unmapped_active)),
                           mapped_label_absent_in_graph_count=len(missing), meta=idinfo["meta"])
        live = ~deleted & mapped
    elif g.layout == "chroma":
        live = np.zeros(g.cur, dtype=bool)  # no id map -> no live claim at all
    else:
        live = ~deleted
    cls = reach.classify(g, r, live)

    operational = None
    if g.layout == "chroma":
        w = chroma_sqlite.read(path)
        if w.get("ok"):
            operational = {"sqlite": "read (immutable, snapshot copy)", "vector_segment_watermark": w["watermark"],
                           "metadata_segment_seq": w.get("metadata_segment_seq"),
                           "queue_max_seq": w["queue_max_seq"], "pending_operations": w["pending_count"],
                           "pending_by_op": w["pending_ops"], "pending_id_count": len(w["pending_ids"]),
                           "pending_ids_sample": w["pending_ids"][:50]}
            if idinfo is not None and w.get("sqlite_live_ids") is not None and ids_by_label is not None:
                idmap_live = {ids_by_label[int(labels[i])] for i in range(g.cur) if live[i]}
                diff = (idmap_live ^ w["sqlite_live_ids"]) - set(w["pending_ids"])
                operational["sqlite_vs_idmap_unexplained_live_diff"] = len(diff)
        else:
            operational = {"sqlite": "NOT READ", "reason": w.get("reason")}
    pending_ids = set(w["pending_ids"]) if (g.layout == "chroma" and w.get("ok")) else set()
    in_src = None
    findings = []
    interesting = np.nonzero(np.array([c in (reach.UNREACHABLE_PROVEN, reach.TOMBSTONE_DEPENDENT) for c in cls]))[0] if g.cur else []
    if len(interesting):
        in_src = _in_neighbours(g, set(int(i) for i in interesting[:max_findings]))
    order = sorted((int(i) for i in interesting), key=lambda i: (cls[i] != reach.UNREACHABLE_PROVEN, str(ids_by_label[int(labels[i])]) if ids_by_label else int(labels[i])))
    for i in order[:max_findings]:
        nb = in_src.get(i, [])
        findings.append({
            "id": ids_by_label[int(labels[i])] if ids_by_label else int(labels[i]),
            "label": int(labels[i]), "internal": i, "class": cls[i], "level": int(g.levels[i]),
            "in_degree_layer0": int(r.in_deg0[i]),
            "out_degree_layer0": int(g.l0_cnt[i]),
            "in_neighbours_layer0": [{"internal": s, "label": int(labels[s]), "deleted": bool(deleted[s]),
                                      "reachable": bool(r.reach0[s])} for s in nb[:20]],
            "why": _why(cls[i], r, in_src.get(i, []), deleted),
            "pending_operation": (str(ids_by_label[int(labels[i])]) in pending_ids) if ids_by_label else None,
        })
    contradictions = []
    if operational and operational.get("sqlite_vs_idmap_unexplained_live_diff"):
        contradictions.append(f"{operational['sqlite_vs_idmap_unexplained_live_diff']} live id(s) differ between SQLite and the id map and are not explained by pending operations")
    if idinfo is not None:
        c = consistency
        if c["mapped_but_tombstoned_count"]:
            contradictions.append(f"{c['mapped_but_tombstoned_count']} id-mapped label(s) are tombstoned in the native graph")
        if c["native_active_without_id_count"]:
            contradictions.append(f"{c['native_active_without_id_count']} native-live label(s) have no id in the map")
        if c["mapped_label_absent_in_graph_count"]:
            contradictions.append(f"{c['mapped_label_absent_in_graph_count']} id-mapped label(s) are absent from the graph")
        dim_meta = idinfo["meta"].get("dimensionality")
        if dim_meta is not None and dim_meta != g.dim:
            contradictions.append(f"id-map dimensionality {dim_meta} != header dimension {g.dim}")
    n_live = int(live.sum())
    n_unreach = int((cls == reach.UNREACHABLE_PROVEN).sum()) if g.cur else 0
    n_tomb = int((cls == reach.TOMBSTONE_DEPENDENT).sum()) if g.cur else 0
    summary = {
        "nodes": g.cur, "live": n_live, "tombstoned_native": int(deleted.sum()),
        "unreachable_proven": n_unreach, "tombstone_dependent": n_tomb,
        "reachable_not_claimed": n_live - n_unreach - n_tomb,
        "entry_internal": int(g.entry) if g.cur else None, "entry_deleted": bool(deleted[g.entry]) if g.cur else None,
        "maxlevel": g.maxlevel, "envelope_size": int(len(r.envelope)), "reach0_size": int(r.reach0.sum()),
        "reach_live_only_size": int(r.reach0_live.sum()),
        "layer0_zero_in_degree_live": int(((r.in_deg0 == 0) & live).sum()) if g.cur else 0,
        "scc_count": r.scc_count, "scc_largest": r.scc_largest,
        "verdict": _verdict(n_unreach, n_tomb, g, idinfo, iderr),
    }
    after = {f: sha256(f) for f in files}
    rep["snapshot_consistency"] = {"hash_stable_during_audit": after == before, "atomic_flush": "UNPROVEN", "note": SNAPSHOT_CONSISTENCY_NOTE}
    rep["api_status"] = API_STATUS
    rep["operational"] = operational
    rep["settled"] = "n/a (vanilla file)" if g.layout != "chroma" else ("yes: no operation newer than the vector segment" if operational and operational.get("sqlite") != "NOT READ" and not operational["pending_operations"] and not (operational.get("metadata_segment_seq") or 0) > operational["vector_segment_watermark"] else "NO or unknown (see status)")
    if operational and operational.get("pending_operations"):
        summary["verdict"] += (f"  CAVEAT: {operational['pending_operations']} pending Chroma operation(s) (touching "
                               f"{operational['pending_id_count']} id(s)) are newer than the persisted graph: a sequence gap. This verdict covers the persisted graph "
                               f"only; the graph Chroma serves cannot be certified from the persisted files alone")
    snapshot_stable = after == before
    rep.update(status="OK" if snapshot_stable and not (g.layout == "chroma" and idinfo is None) else
               ("SNAPSHOT_CHANGED_DURING_AUDIT" if not snapshot_stable else "OK_NO_IDMAP"),
               layout=g.layout, format={"persistence_version": g.version, "dim": g.dim, "maxM": g.maxM, "maxM0": g.maxM0, "M": g.M,
                                        "ef_construction": g.ef_construction, "max_elements": g.max_elements, "stride": g.stride},
               summary=summary, consistency=consistency, anomalies=g.anomalies, findings=findings,
               findings_truncated=len(interesting) > max_findings, elapsed_s=round(time.time() - t0, 3))
    # Settledness: operations newer than the vector segment's watermark are a sequence gap the persisted files cannot account for.
    not_settled = None
    if g.layout == "chroma" and snapshot_stable and not contradictions:
        if operational is None or operational.get("sqlite") == "NOT READ":
            not_settled = ("SETTLEMENT_UNKNOWN", "chroma.sqlite3 could not be read (" + str((operational or {}).get("reason")) +
                           "), so it cannot be shown that the HNSW files contain every committed operation")
        else:
            behind = []
            if operational["pending_operations"]:
                behind.append(f"{operational['pending_operations']} queued operation(s) newer than the vector segment watermark")
            ms = operational.get("metadata_segment_seq")
            if ms is not None and ms > operational["vector_segment_watermark"]:
                behind.append(f"metadata segment seq {ms} > vector segment seq {operational['vector_segment_watermark']}")
            if behind:
                not_settled = ("NOT_SETTLED", "the persisted HNSW files are behind the store (" + "; ".join(behind) +
                               "): a sequence gap, so the graph Chroma serves cannot be certified from the persisted files alone")
    if not_settled:
        # descriptive persisted-only observations are kept, but NO per-ID verdict / health certificate is issued
        rep["persisted_observations"] = {k: summary[k] for k in summary if k != "verdict"}
        rep["persisted_only_findings"] = findings
        rep["findings"] = []
        rep["status"], rep["reason"] = not_settled
        for k in ("unreachable_proven", "tombstone_dependent", "reachable_not_claimed"):
            rep["summary"][k] = None
        rep["summary"]["verdict"] = ("NO CERTIFICATE (" + not_settled[0] + "): the effective-store graph is unknown; structural counts below "
                                     "describe the persisted files only and must not be read as index health")
    if contradictions and snapshot_stable:
        rep["status"] = "INCONSISTENT_SNAPSHOT"
        rep["reason"] = "id map and native graph contradict each other: " + "; ".join(contradictions)
        rep["contradictions"] = contradictions
        rep["findings"] = []
        rep["summary"]["verdict"] = "NO CERTIFICATE: id map and graph disagree; per-ID verdicts withheld (fail closed)"
        for k in ("unreachable_proven", "tombstone_dependent", "reachable_not_claimed"):
            rep["summary"][k] = None
    if not snapshot_stable:
        rep["reason"] = "input files changed while auditing; verdicts withheld"
        rep["findings"] = []
        rep["summary"]["verdict"] = "NO VERDICT: snapshot changed during audit"
    if g.layout == "chroma" and idinfo is None and snapshot_stable:
        rep["reason"] = f"Chroma id map unavailable ({iderr}); no live-ID claim is made, native labels only listed in 'native_unreachable'"
        rep["native_unreachable"] = [int(labels[i]) for i in np.nonzero(~deleted & ~r.reach0)[0][:max_findings]]
        rep["summary"]["verdict"] = "CONSERVATIVE: graph analysed, but live IDs cannot be established without the id map"
    return rep, (g, r, cls, live)


def _in_neighbours(g, targets):
    """Layer-0 in-neighbours for a small target set (one vectorised pass)."""
    cnt = g.l0_cnt.astype(np.int64)
    mask = np.arange(g.maxM0)[None, :] < cnt[:, None]
    src = np.repeat(np.arange(g.cur), cnt)
    tgt = g.l0_nbr[mask].astype(np.int64)
    ts = np.fromiter(targets, dtype=np.int64)
    sel = np.isin(tgt, ts)
    out = {t: [] for t in targets}
    for s, t in zip(src[sel], tgt[sel]):
        out[int(t)].append(int(s))
    return out


def _why(klass, r, in_nb, deleted):
    if klass == reach.UNREACHABLE_PROVEN:
        if not in_nb:
            return "no node has a layer-0 edge to it"
        live_in = [s for s in in_nb if not deleted[s]]
        return (f"{len(in_nb)} node(s) point at it, but every one of them is itself outside the start-reachable region"
                f" ({len(live_in)} live, {len(in_nb) - len(live_in)} tombstoned): a disconnected island")
    if klass == reach.TOMBSTONE_DEPENDENT:
        return "reachable only by routing through deleted (tombstoned) nodes; breaks if tombstones are purged or the index is compacted"
    return ""


def _verdict(n_unreach, n_tomb, g, idinfo, iderr):
    if g.cur == 0:
        return "EMPTY INDEX: nothing to certify"
    if n_unreach:
        return (f"{n_unreach} live ID(s) are structurally unreachable in this graph: no graph search at any k or ef reaches them "
                f"(brute-force or filtered code paths and Chroma API behaviour were not measured). Typical remedy: rebuild the index, then "
                f"re-audit the rebuilt copy; this tool has not verified that a rebuild fixes these IDs")
    if n_tomb:
        return (f"NO UNREACHABLE LIVE IDS; {n_tomb} live ID(s) depend on tombstone routing - they disappear if deleted nodes are "
                f"purged without a graph rebuild")
    return "NO STRUCTURALLY UNREACHABLE LIVE IDS FOUND (not a retrievability guarantee)"
