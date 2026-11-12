"""Verify Now agent helper (t_218b03ef). The submitter AGENT calls this instead of raw RPCs; it never holds the portal service key (this
process reads it from the portal env pointer, the agent only sees stdout and the exit code).

  python job/verify_step.py sent   --request-id X --masked "(629) ***-2578"   the code was just sent to that number
  python job/verify_step.py code   --request-id X                              waits up to 30 min, prints the code ONLY on stdout
  python job/verify_step.py result --request-id X --outcome accepted|rejected  the Directory accepted or rejected the typed code

Exit codes: 0 done | 2 bad arguments | 3 superseded (the client asked for a new code or the portal closed the request: stop, do not finish) |
            4 no code within 30 min (the request is finished failed/code_expired) | 5 refused or failed (nothing was sent or recorded).

The helper owns mark_code_sent, consume_verify_code, the superseded check, set_verification_live and finish_code_request. Every call first
re-reads the request and runs the same bridge.fence() the bridge and the send run use. A code is held in a local variable and written to
stdout once; it is never logged, put in an exception message, or sent anywhere else. stderr carries request ids and reason words only.
"""
import argparse, datetime, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import portal as P
import verify_bridge as B

LIVE_STATUSES = ("code_sent", "checking")
POLL_EVERY_S = 10
POLL_MAX_S = B.POLL_MAX_S
OK, BAD_ARGS, SUPERSEDED, EXPIRED, REFUSED = 0, 2, 3, 4, 5


def log(msg):
    print("verify_step: " + msg, file=sys.stderr, flush=True)


def _claimed(portal, request_id, statuses):
    """-> (req, row) when the request is in one of `statuses` and passes the fence, else (None, None). No exception text is logged."""
    try:
        req = B.request_row(portal, request_id)
    except Exception as e:
        log("request read failed: %s" % type(e).__name__); return None, None
    if not req or req.get("status") not in statuses:
        log("%s is not in %s" % (request_id, "/".join(statuses))); return None, None
    verdict, row = B.fence(req, portal)
    if verdict != "ok":
        log("fence refused %s: %s" % (request_id, verdict)); return None, None
    return req, row


def step_sent(request_id, masked, portal, rpc, now_dt=None):
    req, _row = _claimed(portal, request_id, ("starting",))
    if not req: return REFUSED
    try: rpc.mark_sent(request_id, masked)
    except B.BridgeError as e:
        log(str(e)); return REFUSED
    t0 = B._parse(req.get("requested_at"))
    now_dt = now_dt or datetime.datetime.now(datetime.timezone.utc)
    if t0: log("click_to_send_s=%d request=%s" % ((now_dt - t0).total_seconds(), request_id))   # Nate stop 7: the measured click-to-send
    log("sent recorded for %s" % request_id)
    return OK


def step_code(request_id, portal, rpc, out=None, sleep=time.sleep, now=time.time):
    out = out or sys.stdout
    if not _claimed(portal, request_id, LIVE_STATUSES)[0]: return REFUSED
    deadline = now() + POLL_MAX_S
    misses = 0
    code = None
    while True:
        try:
            cur = B.request_row(portal, request_id)
            if cur is not None and cur.get("status") not in LIVE_STATUSES:   # a PRESENT row that is no longer waiting = superseded
                log("superseded: %s is no longer waiting for a code; no finish" % request_id); return SUPERSEDED
            if cur is None:   # an empty read is a miss, not a verdict (Nate stop 5)
                raise B.BridgeError("empty read")
            code = rpc.consume(request_id); misses = 0
        except B.BridgeError as e:
            misses += 1; log("poll miss %d: %s" % (misses, e))
            if misses >= 3: return _finish(rpc, request_id, "failed", "other", REFUSED)
        except Exception as e:
            misses += 1; log("poll miss %d: %s" % (misses, type(e).__name__))
            if misses >= 3: return _finish(rpc, request_id, "failed", "other", REFUSED)
        if code:
            try:
                out.write(code + "\n"); out.flush()
            finally:
                code = None
            return OK
        if now() >= deadline:
            return _finish(rpc, request_id, "failed", "code_expired", EXPIRED)
        sleep(POLL_EVERY_S)


def _finish(rpc, request_id, status, fail_code, rc):
    try: rpc.finish(request_id, status, fail_code)
    except B.BridgeError as e: log(str(e))
    log("finished %s %s%s" % (request_id, status, "/" + fail_code if fail_code else ""))
    return rc


def step_result(request_id, outcome, portal, rpc, now_dt=None):
    if outcome not in ("accepted", "rejected"): return BAD_ARGS
    req, row = _claimed(portal, request_id, LIVE_STATUSES)
    if not req:
        return SUPERSEDED if _closed_by_portal(portal, request_id) else REFUSED
    if outcome == "rejected":
        return _finish(rpc, request_id, "failed", "code_rejected", OK)
    from verify_send import set_live
    try:
        live = set_live(portal, row, req["client_id"], now_dt)
    except Exception as e:
        log("set live failed: %s" % type(e).__name__); live = False
    if not live:
        log("row could not be set live after an accepted code")
        return _finish(rpc, request_id, "failed", "other", REFUSED)
    return _finish(rpc, request_id, "verified", None, OK)


def _closed_by_portal(portal, request_id):
    try:
        cur = B.request_row(portal, request_id)
    except Exception:
        return False
    return bool(cur) and cur.get("status") not in LIVE_STATUSES + ("starting", "requested")


def main(argv=None, portal=None, rpc=None, out=None):
    a = argparse.ArgumentParser(description="Verify Now agent helper")
    sub = a.add_subparsers(dest="cmd", required=True)
    for name in ("sent", "code", "result"):
        s = sub.add_parser(name); s.add_argument("--request-id", required=True)
        if name == "sent": s.add_argument("--masked", required=True)
        if name == "result": s.add_argument("--outcome", required=True, choices=("accepted", "rejected"))
    try:
        n = a.parse_args(argv)
    except SystemExit:
        return BAD_ARGS
    if not B.UUID_RE.match(n.request_id): log("bad request id"); return BAD_ARGS
    try:
        portal = portal or P.Portal(*P.load_portal_env())
    except Exception as e:
        log("portal env unavailable: %s" % type(e).__name__); return REFUSED
    rpc = rpc or B.VerifyRpc(portal)
    if n.cmd == "sent": return step_sent(n.request_id, n.masked, portal, rpc)
    if n.cmd == "code": return step_code(n.request_id, portal, rpc, out)
    return step_result(n.request_id, n.outcome, portal, rpc)


if __name__ == "__main__":
    sys.exit(main())
