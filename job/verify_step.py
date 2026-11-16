"""Verify Now agent helper (t_218b03ef). The submitter AGENT calls this instead of raw RPCs; it never holds the portal service key (this
process reads it from the portal env pointer, the agent only sees stdout and the exit code).

  python job/verify_step.py arm    --request-id X                                 pre-send fence, run right BEFORE the send click: nonzero (5) = STOP, do not click
  python job/verify_step.py sent   --request-id X --masked "(629) ***-2578" --evidence "<page text>"   the code was just sent to that number; the evidence is the short page text after the click (code box / code-sent text, no error). Missing evidence = refused (5)
  python job/verify_step.py fail   --request-id X --reason directory_refused_phone --evidence "<page text>"   the Directory refused the send: the request ends failed, the text is kept in the stage file
  python job/verify_step.py code   --request-id X [--wait-s 540]               waits up to --wait-s (max 540) per call, prints the code ONLY on stdout
  python job/verify_step.py result --request-id X --outcome accepted|rejected  the Directory accepted or rejected the typed code
  python job/verify_step.py stage  --request-id X --name signed_in             scoreboard: the sign-in just finished (before the send)
  python job/verify_step.py note   --request-id X --text "..."                     one line: what in the playbook was wrong (no values; max 400 chars)
  python job/verify_step.py trace  --request-id X --action goto|click|fill|press --url U [--selector S]   one step before the send (promotion trace)

Exit codes: 0 done | 2 bad arguments | 3 superseded (the client asked for a new code or the portal closed the request: stop, do not finish) |
            4 no code within 30 min of code_sent_at (the request is finished failed/code_expired, once) | 5 refused or failed (nothing was sent or recorded) |
            6 no code yet in this call: run `code` again (nothing finished; the 30 min limit does not restart).

The helper owns mark_code_sent, consume_verify_code, the superseded check, set_verification_live and finish_code_request. Every call first
re-reads the request and runs the same bridge.fence() the bridge and the send run use. A code is held in a local variable and written to
stdout once; it is never logged, put in an exception message, or sent anywhere else. stderr carries request ids and reason words only.
"""
import argparse, datetime, json, os, re, sys, time
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import portal as P
import verify_bridge as B
import verify_scoreboard as SB
import verify_dom as VD

LIVE_STATUSES = ("code_sent", "checking")
POLL_EVERY_S = 10
POLL_MAX_S = B.POLL_MAX_S
OK, BAD_ARGS, SUPERSEDED, EXPIRED, REFUSED, NO_CODE_YET = 0, 2, 3, 4, 5, 6
WAIT_MAX_S = 540        # per call; the agent's Hermes terminal allows 600 s in the foreground and kills anything longer
WAIT_DEFAULT_S = 540


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
    SB.touch_alive(request_id)   # t_c6eee3cb: the sweeper keeps a live agent's `starting` row (liveness, not wall clock)
    return req, row


ARM_MARGIN_S = 60   # the send must be clicked at least this long before the portal shows could_not_start: B.SWEEP_AFTER_S (600) = the portal verify-now START_LIMIT_MS (10 min), which derives could_not_start at READ time from requested_at whatever the bridge status is. The liveness hold (B.SWEEP_HARD_CAP_S) never extends this.


def _late_reopen(portal, request_id, now_dt=None):
    """t_c6eee3cb (b): `sent` arrived for a request the sweeper already closed (could_not_start) within the last LATE_SENT_WINDOW_S of its sweep, and no
    NEWER request exists for the same verification row. Then the text really went out and the client must get the code box: move the row back to
    `starting` (one conditional PATCH, exactly one row or nothing), so mark_code_sent can run. -> (req, row) or (None, None). Logged as late_sent."""
    try:
        req = B.request_row(portal, request_id)
        if not req or req.get("status") != "could_not_start": return None, None
        fin = B._parse(req.get("finished_at"))   # the sweep time: finish_code_request sets finished_at = now(); requested_at only when it is null
        t0 = fin or B._parse(req.get("requested_at"))
        if t0 is None: return None, None
        age = ((now_dt or datetime.datetime.now(datetime.timezone.utc)) - t0).total_seconds()
        if age > B.LATE_SENT_WINDOW_S + (0 if fin else B.SWEEP_AFTER_S):
            log("late_sent refused %s: swept longer ago than %d s" % (request_id, B.LATE_SENT_WINDOW_S)); return None, None
        verdict, row = B.fence(req, portal)
        if verdict != "ok":
            log("late_sent fence refused %s: %s" % (request_id, verdict)); return None, None
        newer = portal.call("GET", "%s?select=id&citation_verification_id=eq.%s&requested_at=gt.%s&limit=1" % (B.REQUEST_TABLE, req["citation_verification_id"], req["requested_at"]))
        if newer:
            log("late_sent refused %s: a newer request exists for this row" % request_id); return None, None
        got = portal.call("PATCH", "%s?id=eq.%s&status=eq.could_not_start" % (B.REQUEST_TABLE, request_id), {"status": "starting", "fail_code": None, "finished_at": None}, prefer="return=representation")
        if not got or len(got) != 1:
            log("late_sent refused %s: the row could not be reopened" % request_id); return None, None
        log("late_sent %s: swept request reopened because its text went out" % request_id)
        return dict(req, status="starting"), row
    except Exception as e:
        log("late_sent failed: %s" % type(e).__name__); return None, None


VAULT_WAIT_S, VAULT_POLL_S = 120, 2


def step_arm(request_id, portal, now_dt=None, sleep=time.sleep):
    """t_c6eee3cb pre-send fence: the agent runs this immediately before the send click. 0 = go; REFUSED (5) = STOP, do not click: the request is not
    `starting` (swept, superseded, already sent), fails the bridge fence, has no readable requested_at, or is past SWEEP_AFTER_S - ARM_MARGIN_S (540 s) old
    (the portal shows could_not_start from SWEEP_AFTER_S = its START_LIMIT_MS, so a later send is a text the client was told never started). Read-only: no stamp, no RPC."""
    req, _row = _claimed(portal, request_id, ("starting",))
    if not req: return REFUSED
    waited = 0   # t_4ee21e60: the agent starts while the send run still checks the vault item; no send until that check passed (it fails closed and kills the agent)
    while not B.vault_ok(request_id):
        if waited >= VAULT_WAIT_S: log("arm refused %s: the vault identity check has not passed" % request_id); return REFUSED
        sleep(VAULT_POLL_S); waited += VAULT_POLL_S
        req, _row = _claimed(portal, request_id, ("starting",))   # the check may have failed and closed the request meanwhile
        if not req: return REFUSED
    t0 = B._parse(req.get("requested_at"))
    if t0 is None:
        log("arm refused %s: no requested_at" % request_id); return REFUSED
    now_dt = now_dt or datetime.datetime.now(datetime.timezone.utc)
    age = (now_dt - t0).total_seconds()
    limit = B.SWEEP_AFTER_S - ARM_MARGIN_S   # 540 s. NOT the hard cap: the portal's START_LIMIT_MS (10 min) says could_not_start whatever the bridge holds
    if age >= limit:
        log("arm refused %s: request is %d s old (limit %d s); do not send" % (request_id, age, limit)); return REFUSED
    log("armed %s: %d s old, %d s left before the cutoff" % (request_id, age, limit - age))
    return OK


EVIDENCE_MAX = 300
ERROR_TEXT = re.compile(r"(?i)\b(not a (mobile|valid|cell)|invalid|error|couldn'?t|could not|can'?t|unable|try again|failed|incorrect|not recogni[sz]ed|too many)\b")
# text and call path alike: the page must show a code-entry field or a sent/called text. A bare click or "we are calling you" with no code field never counts.
LANDED_TEXT = re.compile(r"(?i)(code (was |has been )?(sent|texted|emailed)|\b(sent|texted)\b[^.?!]{0,40}\bcode|verification code|enter (the |your |a )?(\d-digit )?code|confirmation code|security code|code (field|box|input))")
# t_6168a061 (round 4, Nate ruling): LANDED_TEXT above is main's, unchanged. landed() splits the evidence into clauses and drops a clause that is a click, a future promise, or a negated send; the rest is searched.
CLAUSE = re.compile(r"[.?!;,\n/|]+|\s[-\u2013\u2014]+\s")
# a clause that starts with a send control (optionally "I clicked/tapped ...") names a button, not a landed send
SEND_CONTROL = re.compile(r"(?i)^\W*(?:(?:i |we )?(?:click(?:ed)?|tap(?:ped)?|press(?:ed)?|hit)\s+(?:the\s+|on\s+)?['\"\u201c\u2018]?\s*)?(send|resend|text me|call me|get|request)\b")
# pre-click copy ("We'll send a verification code") is a promise, not a send
FUTURE_SEND = re.compile(r"(?i)(\bwill|['\u2019]ll|\bgoing to)\s+(now\s+)?(send|text|email|call)\b")
PAST = re.compile(r"(?i)\b(sent|texted|called|emailed|received)\b")
# a negation that directly governs the send verb (not/never/n't + optional auxiliaries + sent/send/texted/received, `yet to send`, `no <X> code (was) sent`)
NEGATED_SEND = re.compile(r"(?i)((\b(not|never)\b|n['\u2019]t\b)(\s+(yet|been|be|have|has|had|was|were|is|are|do|does|did|ever|really|currently))*\s+(sent|send|texted|text|emailed|received)\b|\byet to (send|text|email)\b|\bno (verification |confirmation |security |sms |text )?codes? (has been |was |is )?(yet )?(sent|texted|emailed|received)\b)")
def landed(text):
    kept = [c for c in CLAUSE.split(text) if not (NEGATED_SEND.search(c) or ((SEND_CONTROL.search(c) or FUTURE_SEND.search(c)) and not PAST.search(c)))]
    return bool(LANDED_TEXT.search(". ".join(kept)))
# t_4ee21e60 rework: ONLY a refusal of the send itself may finish the request failed. Help text on a landed code page ("Didn't receive it? Try again", "Invalid code will lock...")
# is not a refusal; it refuses `sent` with nothing recorded and the agent quotes only the code text. "too many" counts only when no code field shows.
SEND_REFUSAL = re.compile(r"(?i)\b(not an? (mobile|valid|cell)( phone)?( number)?|invalid (phone|number)|(couldn'?t|could not|unable to|failed to) send)\b")
TOO_MANY = re.compile(r"(?i)\btoo many (requests|attempts)\b")
NO_ERROR_PHRASE = re.compile(r"(?i)\b(no|without|not any|zero) (visible |inline )?(error|errors|error text|error message|error messages)\b")   # an agent's own "no error" report is not an error
FAIL_REASONS = {"directory_refused_phone": "send_failed", "send_failed": "send_failed"}


def clean_evidence(text):
    """t_4ee21e60: -> (one-line page text, None) or (None, why). Short, no value in it (email, phone, 6+ digit run, code assignment)."""
    import playbook as PB
    if not isinstance(text, str): return None, "missing"
    t = re.sub(r"\s+", " ", text).strip()
    if not t: return None, "missing"
    if len(t) > EVIDENCE_MAX: return None, "too long"
    try: PB._check_text("evidence", t.replace("{", "(").replace("}", ")"))
    except PB.PlaybookError: return None, "carries a value"
    return t, None


def step_fail(request_id, reason, evidence, portal, rpc):
    """t_4ee21e60: the Directory refused the send (an error shows near the phone field). Stores the page text, finishes the request failed/send_failed so the
    portal shows a failed row and no code box. Only while the request is `starting` (nothing was recorded as sent). -> OK | REFUSED | BAD_ARGS."""
    if reason not in FAIL_REASONS: return BAD_ARGS
    text, why = clean_evidence(evidence)
    if text is None: log("fail refused: evidence %s" % why); return BAD_ARGS
    req, _row = _claimed(portal, request_id, ("starting",))
    if not req: return REFUSED
    SB.set_refusal(request_id, text)
    try: rpc.finish(request_id, "failed", FAIL_REASONS[reason])
    except B.BridgeError as e:
        log(str(e)); return REFUSED
    log("fail recorded for %s: %s" % (request_id, reason))
    return OK


DOM_CHECK = VD.check   # t_00a83602: tests swap this; (cdp_url) -> True | False | None


def _page_landed(request_id, text, portal):
    """t_00a83602: does the page show a landed send? The tenant's Chrome (CDP, read-only) decides when it can be read: a visible code input = landed
    (whatever the text says), a read page with none = refused (whatever the text says). Chrome not readable = the text gate `landed()` alone."""
    try:
        req = B.request_row(portal, request_id)
        cdp = VD.tenant_cdp((req or {}).get("client_id"))
        seen = DOM_CHECK(cdp) if cdp else None
    except Exception as e:
        log("dom check failed (%s); falling back to the text" % type(e).__name__); seen = None
    if seen is None:
        ok = landed(text)
        if not ok: log("sent refused: evidence names no code field or code-sent text (dom unavailable)")
        else: log("dom unavailable; the evidence text is the only landed signal")
        return ok
    if seen:
        log("dom: visible code input; send landed"); return True
    log("sent refused: dom shows no visible code input (text %s landed)" % ("said" if landed(text) else "did not say")); return False


def step_sent(request_id, masked, portal, rpc, now_dt=None, evidence=None):
    """t_4ee21e60: `sent` needs page evidence that the send LANDED (a code box or a 'code sent' text) and no error text. No evidence, evidence that carries a
    value, evidence without a landed signal = REFUSED (nothing recorded). Evidence that reads as an error = the failure path (request finished failed)."""
    text, why = clean_evidence(evidence)
    if text is None: log("sent refused: evidence %s" % why); return REFUSED
    clean = NO_ERROR_PHRASE.sub(" ", text)
    if SEND_REFUSAL.search(clean) or (TOO_MANY.search(clean) and not landed(clean)):
        log("sent refused: the page refuses the send; recording the refusal"); step_fail(request_id, "directory_refused_phone", text, portal, rpc); return REFUSED
    if ERROR_TEXT.search(clean):
        log("sent refused: the evidence has an error word but not a send refusal; nothing recorded. If the page shows a real error near the phone field run `fail`; "
            "if the send landed, run `sent` again quoting only the code-box or code-sent text"); return REFUSED
    if not _page_landed(request_id, text, portal): return REFUSED
    req, _row = _claimed(portal, request_id, ("starting",))
    if not req and B.MASK_RE.match(str(masked or "")): req, _row = _late_reopen(portal, request_id, now_dt)   # t_c6eee3cb (b): a real send after the sweep still reaches the code box
    if not req: return REFUSED
    try: rpc.mark_sent(request_id, masked)
    except B.BridgeError as e:
        log(str(e)); return REFUSED
    t0 = B._parse(req.get("requested_at"))
    now_dt = now_dt or datetime.datetime.now(datetime.timezone.utc)
    SB.stamp(request_id, "send_clicked_at", now_dt)   # the agent runs `sent` right after it clicks send
    SB.stamp(request_id, "code_sent_at", now_dt)
    promote_trace(request_id, req, _row)
    if t0: log("click_to_send_s=%d request=%s" % ((now_dt - t0).total_seconds(), request_id))   # Nate stop 7: the measured click-to-send
    log("sent recorded for %s" % request_id)
    return OK


def step_code(request_id, portal, rpc, out=None, sleep=time.sleep, now=time.time, wait_s=WAIT_DEFAULT_S, wall=None):
    """One bounded call (wait_s <= 540, under the agent terminal's 600 s foreground cap). The 30 min limit is anchored to the request's
    code_sent_at, so repeated NO_CODE_YET calls cannot stretch it. Expiry is checked before consume, so a late code is never taken."""
    out = out or sys.stdout
    wait_s = max(1, min(int(wait_s), WAIT_MAX_S))
    wall = wall or (lambda: datetime.datetime.now(datetime.timezone.utc))
    req, _row = _claimed(portal, request_id, LIVE_STATUSES)
    if not req: return REFUSED
    anchor = B._parse(req.get("code_sent_at"))
    if anchor is None:
        anchor = wall(); log("no code_sent_at on %s; anchoring the 30 min limit to this call" % request_id)
    expired = lambda: (wall() - anchor).total_seconds() >= POLL_MAX_S
    call_deadline = now() + wait_s
    misses = 0
    code = None
    while True:
        try:
            cur = B.request_row(portal, request_id)
            if cur is not None and cur.get("status") not in LIVE_STATUSES:   # a PRESENT row that is no longer waiting = superseded
                log("superseded: %s is no longer waiting for a code; no finish" % request_id); SB.finalize(request_id, "superseded"); return SUPERSEDED
            if cur is None:   # an empty read is a miss, not a verdict (Nate stop 5)
                raise B.BridgeError("empty read")
            if not expired():
                code = rpc.consume(request_id)
            misses = 0
        except B.BridgeError as e:
            misses += 1; log("poll miss %d: %s" % (misses, e))
            if misses >= 3: return _finish(rpc, request_id, "failed", "other", REFUSED)
        except Exception as e:
            misses += 1; log("poll miss %d: %s" % (misses, type(e).__name__))
            if misses >= 3: return _finish(rpc, request_id, "failed", "other", REFUSED)
        if code:
            SB.stamp(request_id, "code_submitted_at", wall())
            try:
                out.write(code + "\n"); out.flush()
            finally:
                code = None
            return OK
        if expired():
            return _finish(rpc, request_id, "failed", "code_expired", EXPIRED)
        if now() >= call_deadline:
            log("no code yet for %s; call again" % request_id); return NO_CODE_YET
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
        if _closed_by_portal(portal, request_id):
            SB.finalize(request_id, "superseded"); return SUPERSEDED
        return REFUSED
    SB.stamp(request_id, "code_entered_at", now_dt)   # typed into the Directory and the page answered
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


# ---- scoreboard stage + step trace (t_e49457af) ---------------------------------------------------------------------------------------
TRACE_ACTIONS = ("goto", "click", "fill", "press")
TRACE_MAX_STEPS = 80
STAGE_NAMES = {"signed_in": "signed_in_at", "ready": None}   # ready: only the agent_ready_at stamp in step_stage


def _trace_dir():
    return os.path.join(SB._dir(), "verify-traces")


def _trace_file(request_id):
    return os.path.join(_trace_dir(), "%s.jsonl" % request_id)


def step_stage(request_id, name, portal, now_dt=None):
    if name not in STAGE_NAMES: return BAD_ARGS
    req, _row = _claimed(portal, request_id, ("starting",))
    if not req: return REFUSED
    SB.stamp(request_id, "agent_ready_at", now_dt)   # any stage call is proof the agent is up (first write wins)
    if STAGE_NAMES[name]: SB.stamp(request_id, STAGE_NAMES[name], now_dt)
    return OK


NOTE_STATES = ("starting", "code_sent", "checking")


def clean_note_text(text):
    """-> the one-line note, or None when it is empty, over NOTE_MAX, or carries a value (6+ digit run, email, phone, code/password assignment)."""
    import playbook as PB
    if not isinstance(text, str): return None
    t = re.sub(r"\s+", " ", text).strip()
    if not t or len(t) > SB.NOTE_MAX: return None
    try: PB._check_text("note", t)
    except PB.PlaybookError: return None
    return t


def step_note(request_id, text, portal):
    """t_eae8e59f: the agent's note on the stored playbook, kept in the request's stage file. The bridge writes it into the playbook only after an
    accepted result. The text is never logged or echoed; a refused note stores nothing."""
    req, _row = _claimed(portal, request_id, NOTE_STATES)
    if not req: return REFUSED
    t = clean_note_text(text)
    if t is None: log("note refused (empty, over %d chars, or it carries a value)" % SB.NOTE_MAX); return REFUSED
    return OK if SB.set_note(request_id, t) else REFUSED


def clean_url(url):
    """http(s) only, query and fragment dropped (a code or token can ride there)."""
    p = urlsplit(str(url or "").strip())
    if p.scheme not in ("http", "https") or not p.netloc: return None
    return ("%s://%s%s" % (p.scheme, p.netloc, p.path))[:300]


def step_trace(request_id, action, url, selector, portal):
    """Append one step (action, URL, selector) to the request's trace. Only while the request is `starting` (before the send). There is no value
    argument: a typed secret or code has no way in. A selector holding a 6+ digit run is refused."""
    if action not in TRACE_ACTIONS: return BAD_ARGS
    u = clean_url(url)
    sel = (selector or "").strip()
    if u is None or len(sel) > 200 or "\n" in sel or re.search(r"\d{6,}", sel): return BAD_ARGS
    req, _row = _claimed(portal, request_id, ("starting",))
    if not req: return REFUSED
    SB.stamp(request_id, "agent_ready_at")   # fallback ready stamp (first write wins)
    f = _trace_file(request_id)
    try:
        os.makedirs(os.path.dirname(f), exist_ok=True)
        n = sum(1 for _ in open(f, encoding="utf-8")) if os.path.exists(f) else 0
        if n >= TRACE_MAX_STEPS: log("trace full"); return REFUSED
        with open(f, "a", encoding="utf-8") as h:
            h.write(json.dumps({"n": n + 1, "action": action, "url": u, "selector": sel or None, "at": SB.iso(SB.now())}, separators=(",", ":")) + "\n")
    except OSError as e:
        log("trace write failed: %s" % type(e).__name__); return REFUSED
    return OK


def promote_trace(request_id, req, row):
    """A clean agent send (the `sent` call succeeded): save the pre-send trace where a citation-engineer card can turn it into a send=script
    entry. -> the path, or None (no trace, or not an agent run). Never raises."""
    try:
        f = _trace_file(request_id)
        if not os.path.exists(f): return None
        steps = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
        ent = B.directory_entry((row or {}).get("directory"), req.get("channel")) or {}
        if not steps or ent.get("send") != "agent": return None
        d = os.path.join(_trace_dir(), "promote"); os.makedirs(d, exist_ok=True)
        out = os.path.join(d, "%s__%s__%s.json" % (ent["domain"], req.get("channel"), request_id))
        with open(out, "w", encoding="utf-8") as h:
            json.dump({"request_id": request_id, "domain": ent["domain"], "channel": req.get("channel"), "signin_url": ent.get("signin_url"),
                       "saved_at": SB.iso(SB.now()), "steps": steps, "next": "citation-engineer card: turn into a send=script entry"}, h, indent=1)
        log("trace saved for promotion: %d steps" % len(steps))
        return out
    except Exception as e:
        log("trace promote skipped: %s" % type(e).__name__); return None


def _closed_by_portal(portal, request_id):
    try:
        cur = B.request_row(portal, request_id)
    except Exception:
        return False
    return bool(cur) and cur.get("status") not in LIVE_STATUSES + ("starting", "requested")


def main(argv=None, portal=None, rpc=None, out=None):
    a = argparse.ArgumentParser(description="Verify Now agent helper")
    sub = a.add_subparsers(dest="cmd", required=True)
    for name in ("arm", "sent", "code", "result", "stage", "trace", "note", "fail"):
        s = sub.add_parser(name); s.add_argument("--request-id", required=True)
        if name == "stage": s.add_argument("--name", required=True, choices=tuple(STAGE_NAMES))
        if name == "trace":
            s.add_argument("--action", required=True, choices=TRACE_ACTIONS); s.add_argument("--url", required=True); s.add_argument("--selector", default="")
        if name == "note": s.add_argument("--text", required=True)
        if name == "sent": s.add_argument("--masked", required=True); s.add_argument("--evidence", default=None)   # t_4ee21e60: missing = refused by step_sent, not an argparse error
        if name == "fail": s.add_argument("--reason", required=True, choices=tuple(FAIL_REASONS)); s.add_argument("--evidence", required=True)
        if name == "code": s.add_argument("--wait-s", type=int, default=WAIT_DEFAULT_S)
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
    if n.cmd == "arm": return step_arm(n.request_id, portal)
    if n.cmd == "sent": return step_sent(n.request_id, n.masked, portal, rpc, evidence=n.evidence)
    if n.cmd == "fail": return step_fail(n.request_id, n.reason, n.evidence, portal, rpc)
    if n.cmd == "stage": return step_stage(n.request_id, n.name, portal)
    if n.cmd == "note": return step_note(n.request_id, n.text, portal)
    if n.cmd == "trace": return step_trace(n.request_id, n.action, n.url, n.selector, portal)
    if n.cmd == "code": return step_code(n.request_id, portal, rpc, out, wait_s=n.wait_s)
    return step_result(n.request_id, n.outcome, portal, rpc)


if __name__ == "__main__":
    sys.exit(main())
