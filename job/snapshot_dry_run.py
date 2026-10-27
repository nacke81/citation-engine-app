"""Dry run: print the new snapshot summary for a COPY of a snapshot payload (a JSON file). No network, no env, no portal, no write.

  python job/snapshot_dry_run.py tests/fixtures/snapshot-scc-2026-10-27.json

The file may be the bare payload or a footprint_snapshot row ({"payload": {...}}). Prints the old (frozen) summary fields if present, the state counts of
the rows as they are, and the summary after `snapshot.finalize` (what the next write would store).
"""
import collections, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import snapshot as SN


def run(path, out=print):
    d = json.load(open(path, encoding="utf-8"))
    p = d.get("payload", d) if isinstance(d, dict) else {}
    old = {k: p[k] for k in SN.FROZEN_KEYS if k in p}
    out("rows: %d" % len(p.get("directories") or []))
    out("states now: %s" % json.dumps(dict(sorted(collections.Counter(x.get("state") for x in p.get("directories") or []).items()))))
    out("old frozen fields: %s" % (json.dumps(old) if old else "none"))
    new = SN.finalize(p)
    out("states after: %s" % json.dumps(dict(sorted(collections.Counter(x.get("state") for x in new["directories"]).items()))))
    out("NEW SUMMARY: %s" % json.dumps(new["summary"]))
    out("live rows with napConsistent null (need a NAP read): %d" % sum(1 for x in new["directories"] if x.get("state") == "live" and x.get("napConsistent") is None))
    return new["summary"]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__); sys.exit(2)
    run(sys.argv[1])
