"""Build a SMALL real Chroma 1.5.9 store with no pending WAL: usage  python control_build.py <store_dir>
(run with an interpreter that has chromadb==1.5.9; this repo does not install it). Adds only, then deletes a few ids so the
engine takes its has_deletions branch. Small sync/batch thresholds force persistence of every operation."""
import json, os, sys
os.environ["ANONYMIZED_TELEMETRY"] = "False"
import chromadb, numpy as np
path = sys.argv[1]
rng = np.random.default_rng(11)
n, d = 300, 16
X = rng.standard_normal((n, d)).astype(np.float32)
c = chromadb.PersistentClient(path=path)
try:
    col = c.create_collection("ctl", configuration={"hnsw": {"space": "l2", "sync_threshold": 10, "batch_size": 10}})
    how = "configuration"
except Exception as e:
    col = c.create_collection("ctl", metadata={"hnsw:space": "l2", "hnsw:sync_threshold": 10, "hnsw:batch_size": 10})
    how = f"metadata (configuration failed: {type(e).__name__})"
for i in range(0, n, 50):
    col.add(ids=[str(j) for j in range(i, i + 50)], embeddings=X[i:i + 50].tolist())
dele = [5, 77, 150, 11, 23, 41, 59, 88, 101, 123, 199, 250]
col.delete(ids=[str(x) for x in dele])
json.dump({"n": n, "dim": d, "deleted": dele, "config_via": how, "chromadb": chromadb.__version__}, open(path + ".meta.json", "w"))
np.save(path + ".vectors.npy", X)
print("built", path, how, "count", col.count())
