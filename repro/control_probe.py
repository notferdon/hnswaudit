"""Real-engine probe of a (copied) Chroma store: own-vector query for every live id at n_results=K, plus get().
usage: control_probe.py <store_dir> <vectors.npy> <K>   (run with an interpreter that has chromadb==1.5.9; opens the store read/write -> use a COPY)"""
import json, os, sys
os.environ["ANONYMIZED_TELEMETRY"] = "False"
import chromadb, numpy as np
path, vec, K = sys.argv[1], np.load(sys.argv[2]), int(sys.argv[3])
col = chromadb.PersistentClient(path=path).get_collection("ctl")
ids = col.get()["ids"]
miss, no_get = [], []
for i in ids:
    r = col.query(query_embeddings=[vec[int(i)].tolist()], n_results=K)
    if i not in r["ids"][0]:
        miss.append(int(i))
    if not col.get(ids=[i])["ids"]:
        no_get.append(int(i))
print(json.dumps({"store": path, "live": len(ids), "K": K, "query_missing": sorted(miss), "get_missing": sorted(no_get)}))
