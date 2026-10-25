"""Read-only look at chroma.sqlite3 beside a Chroma segment directory (operational state).

Opened ``mode=ro&immutable=1`` on a SNAPSHOT COPY. Refuses (returns ok=False, reason) when a rollback
journal / WAL sidecar exists, because a hot journal means the file is not a consistent state.
Only plain SELECTs; nothing is imported or executed from the database.
"""
import os
import sqlite3
import struct
from urllib.parse import quote

OPS = {0: "ADD", 1: "UPDATE", 2: "UPSERT", 3: "DELETE"}


def _seq(v):
    if isinstance(v, (bytes, bytearray)):
        return int.from_bytes(v, "big")
    return int(v)


def read(segdir, with_vectors=False):
    segdir = os.path.abspath(segdir)
    seg = os.path.basename(segdir.rstrip(os.sep))
    db = os.path.join(os.path.dirname(segdir), "chroma.sqlite3")
    if not os.path.isfile(db):
        return {"ok": False, "reason": "chroma.sqlite3 not found next to the segment directory"}
    for suf in ("-wal", "-shm", "-journal"):
        if os.path.exists(db + suf):
            return {"ok": False, "reason": f"chroma.sqlite3{suf} present: not a consistent SQLite state (recover on a copy first)"}
    try:
        c = sqlite3.connect(f"file:{quote(db)}?mode=ro&immutable=1", uri=True)  # quote: #, ? and % are URI syntax
        row = c.execute("select collection, scope from segments where id=?", (seg,)).fetchone()
        if row is None:
            return {"ok": False, "reason": f"segment {seg} not in segments table"}
        collection = row[0]
        wm = c.execute("select seq_id from max_seq_id where segment_id=?", (seg,)).fetchone()
        wm = _seq(wm[0]) if wm else None
        meta_seg = c.execute("select id from segments where collection=? and scope='METADATA'", (collection,)).fetchone()
        topic_like = f"%/{collection}"
        out = {"ok": True, "segment": seg, "collection": collection, "watermark": wm, "db_sha_note": "read immutable"}
        if wm is None:
            out.update(ok=False, reason="no max_seq_id row for the vector segment: cannot establish what the HNSW file contains")
            return out
        q = "select seq_id, operation, id" + (", vector, encoding" if with_vectors else "") + \
            " from embeddings_queue where topic like ? and seq_id>? order by seq_id"
        pend = c.execute(q, (topic_like, wm)).fetchall()
        out["pending"] = pend
        out["pending_count"] = len(pend)
        ops = {}
        for r in pend:
            ops[OPS.get(r[1], str(r[1]))] = ops.get(OPS.get(r[1], str(r[1])), 0) + 1
        out["pending_ops"] = ops
        out["pending_ids"] = sorted({r[2] for r in pend})
        out["metadata_segment_seq"] = None
        if meta_seg:
            mw = c.execute("select seq_id from max_seq_id where segment_id=?", (meta_seg[0],)).fetchone()
            out["metadata_segment_seq"] = _seq(mw[0]) if mw else None
        out["queue_max_seq"] = c.execute("select max(seq_id) from embeddings_queue where topic like ?", (topic_like,)).fetchone()[0]
        if meta_seg:
            out["sqlite_live_ids"] = {r[0] for r in c.execute("select embedding_id from embeddings where segment_id=?", (meta_seg[0],))}
        dim = c.execute("select dimension from collections where id=?", (collection,)).fetchone()
        out["collection_dimension"] = dim[0] if dim else None
        c.close()
        return out
    except sqlite3.Error as e:
        return {"ok": False, "reason": f"sqlite error: {e}"}


def vector(blob, encoding):
    if encoding != "FLOAT32":
        raise ValueError(f"unsupported vector encoding {encoding}")
    import numpy as np
    return np.frombuffer(blob, dtype="<f4")
