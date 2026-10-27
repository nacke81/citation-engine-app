"""Weekly Proof writer (kanban t_f081c9ba). Makes the builder result cards (New listings live / Claimed / Fixed) count.

For every SCC queue row waiting on a Directory (submitted, pending-verify, needs-human) this run's re-check decides:
  * found live + permalink + name/street/phone all match + no diffs -> write proof_url, proof_nap, proof_at, proof_nap_match=true, build_action
    on ce_directory_status, THEN move the row to live through transitions.record_transition (which fires the client-voiced Activities row).
    Proof goes first: if the transition fails the row stays waiting and the next run retries; never a live row without Proof.
  * found but the NAP differs -> proof_nap_match=false, any older Proof cleared, state untouched.
  * anything else (couldn't check, absent, unsearchable, no permalink) -> nothing written.
Only THIS run's checks are read. No stored Proof is ever carried over. No Directory traffic of any kind: the checks were gathered by the
read-only discovery before this runs. Uses the injectable `db` (see directories.py) and `record` (transitions.record_transition).
"""
import datetime, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buildqueue as Q
import directories as D
import listing as L

WAITING = ("submitted", "pending-verify", "needs-human", "created-unlisted")
PROOF_COLS = ("build_action", "proof_url", "proof_nap", "proof_at", "proof_nap_match")


def effective(c):
    """When the matched page differs from the cited permalink, build() hands us the permalink's own NAP/flags as `_proof`; those replace the matched page's."""
    p = c.get("_proof")
    return dict(c, **p) if p is not None else c


def verdict(c):
    """'match' | 'mismatch' | None (couldn't tell: write nothing). Pure."""
    c = effective(c)
    if c.get("biz") != "SCC" or c.get("result") != "found":
        return None
    if c.get("name_match") is None and c.get("match") is None:
        return None
    if not str(c.get("nap_shown") or "").strip():
        return None   # no NAP text to quote: cannot prove it; a live row without proof_nap would never count or be re-checked
    url = c.get("url")
    if not (url and L.is_permalink(c["directory"], url)):
        return None   # found but no record page to cite: cannot prove, cannot call a mismatch either
    clean = bool(c.get("name_match")) and bool(c.get("street_match")) and bool(c.get("phone_match")) and bool(c.get("match")) and not (c.get("diffs") or [])
    return "match" if clean else "mismatch"


def build_action(row_kind, row, claim_status):
    """new | claim | fix from queue_kind and this run's claim status."""
    if row_kind == "create": return "new"
    if row_kind == "claim" or (claim_status == "claimed" and not row.get("wrong_field")): return "claim"
    return "fix"


def _waiting_rows(queue):
    import transitions as T
    out = {}
    for _key, kind, rows in T._row_lists(queue):
        for r in rows:
            if r.get("state") in WAITING and r.get("directory") and not Q.not_due(r):   # t_d2f75685: recheck_due in the future = not touched
                out.setdefault(r["directory"], []).append((kind, r))
    return out


def proof_step(checks, day, *, queue_path=None, db=None, record=None, now=None):
    """Returns {moved:[{row, directory, proof_url, build_action}], mismatched:[...], untouched:[...], errors:[...]}. Never raises per-row."""
    out = {"moved": [], "mismatched": [], "untouched": [], "errors": []}
    path = queue_path or Q.QUEUE_PATH
    try:
        with open(path, encoding="utf-8") as f: queue = json.load(f)
    except Exception as e:
        out["errors"].append("queue: %s" % (str(e)[:200] or type(e).__name__)); return out
    waiting = _waiting_rows(queue)
    if not waiting: return out
    if record is None:
        import transitions; record = transitions.record_transition
    db = db or D.DirDB()
    stamp = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for c in checks:
        d = c.get("directory")
        if c.get("biz") != "SCC" or d not in waiting: continue
        c = effective(c)   # NAP quoted and verdict both come from the proof_url page
        v = verdict(c)
        if v is None:
            out["untouched"].append(d); continue
        if v == "mismatch":
            try:
                D._upsert_status(db, [D._status_row(db, "SCC", d, day, proof_nap_match=False, proof_url=None, proof_nap=None, proof_at=None, build_action=None)])
                out["mismatched"].append(d)
            except Exception as e:
                out["errors"].append("%s: %s" % (d, str(e)[:200] or type(e).__name__))
            continue
        for kind, row in waiting[d]:   # every waiting row on this Directory moves, not just the first
            try:
                action = build_action(kind, row, (c.get("_claim") or {}).get("claim_status"))
                D._upsert_status(db, [D._status_row(db, "SCC", d, day, proof_url=c["url"], proof_nap=c.get("nap_shown"), proof_at=stamp,
                                                    proof_nap_match=True, build_action=action)])
                res = record("SCC", row["id"], "live", c["url"], "weekly re-check: listing live, NAP matches canonical", queue_path=path, today=day)
                if res.get("errors"): out["errors"].append("%s: %s" % (d, "; ".join(res["errors"])[:200]))
                out["moved"].append({"row": row["id"], "directory": d, "proof_url": c["url"], "build_action": action})
            except Exception as e:
                out["errors"].append("%s: %s" % (d, str(e)[:200] or type(e).__name__))
    return out
