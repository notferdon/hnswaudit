"""One command: planted-orphan control on the REAL Chroma 1.5.9 engine.
   python3 repro/control.py --chroma-python /path/to/python-with-chromadb-1.5.9 [--work controls/run1]
Builds a small persisted store (no pending WAL), plants an orphan in a copy for several ids, then compares
(a) hnswaudit's UNREACHABLE_PROVEN set with (b) ids the real engine fails to return for an own-vector query at K=live.
Soundness check: audit set must be a subset of engine misses. Prints/writes evidence/control-summary.json."""
import argparse, glob, json, os, shutil, subprocess, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from hnswaudit.audit import audit

ap = argparse.ArgumentParser()
ap.add_argument("--chroma-python", required=True)
ap.add_argument("--work", default=os.path.join(ROOT, "controls", "run"))
ap.add_argument("--ids", default="42,200,17")
a = ap.parse_args()
py, w = a.chroma_python, os.path.abspath(a.work)
if os.path.exists(w):
    sys.exit(f"{w} exists; choose a new --work directory")
os.makedirs(w)
run = lambda *c: subprocess.run(c, capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
print(run(py, os.path.join(ROOT, "repro", "control_build.py"), f"{w}/base"))
vec = f"{w}/base.vectors.npy"
res = {"chromadb": "1.5.9", "cases": []}
base_seg = glob.glob(f"{w}/base/*-*-*-*-*")[0]
rep, _ = audit(base_seg)
res["base_audit"] = {"status": rep["status"], "unreachable_proven": rep["summary"]["unreachable_proven"], "pending": (rep.get("operational") or {}).get("pending_operations")}
shutil.copytree(f"{w}/base", f"{w}/untouched")
ctl = json.loads(run(py, os.path.join(ROOT, "repro", "control_probe.py"), f"{w}/untouched", vec, "288"))
res["untouched_engine"] = ctl
ok = ctl["query_missing"] == [] and res["base_audit"]["unreachable_proven"] == 0
for uid in a.ids.split(","):
    dst = f"{w}/planted-{uid}"
    planted = run(sys.executable, os.path.join(ROOT, "repro", "plant_orphan.py"), f"{w}/base", dst, uid)
    seg = glob.glob(f"{dst}/*-*-*-*-*")[0]
    rep, _ = audit(seg)
    flagged = sorted(int(f["id"]) for f in rep["findings"] if f["class"] == "UNREACHABLE_PROVEN")
    eng = json.loads(run(py, os.path.join(ROOT, "repro", "control_probe.py"), dst, vec, "288"))
    sound = set(flagged) <= set(eng["query_missing"])
    res["cases"].append({"planted": uid, "plant_log": planted, "audit_unreachable": flagged, "engine_query_missing": eng["query_missing"],
                         "engine_get_missing": eng["get_missing"], "audit_subset_of_engine_misses": sound,
                         "audit_equals_engine_misses": flagged == eng["query_missing"]})
    ok = ok and sound and flagged == eng["query_missing"] and eng["get_missing"] == []
res["all_pass"] = ok
json.dump(res, open(os.path.join(ROOT, "evidence", "control-summary.json"), "w"), indent=1)
print(json.dumps(res, indent=1))
sys.exit(0 if ok else 1)
