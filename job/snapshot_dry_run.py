"""Dry run: print the new snapshot summary for a COPY of a snapshot payload (a JSON file). No network, no env, no portal, no write.

  python job/snapshot_dry_run.py tests/fixtures/snapshot-scc-2026-10-27.json [QUEUE.json]

With a QUEUE file the run applies the same overlay as portal.write_run (every queue list); without one it is snapshot.finalize alone.

The file may be the bare payload or a footprint_snapshot row ({"payload": {...}}). Prints the old (frozen) summary fields if present, the state counts of
the rows as they are, and the summary after `snapshot.finalize` (what the next write would store).
"""
import collections, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import snapshot as SN


def run(path, queue_path=None, out=print, day="2026-10-27", proof_by_dir=None):
    d = json.load(open(path, encoding="utf-8"))
    p = d.get("payload", d) if isinstance(d, dict) else {}
    old = {k: p[k] for k in SN.FROZEN_KEYS if k in p}
    out("rows: %d" % len(p.get("directories") or []))
    out("states now: %s" % json.dumps(dict(sorted(collections.Counter(x.get("state") for x in p.get("directories") or []).items()))))
    out("old frozen fields: %s" % (json.dumps(old) if old else "none"))
    if queue_path:   # the same overlay write_run runs: every queue list
        import buildqueue
        rows = buildqueue.load_all_rows(queue_path)
        out("queue rows overlaid (all lists): %d" % len(rows))
        new = buildqueue.overlay_directories(p, rows, day)
        # t_9d36198a: the count basis write_run applies to SCC. No network here: proof = the queue rows' own proof (or the injected map), not ce_directory_status.
        import portal, transitions
        new = SN.apply_count_basis(new, portal.count_proof(rows, proof_by_dir if proof_by_dir is not None else {}), transitions.proof_problems)
        out("count basis applied (live row needs complete proof, GBP once; proof from queue rows only, ce_directory_status NOT read): unproven live rows -> couldnt_check")
    else:
        new = SN.finalize(p)
        out("count basis NOT applied (no queue file): NEW SUMMARY may overcount live rows that lack proof")
    out("rows after: %d" % len(new["directories"]))
    out("states after: %s" % json.dumps(dict(sorted(collections.Counter(x.get("state") for x in new["directories"]).items()))))
    out("NEW SUMMARY: %s" % json.dumps(new["summary"]))
    out("live rows with napConsistent null (need a NAP read): %d" % sum(1 for x in new["directories"] if x.get("state") == "live" and x.get("napConsistent") is None))
    return new["summary"]


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print(__doc__); sys.exit(2)
    run(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else None)
