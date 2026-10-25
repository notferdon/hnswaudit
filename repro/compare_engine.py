"""Compare hnswaudit's UNREACHABLE_PROVEN set on a SETTLED snapshot with the fresh-process Chroma engine sweeps (files in evidence/engine).
usage: compare_engine.py <segment_dir> <engine.json> [<engine.json> ...]   -> prints/writes JSON; exit 1 on a soundness violation"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from hnswaudit.audit import audit

seg, outs = sys.argv[1], sys.argv[2:]
rep, _ = audit(seg)
assert rep["status"] == "OK", rep["status"]
proven = sorted(int(f["id"]) for f in rep["findings"] if f["class"] == "UNREACHABLE_PROVEN")
res = {"segment": os.path.basename(seg.rstrip("/")), "audit_status": rep["status"], "unreachable_proven": proven, "engine_runs": []}
ok = True
for o in outs:
    e = json.load(open(o))
    miss = e["full_sweep_missing"]
    never = {i: all(not e["targeted"][str(i)][k]["found"] for k in e["targeted"][str(i)]) for i in proven if str(i) in e["targeted"]}
    row = {"file": os.path.basename(o), "full_sweep_k": e["full_sweep_k"], "engine_misses": miss,
           "audit_subset_of_engine_misses": set(proven) <= set(miss), "audit_equals_engine_misses": proven == miss,
           "proven_ids_never_returned_at_any_tested_k": never}
    ok &= row["audit_subset_of_engine_misses"]
    res["engine_runs"].append(row)
res["soundness_holds"] = ok
print(json.dumps(res, indent=1))
sys.exit(0 if ok else 1)
