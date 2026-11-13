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
The bridge itself never starts it; the send run (job/verify_send.py) does, for send=agent Directories. The bridge starts the send run:
  python job/verify_send.py --request-id <uuid>

Rules this module holds:
  * No send without a claimed request id for that exact row. fence() is the ONE decision (bridge and send run both call it) and a
    request whose client_id does not match the verification row is refused before the send run starts or any Directory is touched.
  * A code is never read here. Logs and cards carry request ids and allowlisted reason codes only, never exception text.
  * Only the two allow-listed portal clients (portal.check_client). Channels sms and phone-call, and only the Directories listed in config/verify_directories.json (send=agent default, send=script). `python job/verify_bridge.py --check` lists waiting rows whose Directory is missing from that file (read-only).
  * One send run per tenant at a time: a per-tenant OS file lock (the OS drops it when the run dies, however it dies) is taken by the
    send run before the browser opens. The bridge leaves a busy tenant's newly claimed request in 'starting' and retries it on the
    next pass (a started-marker file tells a deferred row from one whose run is already going). It stays inside the 10 min sweep.
  * Sweeper: requested/starting older than 10 minutes -> finish_code_request('could_not_start','timeout') and ONE Kanban card
    (idempotency key verify-now:<request_id>). Nothing stays in 'starting' forever.
"""
import contextlib, datetime, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import portal as P
import verify_scoreboard as SB

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
CHANNELS = ("sms", "phone-call")
DIRECTORIES_PATH = os.path.join(HERE, "..", "config", "verify_directories.json")   # the operating seat edits this file; CE_VERIFY_DIRECTORIES overrides (tests)
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


def norm_domain(directory):
    d = str(directory or "").lower().strip()
    d = re.sub(r"^https?://", "", d).split("/")[0]
    return d[4:] if d.startswith("www.") else d


def _load_file(path, source, agent_only=False):
    import json
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f).get("directories")
    except Exception:
        return []
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or not norm_domain(r.get("domain")): continue
        if r.get("send") not in ("script", "agent"): continue
        if agent_only and r.get("send") != "agent": continue   # a runtime-file entry can never name a script send (that needs a PR)
        out.append({"domain": norm_domain(r["domain"]), "aliases": [norm_domain(a) for a in r.get("aliases") or []],
                    "channels": [c for c in r.get("channels") or [] if c in CHANNELS], "send": r["send"],
                    "signin_url": r.get("signin_url") or "https://%s/" % norm_domain(r["domain"]),
                    "vault_items": dict(r.get("vault_items") or {}), "source": source})
    return out


def local_directories_path():
    import verify_allowlist as A
    return A.local_path()


def load_directories(path=None):
    """-> list of entries {domain, aliases, channels, send, signin_url, vault_items, source}. A missing or broken file is an empty list (fail closed).
    No path: the repo file MERGED with the runtime file outside the repo (t_f31e2490); the repo file wins on any domain/alias overlap.
    An explicit path reads that file only."""
    if path: return _load_file(path, "repo")
    out = _load_file(os.environ.get("CE_VERIFY_DIRECTORIES") or DIRECTORIES_PATH, "repo")
    taken = set(x for e in out for x in [e["domain"]] + e["aliases"])
    lp = local_directories_path()
    for e in _load_file(lp, "local", agent_only=True) if lp else []:
        names = [e["domain"]] + e["aliases"]
        base = next((o for o in out if o["source"] == "repo" and set(names) & set([o["domain"]] + o["aliases"])), None)
        if base is not None:   # a runtime row for a repo Directory only SUPPLEMENTS it: missing channels / tenant vault items. Repo values win; send is the repo's; a repo script entry is never extended.
            if base["send"] == "agent":
                base["channels"] = base["channels"] + [c for c in e["channels"] if c not in base["channels"]]
                for t, v in e["vault_items"].items(): base["vault_items"].setdefault(t, v)
                base["supplemented"] = True
            continue
        if taken.intersection(names): continue
        taken.update(names); out.append(e)
    return out


def directory_entry(directory, channel=None, path=None):
    """The file entry for this Directory (domain or alias) that lists the channel, else None."""
    d = norm_domain(directory)
    for e in load_directories(path):
        if d in [e["domain"]] + e["aliases"] and (channel is None or channel in e["channels"]): return e
    return None


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
        SB.finalize(request_id, status if status == "verified" else "%s:%s" % (status, fail_code))   # the one scoreboard row; never raises


# ---- reads (PostgREST GET on the existing service-role client; no code table is ever read) --------------------------------------------
def lock_dir():
    import sitegate
    d = os.environ.get("CE_VERIFY_LOCKS") or os.path.join(sitegate.logs_dir(), "verify-locks")
    os.makedirs(d, exist_ok=True)
    return d


@contextlib.contextmanager
def tenant_lock(client_id):
    """One send run per tenant. Non-blocking. Yields True when this caller holds the lock, False when another run does. The OS drops
    the lock when the holder exits or crashes, so there is no stale lock file to clean up."""
    cid = str(client_id or "")
    if not UUID_RE.match(cid): raise BridgeError("tenant lock: bad client id")
    fh = open(os.path.join(lock_dir(), "tenant-%s.lock" % cid), "a+b")
    got = False
    try:
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0); msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            got = True
        except OSError:
            got = False
        yield got
    finally:
        if got:
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0); msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        fh.close()


def tenant_busy(client_id):
    with tenant_lock(client_id) as got:
        return not got


def _marker(rid): return os.path.join(lock_dir(), "started-%s" % rid)


def mark_started(rid):
    with open(_marker(rid), "wb"): pass


def was_started(rid): return os.path.exists(_marker(rid))


def clear_started(rid):
    try: os.remove(_marker(rid))
    except OSError: pass


def prune_markers(max_age_s=86400):
    d = lock_dir()
    for n in os.listdir(d):
        if n.startswith("started-"):
            try:
                if time.time() - os.path.getmtime(os.path.join(d, n)) > max_age_s: os.remove(os.path.join(d, n))
            except OSError: pass


def verification_row(portal, vid):
    if not isinstance(vid, str) or not UUID_RE.match(vid): return None
    rows = portal.call("GET", "%s?select=id,client_id,directory,state,verification_type,steps,directory_url&id=eq.%s&limit=1" % (VERIFICATION_TABLE, vid))
    return rows[0] if isinstance(rows, list) and rows else None


def request_row(portal, rid, status=None):
    if not isinstance(rid, str) or not UUID_RE.match(rid): return None
    q = "%s?select=id,citation_verification_id,client_id,channel,status,requested_at,claimed_at,code_sent_at&id=eq.%s&limit=1" % (REQUEST_TABLE, rid)
    if status: q += "&status=eq.%s" % status
    rows = portal.call("GET", q)
    return rows[0] if isinstance(rows, list) and rows else None


def starting_requests(portal):
    q = "%s?select=id,citation_verification_id,client_id,channel,status,requested_at,claimed_at,code_sent_at&status=eq.starting&order=claimed_at.asc&limit=20" % REQUEST_TABLE
    rows = portal.call("GET", q) or []
    return [r for r in rows if isinstance(r, dict) and r.get("status") == "starting"]


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
    if req.get("channel") not in CHANNELS: return "channel", None
    try:
        row = verification_row(portal, req["citation_verification_id"])
    except Exception:
        return "no_row", None
    if not row: return "no_row", None
    if row.get("client_id") != req["client_id"]: return "mismatch", row
    if not directory_entry(row.get("directory"), req.get("channel")): return "no_playbook", row
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


def _stamp_pickup(req, row):
    """Scoreboard: the click (requested_at) and the bridge pickup (portal claimed_at, else now). First write wins, so a deferred retry keeps the first pickup."""
    rid = req.get("id")
    t_req = _parse(req.get("requested_at"))
    if t_req is not None: SB.stamp(rid, "requested_at", t_req)   # no portal value = no stamp (never fake the click with the pickup time)
    SB.stamp(rid, "bridge_pickup_at", _parse(req.get("claimed_at")) or SB.now())
    ent = directory_entry((row or {}).get("directory"), req.get("channel")) or {}
    SB.stamp(rid, None, tenant=next((k for k, v in P.ALLOWED.items() if v == req.get("client_id")), None), domain=ent.get("domain"),
             channel=req.get("channel"), send_mode=ent.get("send"))


def dispatch(req, portal, rpc, res, busy, spawner=None):
    """Fence one claimed request, then start its send run unless its tenant is busy. A busy tenant's request stays in 'starting'
    (no finish, no card) and is retried by the next pass; the sweeper still ends it at 10 minutes."""
    verdict, _row = fence(req, portal)
    rid = req.get("id")
    if verdict != "ok":
        log("refused %s: %s" % (rid, verdict))
        res["refused"].append((rid, verdict))
        try: rpc.finish(rid, "failed", FENCE_FAIL[verdict])
        except BridgeError as e: log(str(e))
        return
    cid = req["client_id"]
    _stamp_pickup(req, _row)
    if cid in busy or tenant_busy(cid):
        log("tenant busy; %s stays starting, retry next pass" % rid)
        if rid not in res["deferred"]: res["deferred"].append(rid)
        return
    try:
        mark_started(rid)
        start_send(rid, spawner)
        busy.add(cid)
        res["started"].append(rid)
        log("started send run for %s" % rid)
    except Exception as e:
        clear_started(rid)
        log("could not start %s: %s" % (rid, type(e).__name__))
        try: rpc.finish(rid, "could_not_start", "other")
        except BridgeError as e2: log(str(e2))


def run_pass(portal=None, rpc=None, now=None, spawner=None, card_runner=None):
    """-> {"swept": [ids], "started": [ids], "refused": [(id, verdict)], "deferred": [ids]}. Sweeps first so a stuck row is never
    starved by new claims. Then retries deferred rows (starting, no run started yet), then claims new ones."""
    portal = portal or P.Portal(*P.load_portal_env())
    rpc = rpc or VerifyRpc(portal)
    res = {"swept": sweep(portal, rpc, now, card_runner), "started": [], "refused": [], "deferred": [], "first_use": []}
    try: res["first_use"] = file_first_use_cards(portal, card_runner)   # never blocks claim or dispatch
    except Exception as e: log("first-use cards failed: %s" % type(e).__name__)
    busy = set()   # tenants this pass already started a run for (the new run may not hold its lock yet)
    try: prune_markers()
    except Exception as e: log("marker prune failed: %s" % type(e).__name__)
    try:
        waiting = [r for r in starting_requests(portal) if r.get("id") and UUID_RE.match(str(r["id"])) and not was_started(r["id"])]
    except Exception as e:
        log("deferred list failed: %s" % type(e).__name__); waiting = []
    for req in waiting:
        dispatch(req, portal, rpc, res, busy, spawner)
    for _ in range(MAX_CLAIMS_PER_PASS):
        try:
            req = rpc.claim()
        except BridgeError as e:
            log(str(e)); break
        if not req: break
        dispatch(req, portal, rpc, res, busy, spawner)
    return res


def first_use_rows(portal):
    """Read-only. The sms/phone-call rows waiting for verification (allow-listed clients only). One GET, no write."""
    rows = portal.call("GET", "%s?select=id,client_id,directory,verification_type,state&verification_type=in.(sms,phone-call)&state=eq.requires_verification&order=directory.asc" % VERIFICATION_TABLE) or []
    ok_ids = set(P.ALLOWED.values())
    return [r for r in rows if isinstance(r, dict) and r.get("client_id") in ok_ids and r.get("state", "requires_verification") == "requires_verification"
            and r.get("verification_type") in CHANNELS and UUID_RE.match(str(r.get("id") or ""))]


def first_use_argv(row):
    import postcard_step as PS
    tenant = {v: k for k, v in P.ALLOWED.items()}.get(row.get("client_id"), "unknown")
    directory = str(row.get("directory") or "")[:120]
    listed = "yes" if directory_entry(directory, row.get("verification_type")) else "no"
    title = "Verify Now: first-use row %s (%s)" % (directory, tenant)
    body = ("A client row is waiting for verification and no request exists yet. Directory: %s. Tenant: %s. Type: %s. "
            "In config/verify_directories.json for this type: %s. This card carries no code, no client email, no phone number." % (directory, tenant, row.get("verification_type"), listed))
    return [PS._hermes_exe(), "-p", PS.REVIEWER, "kanban", "--board", PS.REVIEWER, "create", title, "--assignee", PS.REVIEWER,
            "--workspace", "scratch", "--idempotency-key", "verify-now-row:%s" % row["id"], "--body", body]


def _seen_marker(rid): return os.path.join(lock_dir(), "first-use-%s" % rid)


def file_first_use_cards(portal, card_runner=None):
    """-> [row ids a card was filed for this pass]. A row id is filed once: the marker is written only after the card call worked, so a
    failed filing retries next pass; the board's idempotency key stops a duplicate if the marker is ever lost."""
    done = []
    try:
        rows = first_use_rows(portal)
    except Exception as e:
        log("first-use list failed: %s" % type(e).__name__); return done
    for r in rows:
        rid = r["id"]
        if os.path.exists(_seen_marker(rid)): continue
        if os.environ.get("CE_NO_CARDS") == "1" and card_runner is None and _card_runner is None:
            log("first-use card skipped (CE_NO_CARDS) for %s" % rid); continue
        try:
            (card_runner or _card_runner or subprocess.run)(first_use_argv(r), capture_output=True, timeout=CARD_TIMEOUT_S, check=True)
        except Exception as e:
            log("first-use card failed for %s: %s" % (rid, type(e).__name__)); continue
        with open(_seen_marker(rid), "wb"): pass
        log("first-use card filed for %s" % rid)
        done.append(rid)
    return done


def check_missing(portal, path=None):
    """Read-only. -> (rows, missing): the portal sms/phone-call rows still waiting for verification (allow-listed clients only) and those
    whose Directory is not in the file for that channel. One GET, no write."""
    rows = portal.call("GET", "%s?select=client_id,directory,verification_type,state&verification_type=in.(sms,phone-call)&state=eq.requires_verification&order=directory.asc" % VERIFICATION_TABLE) or []
    ok_ids = set(P.ALLOWED.values())
    rows = [r for r in rows if isinstance(r, dict) and r.get("client_id") in ok_ids]
    return rows, [r for r in rows if not directory_entry(r.get("directory"), r.get("verification_type"), path)]


def run_check(portal=None, out=print):
    portal = portal or P.Portal(*P.load_portal_env())
    rows, missing = check_missing(portal)
    names = {v: k for k, v in P.ALLOWED.items()}
    out("VERIFY DIRECTORIES CHECK: %d sms/phone-call rows waiting, %d missing from the repo + local allowlist" % (len(rows), len(missing)))
    for r in missing:
        out("  missing: %s | %s | %s" % (names.get(r.get("client_id")), r.get("directory"), r.get("verification_type")))
    lp = local_directories_path()
    for src, p in (("repo", os.environ.get("CE_VERIFY_DIRECTORIES") or DIRECTORIES_PATH), ("local", lp)):
        out("  source %s: %s (%d entries)" % (src, os.path.abspath(p) if p else "none", len([e for e in load_directories() if e["source"] == src])))
    sup = [e["domain"] for e in load_directories() if e.get("supplemented")]
    out("  supplements (local rows adding a channel or tenant item to a repo Directory): %s" % (", ".join(sup) if sup else "none"))
    return 0


def main(argv=None):
    if "--check" in (argv if argv is not None else sys.argv[1:]):
        try: return run_check()
        except Exception as e:
            print("VERIFY DIRECTORIES CHECK FAILED: " + type(e).__name__, file=sys.stderr, flush=True); return 1
    try:
        r = run_pass()
    except Exception as e:
        print("VERIFY BRIDGE FAILED: " + type(e).__name__, file=sys.stderr, flush=True)
        return 1
    print("VERIFY BRIDGE OK swept=%d started=%d refused=%d deferred=%d first_use=%d" % (len(r["swept"]), len(r["started"]), len(r["refused"]), len(r["deferred"]), len(r["first_use"])), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
