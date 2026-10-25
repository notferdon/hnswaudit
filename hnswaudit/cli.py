"""Read-only command line: ``python -m hnswaudit audit <snapshot> --json r.json --html r.html``.

Exit codes: 0 no structurally unreachable live IDs; 1 unreachable live IDs found;
2 no verdict (unsupported, inconsistent, NOT_SETTLED, id map unavailable: fail closed); 3 usage error.
"""
import argparse
import json
import os
import sys

from . import __version__


def _inside(child, parent):
    c, p = os.path.realpath(child), os.path.realpath(parent)
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hnswaudit", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="audit a snapshot (Chroma segment dir or vanilla hnswlib file); never writes to it")
    a.add_argument("snapshot", help="COPY of a stopped store: Chroma <uuid> segment directory, or an hnswlib index file")
    a.add_argument("--json", metavar="FILE", help="write machine-readable report")
    a.add_argument("--html", metavar="FILE", help="write self-contained HTML inspector")
    a.add_argument("--max-findings", type=int, default=100000)
    a.add_argument("--force", action="store_true", help="overwrite existing report files")
    sub.add_parser("version")
    ns = ap.parse_args(argv)
    if ns.cmd == "version":
        print(__version__)
        return 0
    for out in (ns.json, ns.html):
        if out and _inside(out, ns.snapshot):
            print("refusing to write a report inside the snapshot", file=sys.stderr)
            return 3
        if out and os.path.exists(out) and not ns.force:
            print(f"{out} exists (use --force)", file=sys.stderr)
            return 3
    if not os.path.exists(ns.snapshot):
        print(f"snapshot not found: {ns.snapshot}", file=sys.stderr)
        return 3
    try:
        # Lazy imports keep a missing runtime dependency from becoming exit 1,
        # which is reserved for a proven graph finding.
        from .audit import audit
        from .html_report import render
        rep, _ = audit(ns.snapshot, ns.max_findings)
        if ns.json:
            with open(ns.json, "w") as f:
                json.dump(rep, f, indent=1, default=str)
        if ns.html:
            with open(ns.html, "w") as f:
                f.write(render(rep))
    except ModuleNotFoundError as e:
        print(f"cannot audit: missing Python dependency {e.name!r}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"cannot audit: I/O error: {e}", file=sys.stderr)
        return 2
    except Exception:
        # Keep the full traceback for diagnosis, but never conflate a crash
        # with exit 1 (a successfully proven structural finding).
        import traceback
        print("cannot audit: unexpected internal error (NO VERDICT)", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 2
    s = rep.get("summary", {})
    print(f"status   : {rep['status']}" + (f" ({rep['reason']})" if rep.get("reason") else ""))
    print(f"layout   : {rep.get('layout', '?')}   nodes {s.get('nodes', '-')}   live {s.get('live', '-')}")
    print(f"verdict  : {s.get('verdict')}")
    if s.get("unreachable_proven") is not None:
        print(f"findings : UNREACHABLE_PROVEN={s['unreachable_proven']}  TOMBSTONE_DEPENDENT={s['tombstone_dependent']}  "
              f"reachable_not_claimed={s['reachable_not_claimed']}")
    print(f"api      : {rep.get('api_status', '-')[:60]}...")
    po = rep.get("persisted_observations")
    if po:
        print(f"persisted-files-only (descriptive, NOT a verdict): unreachable_proven={po['unreachable_proven']} "
              f"tombstone_dependent={po['tombstone_dependent']} reachable_not_claimed={po['reachable_not_claimed']}")
    for f in rep.get("findings", [])[:10]:
        print(f"  {f['class']:<20} id={f['id']!r:<14} label={f['label']:<8} in-edges(L0)={f['in_degree_layer0']}  {f['why']}")
    if rep["status"] in ("UNSUPPORTED_OR_CORRUPT", "SNAPSHOT_CHANGED_DURING_AUDIT", "INCONSISTENT_SNAPSHOT", "NOT_SETTLED", "SETTLEMENT_UNKNOWN", "OK_NO_IDMAP"):
        return 2
    return 1 if s.get("unreachable_proven") else 0


if __name__ == "__main__":
    sys.exit(main())
