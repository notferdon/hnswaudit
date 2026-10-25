"""Hand-built hnswlib-format graphs for deterministic tests (no engine needed).

``write_vanilla`` / ``write_chroma`` serialise the same abstract graph:
    n nodes, per-node level, layer-0 adjacency, upper adjacency {level: {node: [nbrs]}},
    entry node, deleted set, labels.
"""
import os
import struct

import numpy as np


def _build(n, dim, maxM, maxM0, levels, adj0, upper, entry, deleted, labels):
    data_off = 4 + 4 * maxM0
    label_off = data_off + 4 * dim
    stride = label_off + 8
    d0 = bytearray(n * stride)
    for i in range(n):
        nb = adj0.get(i, [])
        assert len(nb) <= maxM0
        flags = len(nb) | (0x10000 if i in deleted else 0)
        struct.pack_into("<I", d0, i * stride, flags)
        for j, t in enumerate(nb):
            struct.pack_into("<I", d0, i * stride + 4 + 4 * j, t)
        struct.pack_into("<Q", d0, i * stride + label_off, labels[i])
    ll = bytearray()
    per = 4 + 4 * maxM
    for i in range(n):
        L = levels[i] * per
        ll += struct.pack("<I", L)
        blk = bytearray(L)
        for lvl in range(1, levels[i] + 1):
            nb = upper.get(lvl, {}).get(i, [])
            assert len(nb) <= maxM
            struct.pack_into("<I", blk, (lvl - 1) * per, len(nb))
            for j, t in enumerate(nb):
                struct.pack_into("<I", blk, (lvl - 1) * per + 4 + 4 * j, t)
        ll += blk
    maxlevel = max(levels) if n else -1
    hdr = (0, n, n, stride, label_off, data_off, maxlevel, entry, maxM, maxM0, maxM // 2 or 1, 1.0, 100)
    return hdr, bytes(d0), bytes(ll)


def write_vanilla(path, **kw):
    hdr, d0, ll = _build(**kw)
    with open(path, "wb") as f:
        f.write(struct.pack("<QQQQQQiIQQQdQ", *hdr))
        f.write(d0)
        f.write(ll)
    return path


def write_chroma(dirpath, **kw):
    hdr, d0, ll = _build(**kw)
    os.makedirs(dirpath, exist_ok=True)
    with open(os.path.join(dirpath, "header.bin"), "wb") as f:
        f.write(struct.pack("<iQQQQQQiIQQQdQ", 1, *hdr))
    with open(os.path.join(dirpath, "data_level0.bin"), "wb") as f:
        f.write(d0)
    with open(os.path.join(dirpath, "length.bin"), "wb") as f:
        f.write(np.ones(kw["n"], dtype="<f4").tobytes())
    with open(os.path.join(dirpath, "link_lists.bin"), "wb") as f:
        f.write(ll)
    return dirpath


def graph(n=6, dim=2, maxM=2, maxM0=4, levels=None, adj0=None, upper=None, entry=0, deleted=(), labels=None):
    return dict(n=n, dim=dim, maxM=maxM, maxM0=maxM0, levels=levels or [0] * n, adj0=adj0 or {}, upper=upper or {},
                entry=entry, deleted=set(deleted), labels=labels or list(range(100, 100 + n)))


def write_chroma_sqlite(parent, segment, watermark=10, meta_seq=10, queue_seqs=(10,), ids=()):
    """Minimal chroma.sqlite3 next to a segment dir: segments, max_seq_id, embeddings_queue, embeddings, collections."""
    import sqlite3
    db = os.path.join(parent, "chroma.sqlite3")
    c = sqlite3.connect(db)
    c.executescript("""
      create table segments(id text, type text, scope text, collection text);
      create table max_seq_id(segment_id text, seq_id integer);
      create table embeddings_queue(seq_id integer, created_at text, operation integer, topic text, id text, vector blob, encoding text, metadata text);
      create table embeddings(id integer, segment_id text, embedding_id text, seq_id integer, created_at text);
      create table collections(id text, name text, dimension integer);
    """)
    c.execute("insert into segments values(?,?,?,?)", (segment, "hnsw-local-persisted", "VECTOR", "col1"))
    c.execute("insert into segments values(?,?,?,?)", ("metaseg", "metadata/sqlite", "METADATA", "col1"))
    c.execute("insert into max_seq_id values(?,?)", (segment, watermark))
    c.execute("insert into max_seq_id values(?,?)", ("metaseg", meta_seq))
    for s in queue_seqs:
        c.execute("insert into embeddings_queue values(?,?,?,?,?,?,?,?)", (s, "t", 2, "persistent://default/default/col1", f"q{s}", b"", "FLOAT32", None))
    for n, i in enumerate(ids):
        c.execute("insert into embeddings values(?,?,?,?,?)", (n, "metaseg", str(i), 1, "t"))
    c.execute("insert into collections values('col1','c',2)")
    c.commit()
    c.close()
