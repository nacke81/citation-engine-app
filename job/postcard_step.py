"""Live postcard step: read the client's code once, enter it at the Directory, record the result (no code anywhere).

  python job/postcard_step.py            real run (consume + enter + record); meant for the 12 hourly Task Scheduler job (job/postcards.cmd)
  python job/postcard_step.py --dry      lists the rows that would be consumed; consumes nothing, enters nothing, writes nothing

Per row (citation_verification: verification_type postcard, state requires_verification, code_received_at set, SCC only):
  1. No code entry registered for the Directory -> the row is SKIPPED and consume() is NOT called. consume() destroys the code,
     so it is only called when something can use it right away.
  2. consume(portal, id) -> the code, in memory only. None means the portal already purged it (expired or used): reported, no retry loop.
  3. enter(directory, code) -> "accepted" | "rejected". Any exception counts as "error".
  4. One citation_verification_attempt row (verified | failed | retry) with a fixed note. The note never carries the code
     (the table also refuses 4+ digit runs and the word "code"). The row's state is NOT changed here: live needs the public
     page proof (weekly Proof/recheck), exactly like every other state change.
  The portal trigger clears code_received_at on consume, so a rejected code lets the client send a fresh one.

The code is never logged, printed, put in a queue file, history, Activities, or in the result this module returns.
Expiry: the portal keeps a code 72 hours after the client submits it and purges expired codes on the next consume. This step must
run at least once inside every 72 hours. It runs every 12 hours (postcards.cmd) and warns when a waiting row is older than 48 hours.
"""
import json, os, sys, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import portal as P
import postcard_codes as PC

CLIENT = "SCC"
ATTEMPT_PATH = "citation_verification_attempt"
EXPIRY_HOURS = 72
WARN_AFTER_HOURS = 48
NOTES = {  # fixed text only: nothing from the Directory page or the code is ever copied in
    "verified": "postcard code entered at the Directory and accepted",
    "failed": "postcard code entered at the Directory and rejected; the client was not asked again yet",
    "retry": "postcard code could not be entered this run; the code was cleared, ask the client to send it again",
}
SELECT = ("citation_verification?select=id,client_id,directory,code_received_at"
          "&verification_type=eq.postcard&state=eq.requires_verification&code_received_at=not.is.null&client_id=eq.%s&order=code_received_at.asc")

# Directory -> callable(directory, code) -> "accepted" | "rejected". Filled by a Directory playbook that has seen the real code-entry page.
# Empty on purpose: no Directory's postcard entry form has been observed yet, and guessing a form would burn the code.
ENTERERS = {}


def _age_hours(ts, now):
    try:
        t = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (now - t).total_seconds() / 3600.0
    except Exception:
        return None


def run(portal=None, enterers=None, dry=False, now=None, log=print):
    """-> list of {id, directory, outcome, age_hours}. outcome: skipped-no-entry | would-consume | no-code | accepted | rejected | error. Never holds a code."""
    enterers = ENTERERS if enterers is None else enterers
    now = now or datetime.datetime.now(datetime.timezone.utc)
    cid = P.client_for(CLIENT)
    portal = portal or P.Portal(*P.load_portal_env())
    rows = portal.call("GET", SELECT % cid) or []
    out = []
    for r in rows:
        vid, d = r["id"], r["directory"]
        age = _age_hours(r.get("code_received_at"), now)
        res = {"id": vid, "directory": d, "age_hours": None if age is None else round(age, 1)}
        if age is not None and age >= WARN_AFTER_HOURS:
            log("POSTCARD WARNING: %s waited %.0fh of the %dh the code lives" % (vid, age, EXPIRY_HOURS))
        enter = enterers.get(d)
        if enter is None:
            res["outcome"] = "skipped-no-entry"   # leave the code in the portal; do not consume what we cannot use
        elif dry:
            res["outcome"] = "would-consume"
        else:
            res["outcome"] = _one(portal, cid, vid, d, enter)
        out.append(res)
        log("POSTCARD %s %s %s" % (res["outcome"], d, vid))
    return out


def _one(portal, cid, vid, directory, enter):
    try:
        code = PC.consume(portal, vid)
    except PC.PostcardCodeError:
        return "error"   # consume failed: nothing was read, so nothing to record
    if code is None:
        return "no-code"
    try:
        verdict = enter(directory, code)
    except BaseException:
        verdict = "error"   # the exception text could hold the code; keep only the fact
    finally:
        code = None
    outcome = {"accepted": "verified", "rejected": "failed"}.get(verdict, "retry")
    _record(portal, cid, vid, outcome)
    return {"verified": "accepted", "failed": "rejected", "retry": "error"}[outcome]


def _record(portal, cid, vid, outcome):
    try:
        portal.call("POST", ATTEMPT_PATH, [{"citation_verification_id": vid, "client_id": cid, "outcome": outcome, "note": NOTES[outcome]}],
                    prefer="return=minimal")
        return True
    except Exception as e:
        print("POSTCARD RECORD FAILED: %s: %s" % (vid, type(e).__name__), file=sys.stderr, flush=True)
        return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        res = run(dry="--dry" in argv)
    except Exception as e:
        print("POSTCARD STEP FAILED: " + type(e).__name__, file=sys.stderr, flush=True)
        return 1
    print("POSTCARD STEP OK", json.dumps({"rows": len(res), "outcomes": [r["outcome"] for r in res]}), flush=True)
    return 1 if any(r["outcome"] == "error" for r in res) else 0


if __name__ == "__main__":
    sys.exit(main())
