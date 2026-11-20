"""NM Activities backfill (t_2211682c). One `deliverables` row per NM queue-history move into submitted / pending-verify / live / rejected, dated by the
history entry, plus every NM Verify Now verification that is live ("Verified your <directory> listing by phone code").

  python job/nm_activities_backfill.py              dry run: prints the planned rows (reads the portal only to skip rows already there)
  python job/nm_activities_backfill.py --write      POSTs the missing rows through portal.write_deliverables (the one writer), NM client id only

Idempotent by source_ref (`citation-transition:<queue row id>:<state>`, `citation-transition:<verification id>:verified`): rows whose source_ref is
already in `deliverables` for NM are skipped, so a second --write plans 0. A row that went into the same state twice keeps its first move.
Never SCC, never a state outside ACTIVITY_STATES (needs-human and created-unlisted are internal), no other table is written."""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import portal as P
import transitions as T

CLIENT = "NM"


def plan_queue_rows(q, client_id):
    """-> [row dict] one per first move into an activity state, in queue order. No network."""
    out, seen = [], set()
    for _key, _kind, rows in T._row_lists(q):
        for r in rows:
            if not str(r.get("id") or "").startswith("nm-"): continue
            for h in r.get("history") or []:
                to = h.get("to")
                if to not in T.ACTIVITY_STATES or h.get("from") == to or not h.get("at"): continue
                ref = "citation-transition:%s:%s" % (r["id"], to)
                if ref in seen: continue
                seen.add(ref)
                out.append(T.build_activity_record(client_id, r, to, h.get("evidence_url"), str(h["at"])[:10]))
    return out


# Verify Now verifications that really ended in an accepted code. Named, not inferred: a live citation_verification row can also be closed by hand
# (a25e00ff, alignable.com, Nate 2026-11-20) and that is NOT "verified by code". Thumbtack: request db1fdaaa, accepted 2026-11-19 18:19:43Z.
CODE_VERIFIED = (("thumbtack.com", "2026-11-19", "db1fdaaa"),)


def plan_verified_rows(ver_rows, client_id):
    """ver_rows: citation_verification rows (id, directory, verification_type, state, verified_at) of NM. Only the CODE_VERIFIED ones (same directory, verified that day, live)."""
    out = []
    for v in ver_rows or []:
        if v.get("state") != "live" or not v.get("verified_at") or v.get("verification_type") not in ("phone-call", "sms"): continue
        if (v.get("directory"), str(v["verified_at"])[:10]) not in {(d, day) for d, day, _r in CODE_VERIFIED}: continue
        out.append(T.build_verified_activity(client_id, v["directory"], v["verification_type"], v["id"], str(v["verified_at"])[:10]))
    return out


def plan(q, ver_rows, have, client_id):
    rows = plan_queue_rows(q, client_id) + plan_verified_rows(ver_rows, client_id)
    return [r for r in rows if r["source_ref"] not in have]


def run(queue_path, write, portal=None, have=None):
    client_id = P.client_for(CLIENT)
    q = T._read(queue_path)
    ver = []
    if portal is not None:
        ver = portal.call("GET", "citation_verification?client_id=eq.%s&state=eq.live&select=id,directory,verification_type,state,verified_at" % client_id, None, "return=representation") or []
        have = P.existing_source_refs(portal, client_id)
    rows = plan(q, ver, have or set(), client_id)
    res = {"client": CLIENT, "client_id": client_id, "planned": len(rows), "existing_known": portal is not None, "rows": rows, "written": 0}
    if write:
        if portal is None: raise P.PortalWriteError("--write needs the portal")
        if rows: P.write_deliverables(portal, rows, now=rows[0]["approved_at"])
        res["written"] = len(rows)
    return res


def main(argv=None, portal=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--queue", default=None)
    n = ap.parse_args(argv)
    queue = n.queue or T.tenant_of(CLIENT)["queue_default"]()
    try:
        if portal is None:
            try: portal = P.Portal(*P.load_portal_env())
            except Exception as e:
                if n.write: raise
                print("portal not reachable (%s): dry run lists every queue move, existing rows unknown" % type(e).__name__, file=sys.stderr)
        res = run(queue, n.write, portal)
    except Exception as e:
        print("FAILED: %s" % e, file=sys.stderr); return 2
    print(json.dumps(res, indent=2))
    print("planned %d row(s)%s" % (res["planned"], "; written %d" % res["written"] if n.write else " (dry run, nothing written)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
