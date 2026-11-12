"""Verify Now bridge (slice 1, SMS). One pass = sweep, claim, fence, start the send run. Meant to run every 60 s or less.

  python job/verify_bridge.py            one pass (a later card schedules it; this module creates no scheduled task)

Contract (portal card t_c55c728e), service role only, exact names:
  claim_code_request()                                   -> oldest 'requested' row, set 'starting' (or null)
  mark_code_sent(p_request_id, p_sent_to_masked)         mask looks like (502) ***-0101
  consume_verify_code(p_request_id)                      -> code text or null (delete-returning)
  finish_code_request(p_request_id, p_status, p_fail_code)
Row fields: id, citation_verification_id, client_id, channel, status, requested_at, claimed_at, code_sent_at.

Why a direct subprocess: a Kanban dispatcher hop measured 37 s to 8m25s in spike 1, which breaks the 10 minute bar. The send run
(job/verify_send.py) is started with subprocess.Popen from this pass. No card, no dispatcher tick.

Direct-run command for the submitter seat (verified to exist: `hermes -p citation-submitter chat --help` lists --query-file and --oneshot):
  hermes -p citation-submitter chat --query-file <file> --oneshot
That path starts an LLM turn and is NOT used by the bridge. The bridge runs the deterministic send script instead:
  python job/verify_send.py --request-id <uuid>

Rules this module holds:
  * No send without a claimed request id for that exact row. fence() is the ONE decision (bridge and send run both call it) and a
    request whose client_id does not match the verification row is refused before the send run starts or any Directory is touched.
  * A code is never read here. Logs and cards carry request ids and allowlisted reason codes only, never exception text.
  * Only the two allow-listed portal clients (portal.check_client). Slice 1 handles channel 'sms' and the Cylex playbook only.
  * Sweeper: requested/starting older than 10 minutes -> finish_code_request('could_not_start','timeout') and ONE Kanban card
    (idempotency key verify-now:<request_id>). Nothing stays in 'starting' forever.
"""
import datetime, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import portal as P

REQUEST_TABLE = "citation_code_request"   # contract table (portal card t_c55c728e); pinned by tests/verify_bridge_test.py
VERIFICATION_TABLE = "citation_verification"
STATUSES = ("verified", "could_not_start", "failed")
FAIL_CODES = ("timeout", "no_playbook", "signin_failed", "send_failed", "code_rejected", "code_expired", "resend", "other")
SWEEP_AFTER_S = 600
POLL_MAX_S = 1800
POST_SEND_SWEEP_S = POLL_MAX_S + 600   # 40 min: a send run that died after mark_code_sent
POST_SEND_FAIL = {"code_sent": "code_expired", "checking": "other"}
MAX_CLAIMS_PER_PASS = 3
CARD_TIMEOUT_S = 60
SMS_DIRECTORIES = ("cylex.us", "cylex.us.com")   # the only proven SMS Directory
MASK_RE = re.compile(r"^\(\d{3}\) \*\*\*-\d{4}$")
UUID_RE = re.compile(r"^[0-9a-fA-F-]{8,40}$")
_card_runner = None   # tests inject a fake; None means subprocess.run
_spawner = None       # tests inject a fake; None means subprocess.Popen


class BridgeError(Exception):
    pass


def log(msg):
    print("verify_bridge: " + msg, file=sys.stderr, flush=True)


def mask_phone(phone):
    """'+1 (502) 555-0101' -> '(502) ***-0101'. None when the input is not a 10 or 11 digit US number."""
    d = re.sub(r"\D", "", str(phone or ""))
    if len(d) == 11 and d[0] == "1": d = d[1:]
    return "(%s) ***-%s" % (d[:3], d[6:]) if len(d) == 10 else None


def directory_ok(directory):
    d = str(directory or "").lower().strip()
    if d.startswith("www."): d = d[4:]
    return d in SMS_DIRECTORIES


class VerifyRpc:
    """The 4 agent RPCs, exact names and arg names. Errors carry the RPC name and exception type only."""
    def __init__(self, portal):
        self.portal = portal

    def _rpc(self, name, body):
        try:
            return self.portal.call("POST", "rpc/" + name, body)
        except Exception as e:   # PortalWriteError text is scrubbed of the key, but keep only the type anyway
            raise BridgeError("%s failed: %s" % (name, type(e).__name__))

    def claim(self):
        got = self._rpc("claim_code_request", {})
        if isinstance(got, list): got = got[0] if got else None
        return got or None

    def mark_sent(self, request_id, masked):
        if not MASK_RE.match(str(masked or "")): raise BridgeError("mark_code_sent refused: bad mask")
        self._rpc("mark_code_sent", {"p_request_id": request_id, "p_sent_to_masked": masked})

    def consume(self, request_id):
        got = self._rpc("consume_verify_code", {"p_request_id": request_id})
        if isinstance(got, list): got = got[0] if got else None
        return got or None

    def finish(self, request_id, status, fail_code=None):
        if status not in STATUSES: raise BridgeError("finish_code_request refused: status")
        if status == "verified": fail_code = None
        elif fail_code not in FAIL_CODES: raise BridgeError("finish_code_request refused: fail code")
        self._rpc("finish_code_request", {"p_request_id": request_id, "p_status": status, "p_fail_code": fail_code})


# ---- reads (PostgREST GET on the existing service-role client; no code table is ever read) --------------------------------------------
def verification_row(portal, vid):
    if not isinstance(vid, str) or not UUID_RE.match(vid): return None
    rows = portal.call("GET", "%s?select=id,client_id,directory,state&id=eq.%s&limit=1" % (VERIFICATION_TABLE, vid))
    return rows[0] if isinstance(rows, list) and rows else None


def request_row(portal, rid, status=None):
    if not isinstance(rid, str) or not UUID_RE.match(rid): return None
    q = "%s?select=id,citation_verification_id,client_id,channel,status,requested_at,claimed_at,code_sent_at&id=eq.%s&limit=1" % (REQUEST_TABLE, rid)
    if status: q += "&status=eq.%s" % status
    rows = portal.call("GET", q)
    return rows[0] if isinstance(rows, list) and rows else None


# ---- the one decision ---------------------------------------------------------------------------------------------------------------
def fence(req, portal):
    """-> (verdict, verification_row_or_None). verdict: ok | bad_request | bad_client | channel | no_row | mismatch | no_playbook.
    Order matters: everything that needs no network runs first (the allow-list check), then ONE portal read of the verification row.
    Never touches a Directory."""
    if not isinstance(req, dict) or not req.get("id") or not req.get("citation_verification_id"): return "bad_request", None
    try:
        P.check_client(req.get("client_id"))
    except P.PortalWriteError:
        return "bad_client", None
    if req.get("channel") != "sms": return "channel", None
    try:
        row = verification_row(portal, req["citation_verification_id"])
    except Exception:
        return "no_row", None
    if not row: return "no_row", None
    if row.get("client_id") != req["client_id"]: return "mismatch", row
    if not directory_ok(row.get("directory")): return "no_playbook", row
    return "ok", row


FENCE_FAIL = {"bad_request": "other", "bad_client": "other", "channel": "other", "no_row": "other", "mismatch": "other", "no_playbook": "no_playbook"}


# ---- sweeper ------------------------------------------------------------------------------------------------------------------------
def _parse(ts):
    try:
        t = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None


def card_argv(request_id, status, age_s):
    import postcard_step as PS   # REVIEWER literal is assembled there (the repo leak check denylists it)
    if status in POST_SEND_FAIL:
        title = "VERIFY NOW: request %s stuck after the code was sent (%s, %dm)" % (request_id, status, int(age_s // 60))
        body = ("Request %s sat in %s for %d minutes after the text went out and the send run is gone. The bridge marked it failed/%s. "
                "Next step: check the agent box (send run log, Chrome, sleep or reboot) and tell the client. This card never carries a code."
                % (request_id, status, int(age_s // 60), POST_SEND_FAIL[status]))
    else:
        title = "VERIFY NOW: request %s could not start (%s, %dm)" % (request_id, status, int(age_s // 60))
        body = ("Request %s sat in %s for %d minutes with no code sent. The bridge marked it could_not_start/timeout. "
                "Next step: check the agent box (bridge pass, vault, Chrome) and tell the client. This card never carries a code." % (request_id, status, int(age_s // 60)))
    return [PS._hermes_exe(), "-p", PS.REVIEWER, "kanban", "--board", PS.REVIEWER, "create", title, "--assignee", PS.REVIEWER,
            "--workspace", "scratch", "--idempotency-key", "verify-now:%s" % request_id, "--body", body]


def file_card(request_id, status, age_s, runner=None):
    if os.environ.get("CE_NO_CARDS") == "1" and runner is None and _card_runner is None:
        log("card skipped (CE_NO_CARDS) for %s" % request_id); return False
    try:
        (runner or _card_runner or subprocess.run)(card_argv(request_id, status, age_s), capture_output=True, timeout=CARD_TIMEOUT_S, check=True)
        return True
    except Exception as e:
        log("card failed for %s: %s" % (request_id, type(e).__name__)); return False


def stale_requests(portal, now, after_s=SWEEP_AFTER_S):
    cutoff = (now - datetime.timedelta(seconds=after_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = portal.call("GET", "%s?select=id,status,requested_at&status=in.(requested,starting)&requested_at=lt.%s&order=requested_at.asc" % (REQUEST_TABLE, cutoff)) or []
    out = []
    for r in rows:   # re-check locally: the sweeper trusts its own clock, not the filter alone
        t = _parse(r.get("requested_at"))
        if r.get("status") in ("requested", "starting") and t and (now - t).total_seconds() >= after_s and r.get("id"):
            out.append((r["id"], r["status"], (now - t).total_seconds()))
    return out


def stale_post_send(portal, now, after_s=POST_SEND_SWEEP_S):
    """code_sent / checking rows whose send run is gone (crash, sleep, reboot). Same local re-check as stale_requests."""
    cutoff = (now - datetime.timedelta(seconds=after_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = portal.call("GET", "%s?select=id,status,code_sent_at&status=in.(code_sent,checking)&code_sent_at=lt.%s&order=code_sent_at.asc" % (REQUEST_TABLE, cutoff)) or []
    out = []
    for r in rows:
        t = _parse(r.get("code_sent_at"))
        if r.get("status") in POST_SEND_FAIL and t and (now - t).total_seconds() >= after_s and r.get("id"):
            out.append((r["id"], r["status"], (now - t).total_seconds()))
    return out


def sweep(portal, rpc, now=None, card_runner=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    done = []
    try:
        rows = [(rid, st, age, "could_not_start", "timeout", True) for rid, st, age in stale_requests(portal, now)]
    except Exception as e:
        log("sweep list failed: %s" % type(e).__name__); rows = []
    try:
        for rid, st, age in stale_post_send(portal, now):
            rows.append((rid, st, age, "failed", POST_SEND_FAIL[st], st == "checking"))
    except Exception as e:
        log("sweep post-send list failed: %s" % type(e).__name__)
    for rid, status, age, fstatus, fcode, card in rows:
        try:
            rpc.finish(rid, fstatus, fcode)
        except BridgeError as e:
            log("sweep finish failed for %s: %s" % (rid, e))   # the card still goes out below: a stuck row must reach a person
        if card: file_card(rid, status, age, runner=card_runner)
        log("swept %s from %s after %dm: %s/%s" % (rid, status, int(age // 60), fstatus, fcode))
        done.append(rid)
    return done


# ---- start --------------------------------------------------------------------------------------------------------------------------
def start_send(request_id, spawner=None):
    """Direct subprocess. argv holds the request id only (no client data, no code). Output goes to a run log under CE_LOGS."""
    import sitegate
    d = sitegate.logs_dir(); os.makedirs(d, exist_ok=True)
    out = open(os.path.join(d, "verify-send-%s.log" % request_id), "ab")
    argv = [sys.executable, os.path.join(HERE, "verify_send.py"), "--request-id", request_id]
    kw = dict(stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, close_fds=True)
    if os.name == "nt": kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    try:
        return (spawner or _spawner or subprocess.Popen)(argv, **kw)
    finally:
        out.close()


def run_pass(portal=None, rpc=None, now=None, spawner=None, card_runner=None):
    """-> {"swept": [ids], "started": [ids], "refused": [(id, verdict)]}. Sweeps first so a stuck row is never starved by new claims."""
    portal = portal or P.Portal(*P.load_portal_env())
    rpc = rpc or VerifyRpc(portal)
    res = {"swept": sweep(portal, rpc, now, card_runner), "started": [], "refused": []}
    for _ in range(MAX_CLAIMS_PER_PASS):
        try:
            req = rpc.claim()
        except BridgeError as e:
            log(str(e)); break
        if not req: break
        verdict, _row = fence(req, portal)
        rid = req.get("id")
        if verdict != "ok":
            log("refused %s: %s" % (rid, verdict))
            res["refused"].append((rid, verdict))
            try: rpc.finish(rid, "failed", FENCE_FAIL[verdict])
            except BridgeError as e: log(str(e))
            continue
        try:
            start_send(rid, spawner)
            res["started"].append(rid)
            log("started send run for %s" % rid)
        except Exception as e:
            log("could not start %s: %s" % (rid, type(e).__name__))
            try: rpc.finish(rid, "could_not_start", "other")
            except BridgeError as e2: log(str(e2))
    return res


def main(argv=None):
    try:
        r = run_pass()
    except Exception as e:
        print("VERIFY BRIDGE FAILED: " + type(e).__name__, file=sys.stderr, flush=True)
        return 1
    print("VERIFY BRIDGE OK swept=%d started=%d refused=%d" % (len(r["swept"]), len(r["started"]), len(r["refused"])), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
