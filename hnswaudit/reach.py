"""Structural reachability over a validated persisted HNSW graph.

Soundness argument:
* A search enters at ``enterpoint`` and descends layers maxlevel..1 moving only along
  that layer's edges, then runs a layer-0 beam search that only ever visits neighbours
  of nodes it has expanded (deleted nodes are expanded too).
* ``entry_envelope`` over-approximates every possible layer-0 start by taking the
  *undirected-in-distance* closure: all nodes reachable along layer-l edges, ignoring the
  "strictly closer" rule. Any real greedy descent stays inside it.
* ``reach0`` is the layer-0 forward closure of that envelope. A live node outside it can
  never be visited by any unfiltered or filtered search at any ``ef``/``k``.
The classes are structural claims about the *files*, never "query X returns Y".
"""
from dataclasses import dataclass

import numpy as np


def _csr(nodes_src, cnt, nbr, n):
    """Build CSR (indptr, indices) for edges src->nbr[:cnt]."""
    cnt = cnt.astype(np.int64)
    mask = np.arange(nbr.shape[1])[None, :] < cnt[:, None]
    indices = nbr[mask].astype(np.int64)
    src = np.repeat(nodes_src, cnt)
    order = np.argsort(src, kind="stable")
    indices = indices[order]
    counts = np.bincount(src, minlength=n)
    indptr = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(counts, out=indptr[1:])
    return indptr, indices


def _closure(indptr, indices, seeds, n, expandable=None):
    """Forward closure from ``seeds``. Nodes with expandable[v] False are visited but not expanded."""
    seen = np.zeros(n, dtype=bool)
    seeds = np.asarray(seeds, dtype=np.int64)
    seen[seeds] = True
    frontier = seeds
    if expandable is not None:
        frontier = frontier[expandable[frontier]]
    while frontier.size:
        starts, ends = indptr[frontier], indptr[frontier + 1]
        total = int((ends - starts).sum())
        if total == 0:
            break
        # gather all neighbour slices of the frontier
        lens = ends - starts
        offs = np.repeat(starts - np.concatenate(([0], np.cumsum(lens)[:-1])), lens) + np.arange(total)
        nxt = np.unique(indices[offs])
        nxt = nxt[~seen[nxt]]
        seen[nxt] = True
        frontier = nxt if expandable is None else nxt[expandable[nxt]]
    return seen


@dataclass
class Reach:
    envelope: np.ndarray  # int64 ids of S_0
    reach0: np.ndarray  # bool[cur]  routing closure (deleted nodes expand)
    reach0_live: np.ndarray  # bool[cur]  closure when deleted nodes are never expanded
    in_deg0: np.ndarray  # int64[cur] layer-0 in-degree
    scc_count: object  # int, or None when scipy is unavailable (not computed)
    scc_largest: object


def analyse(g):
    n = g.cur
    if n == 0:
        z = np.zeros(0, bool)
        return Reach(np.zeros(0, np.int64), z, z, np.zeros(0, np.int64), 0, 0)
    seeds = np.array([g.entry], dtype=np.int64)
    for lvl in range(g.maxlevel, 0, -1):
        nodes, cnt, nbr = g.upper.get(lvl, (np.zeros(0, np.int64), np.zeros(0, np.uint32), np.zeros((0, g.maxM), np.uint32)))
        ip, ix = _csr(nodes, cnt, nbr, n)
        seeds = np.nonzero(_closure(ip, ix, seeds, n))[0]
    ip0, ix0 = _csr(np.arange(n, dtype=np.int64), g.l0_cnt, g.l0_nbr, n)
    reach0 = _closure(ip0, ix0, seeds, n)
    live = ~g.deleted
    reach_live = _closure(ip0, ix0, seeds, n, expandable=live)
    in_deg = np.bincount(ix0, minlength=n)
    try:
        from scipy.sparse import csr_matrix
        from scipy.sparse.csgraph import connected_components

        m = csr_matrix((np.ones(len(ix0), dtype=np.int8), ix0, ip0), shape=(n, n))
        k, lab = connected_components(m, directed=True, connection="strong")
        scc_largest = int(np.bincount(lab).max())
    except Exception:  # scipy optional
        k, scc_largest = None, None  # scipy not installed: not computed
    return Reach(seeds, reach0, reach_live, in_deg, None if k is None else int(k), scc_largest)


UNREACHABLE_PROVEN = "UNREACHABLE_PROVEN"
TOMBSTONE_DEPENDENT = "TOMBSTONE_DEPENDENT"
REACHABLE_NOT_CLAIMED = "REACHABLE_NOT_CLAIMED"


def classify(g, r, live_mask):
    """Class per internal id; only nodes with live_mask are classified (others -> None)."""
    cls = np.full(g.cur, None, dtype=object)
    unreach = live_mask & ~r.reach0
    tomb = live_mask & r.reach0 & ~r.reach0_live
    ok = live_mask & r.reach0_live
    cls[unreach] = UNREACHABLE_PROVEN
    cls[tomb] = TOMBSTONE_DEPENDENT
    cls[ok] = REACHABLE_NOT_CLAIMED
    return cls
