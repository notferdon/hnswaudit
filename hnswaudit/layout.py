"""Strict, read-only parser for persisted hnswlib graphs.

Two layouts are recognised and everything else is refused (fail closed):

* ``chroma``  - Chroma segment directory: header.bin (100 B), data_level0.bin,
                length.bin, link_lists.bin (+ index_metadata.pickle, see idmap.py)
* ``vanilla`` - nmslib/hnswlib ``saveIndex`` single file (96 B header, no version)

Native types are raw machine PODs; only little-endian LP64 is accepted.
Layout facts come from hnswlib ``hnswalg.h`` (``persistHeader`` / ``saveIndex``) as
read from source; they are re-checked against real files in tests.
"""
import mmap
import os
import struct
import sys
from dataclasses import dataclass, field

import numpy as np

if sys.byteorder != "little":  # pragma: no cover
    raise SystemExit("hnswaudit: refusing big-endian host")


class FormatError(Exception):
    """Snapshot is not a supported/consistent hnswlib graph. No verdicts may be issued."""


CHROMA_HEADER = struct.Struct("<iQQQQQQiIQQQdQ")  # 4+6*8+4+4+3*8+8+8 = 100
VANILLA_HEADER = struct.Struct("<QQQQQQiIQQQdQ")  # 96
assert CHROMA_HEADER.size == 100 and VANILLA_HEADER.size == 96

DELETE_BIT = 0x10000  # flags word of a level-0 record: bit 16 = DELETE_MARK


@dataclass
class Graph:
    layout: str
    source: dict  # file -> {path, bytes, sha256?}
    version: int | None
    cur: int
    max_elements: int
    stride: int
    dim: int
    maxM: int
    maxM0: int
    M: int
    maxlevel: int
    entry: int
    ef_construction: int
    mult: float
    labels: np.ndarray  # uint64[cur]
    deleted: np.ndarray  # bool[cur]
    levels: np.ndarray  # int32[cur]
    l0_cnt: np.ndarray  # uint32[cur]
    l0_nbr: np.ndarray  # uint32[cur, maxM0] (read-only view)
    upper: dict = field(default_factory=dict)  # level -> (node_ids int64[], cnt uint32[], nbr uint32[n, maxM])
    anomalies: list = field(default_factory=list)


def _map(path):
    size = os.path.getsize(path)
    if size == 0:
        return b""
    f = open(path, "rb")
    try:
        return mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    finally:
        f.close()


def _need(cond, msg):
    if not cond:
        raise FormatError(msg)


def _validate_header(h, layout):
    (offset0, max_el, cur, stride, label_off, data_off, maxlevel, entry, maxM, maxM0, M, mult, efc) = h
    _need(offset0 == 0, f"offsetLevel0={offset0} (must be 0)")
    _need(cur <= max_el < 2**40, f"cur_element_count={cur} max_elements={max_el}")
    _need(1 <= maxM <= 1024 and 1 <= maxM0 <= 4096 and 1 <= M <= 1024, f"degree params maxM={maxM} maxM0={maxM0} M={M}")
    _need(data_off == 4 + 4 * maxM0, f"offsetData={data_off} != 4+4*maxM0={4 + 4 * maxM0}")
    _need(label_off > data_off and (label_off - data_off) % 4 == 0, f"label_offset={label_off} inconsistent")
    dim = (label_off - data_off) // 4
    _need(1 <= dim <= 1 << 20, f"dimension {dim}")
    _need(stride == label_off + 8, f"size_data_per_element={stride} != label_offset+8={label_off + 8}")
    _need(-1 <= maxlevel < 64, f"maxlevel={maxlevel}")
    if cur > 0:
        _need(maxlevel >= 0 and entry < cur, f"enterpoint={entry} maxlevel={maxlevel} cur={cur}")
    return dim


def _level0(buf, base, cur, stride, maxM0, label_off, anomalies):
    raw = np.frombuffer(buf, dtype=np.uint8, count=cur * stride, offset=base).reshape(cur, stride)
    flags = raw[:, :4].copy().view("<u4").ravel()
    cnt = (flags & 0xFFFF).astype(np.uint32)
    deleted = (flags & DELETE_BIT) != 0
    if np.any(flags & ~np.uint32(0x1FFFF)):
        anomalies.append("level-0 flags word has unexpected high bits set")
    _need(not np.any(cnt > maxM0), "level-0 neighbour count exceeds maxM0")
    nbr = raw[:, 4:4 + 4 * maxM0].copy().view("<u4").reshape(cur, maxM0)
    labels = raw[:, label_off:label_off + 8].copy().view("<u8").ravel()
    return flags, cnt, deleted, nbr, labels


def _linklists(buf, start, end, cur, maxM, anomalies):
    """Sequentially index link_lists data. Returns (levels[int32], offsets[int64])."""
    per = 4 + 4 * maxM
    pos = start
    levels = np.zeros(cur, dtype=np.int32)
    offs = np.full(cur, -1, dtype=np.int64)
    unpack = struct.Struct("<I").unpack_from
    for i in range(cur):
        _need(pos + 4 <= end, f"link list stream truncated at element {i}")
        L = unpack(buf, pos)[0]
        _need(L % per == 0, f"link list size {L} for element {i} not a multiple of {per}")
        _need(pos + 4 + L <= end, f"link list stream overruns at element {i}")
        levels[i] = L // per
        offs[i] = pos + 4
        pos += 4 + L
    return levels, offs, pos


def _upper_levels(buf, levels, offs, maxM, cur, anomalies):
    per = 4 + 4 * maxM
    arr = np.frombuffer(buf, dtype="<u4") if len(buf) % 4 == 0 else np.frombuffer(buf[: len(buf) // 4 * 4], dtype="<u4")
    out = {}
    top = int(levels.max()) if cur else 0
    for lvl in range(1, top + 1):
        nodes = np.nonzero(levels >= lvl)[0]
        starts = offs[nodes] + (lvl - 1) * per
        _need(np.all(starts % 4 == 0), "unaligned link list block")
        w = (starts // 4).astype(np.int64)
        words = arr[w]
        cnt = (words & 0xFFFF).astype(np.uint32)
        if np.any(words & 0xFFFF0000):
            anomalies.append(f"level-{lvl} count word has high bits set")
        _need(not np.any(cnt > maxM), f"level-{lvl} neighbour count exceeds maxM")
        nbr = arr[w[:, None] + 1 + np.arange(maxM)[None, :]]
        out[lvl] = (nodes.astype(np.int64), cnt, nbr)
    return out


def _check_edges(g):
    cur = g.cur
    mask0 = np.arange(g.maxM0)[None, :] < g.l0_cnt[:, None]
    n0 = g.l0_nbr[mask0]
    _need(not np.any(n0 >= cur), "level-0 neighbour id out of range")
    for lvl, (nodes, cnt, nbr) in g.upper.items():
        mask = np.arange(g.maxM)[None, :] < cnt[:, None]
        tgt = nbr[mask]
        _need(not np.any(tgt >= cur), f"level-{lvl} neighbour id out of range")
        _need(not np.any(g.levels[tgt] < lvl), f"level-{lvl} edge to a node whose level is lower")
    if g.cur:
        _need(g.levels[g.entry] == g.maxlevel, f"level(enterpoint)={g.levels[g.entry]} != maxlevel={g.maxlevel}")
        _need(int(g.levels.max()) <= g.maxlevel, "an element has a level above maxlevel")
    uniq = np.unique(g.labels)
    _need(len(uniq) == g.cur, "duplicate native labels")


def load_chroma(dirpath):
    paths = {n: os.path.join(dirpath, n) for n in ("header.bin", "data_level0.bin", "length.bin", "link_lists.bin")}
    for n, p in paths.items():
        _need(os.path.isfile(p), f"missing {n}")
    hb = open(paths["header.bin"], "rb").read()
    _need(len(hb) == 100, f"header.bin is {len(hb)} bytes (supported: 100)")
    ver, *h = CHROMA_HEADER.unpack(hb)
    _need(ver == 1, f"persistence version {ver} (supported: 1)")
    dim = _validate_header(h, "chroma")
    (offset0, max_el, cur, stride, label_off, data_off, maxlevel, entry, maxM, maxM0, M, mult, efc) = h
    dsz = os.path.getsize(paths["data_level0.bin"])
    _need(dsz >= cur * stride, f"data_level0.bin is {dsz} B, need >= {cur * stride}")
    _need(dsz <= max_el * stride, f"data_level0.bin is {dsz} B, larger than max_elements*stride")
    lsz = os.path.getsize(paths["length.bin"])
    _need(lsz >= cur * 4, f"length.bin is {lsz} B, need >= {cur * 4}")
    anomalies = []
    data = _map(paths["data_level0.bin"]) if cur else b""
    _, cnt, deleted, nbr, labels = _level0(data, 0, cur, stride, maxM0, label_off, anomalies) if cur else (None, np.zeros(0, np.uint32), np.zeros(0, bool), np.zeros((0, maxM0), np.uint32), np.zeros(0, np.uint64))
    ll = _map(paths["link_lists.bin"])
    levels, offs, endpos = _linklists(ll, 0, len(ll), cur, maxM, anomalies)
    if endpos != len(ll):
        anomalies.append(f"link_lists.bin has {len(ll) - endpos} trailing bytes")
    _need(cur == 0 or int(levels.max()) <= maxlevel, "an element has a level above maxlevel")  # before the per-level loop
    upper = _upper_levels(ll, levels, offs, maxM, cur, anomalies) if cur else {}
    g = Graph("chroma", {n: {"path": p, "bytes": os.path.getsize(p)} for n, p in paths.items()}, ver, cur, max_el, stride, dim,
              maxM, maxM0, M, maxlevel, entry, efc, mult, labels, deleted, levels, cnt, nbr, upper, anomalies)
    _check_edges(g)
    return g


def load_vanilla(path):
    size = os.path.getsize(path)
    _need(size >= VANILLA_HEADER.size, "file shorter than the 96-byte hnswlib header")
    buf = _map(path)
    h = VANILLA_HEADER.unpack_from(buf, 0)
    dim = _validate_header(h, "vanilla")
    (offset0, max_el, cur, stride, label_off, data_off, maxlevel, entry, maxM, maxM0, M, mult, efc) = h
    base = VANILLA_HEADER.size
    _need(size >= base + cur * stride, "file truncated inside level-0 data")
    anomalies = []
    _, cnt, deleted, nbr, labels = _level0(buf, base, cur, stride, maxM0, label_off, anomalies) if cur else (None, np.zeros(0, np.uint32), np.zeros(0, bool), np.zeros((0, maxM0), np.uint32), np.zeros(0, np.uint64))
    start = base + cur * stride
    levels, offs, endpos = _linklists(buf, start, size, cur, maxM, anomalies)
    _need(endpos == size, f"{size - endpos} unexplained trailing bytes after link lists")
    _need(cur == 0 or int(levels.max()) <= maxlevel, "an element has a level above maxlevel")  # before the per-level loop
    upper = _upper_levels(buf, levels, offs, maxM, cur, anomalies) if cur else {}
    g = Graph("vanilla", {"index": {"path": path, "bytes": size}}, None, cur, max_el, stride, dim, maxM, maxM0, M, maxlevel,
              entry, efc, mult, labels, deleted, levels, cnt, nbr, upper, anomalies)
    _check_edges(g)
    return g


def load(path):
    """Dispatch on layout; refuse anything unrecognised."""
    if os.path.isdir(path):
        if os.path.isfile(os.path.join(path, "header.bin")):
            return load_chroma(path)
        raise FormatError("directory has no header.bin (not a Chroma HNSW segment directory)")
    if os.path.isfile(path):
        return load_vanilla(path)
    raise FormatError("path does not exist")
