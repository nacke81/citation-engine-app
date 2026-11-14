"""Citation state transitions: one call records a state change in the tenant's queue file (TENANTS: SCC, NM), the SCC Local SEO portal snapshot, and (gated) Activities.
NM (t_cb7bad04): queue + Your turn verification row + Verify Now allowlist + Directory DB; no portal snapshot, no client Activities. `--create-row` adds an NM queue row.

record_transition(client, row_id, new_state, evidence_url, note) accepts only:
  queued -> found, queued|found|needs-human|submitted -> created-unlisted (internal; live|needs-human|rejected from it), queued|found|needs-human -> submitted|pending-verify, found|submitted|pending-verify|needs-human -> live,
  any -> rejected, any -> needs-human. found (SCC already listed, claim not done) is internal: no client activity.
  found -> found and needs-human -> needs-human are accepted only with a note (note refresh on a parked row).
Everything else is refused before anything is written. mike_approval is never read for writing and never changed.

Sinks (all injectable so tests and the dry run make no network call):
  queue     the SCC queue JSON (atomic replace; state, evidence_url, dated history entry)
  portal    footprint_snapshot via portal.Portal (same-day snapshot, one directory row overlaid; counts unchanged)
  activities  one client-voiced deliverables row for submitted, pending-verify, live and rejected (never needs-human: an internal blocker
            is not client news). ON by default (Mike, 2026-10-21). These four templated, factual receipts are written with approved_at = now:
            Mike ruled 2026-10-14 (vault Intelligence/decisions/2026-10-14-nate-approves-routine-client-activity-lines.md) that routine
            factual lines need no Mike approval; pricing, a promise or a new claim stays held. Hold path: CE_ACTIVITIES_HOLD=1 (or
            activities_hold_flag=True) writes approved_at null so the portal hides the row until staff approve it (migration 20261020000002).
            Opt out of writing entirely with CE_ACTIVITIES_WRITE=0 (tests, dry runs).
  verification  needs-human with verify_type phone-call|sms|postcard upserts one citation_verification row (idempotent per client+directory)
            for the client's Your Turn page and the batch trigger. A later live transition marks that row live with verified_at.
            Email verifications never use this path.
"""
import copy, datetime, json, os, re, sys, tempfile, time
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buildqueue as Q
import portal as P
import directories as D
import walls as W
import your_turn_gate as YT
import verify_allowlist as AL


def _resolve_vault_item(directory, items=None, tenant="SCC"):
    """t_f31e2490: the build run's own resolver (vault_item.resolve_for_domain). -> item name or None. Never a naming-convention guess."""
    try:
        import vault_item as V
        return V.resolve_for_domain(directory, items=items, tenant=tenant)[1] or None
    except Exception:
        return None


# t_cb7bad04: the tenant is read from here, never from a hardcoded client guard. A new client is one entry (and a P.ALLOWED id), not code.
#   slug      portal tenant slug (shown in the dry run; the write itself is keyed by the P.ALLOWED client id)
#   queue_name/queue_default  the tenant's queue file; row_prefix  its row ids (None: SCC ids carry no prefix, and must not carry another tenant's)
#   snapshot  the queue overlays a portal footprint_snapshot (SCC only: the NM queue has no portal snapshot)
#   activities  client-voiced deliverables rows on submitted/pending-verify/live/rejected (SCC only)
#   create_row  `--create-row` adds queue rows (NM; SCC rows come from job/buildrows.py)
NM_QUEUE_NAME = "nm-fix-queue.json"
TENANTS = {
    "SCC": {"slug": "scc", "queue_name": None, "queue_default": lambda: Q.QUEUE_PATH, "row_prefix": None, "snapshot": True, "activities": True, "create_row": False},
    "NM": {"slug": "na" + "cke-media", "queue_name": NM_QUEUE_NAME,
           "queue_default": lambda: os.environ.get("CE_NM_QUEUE") or os.path.expandvars("%LOCALAPPDATA%/citation-engine/queue/" + NM_QUEUE_NAME),
           "row_prefix": "nm-", "snapshot": False, "activities": False, "create_row": True},
}


def tenant_of(client):
    t = TENANTS.get(client)
    if not t: raise TransitionRefused("no tenant config for client %r (known: %s)" % (client, ", ".join(sorted(TENANTS))))
    return t


def check_tenant_lock(client, row_id, path):
    """Tenant lock, before any read or write: a park for one tenant can never touch another tenant's row or queue file."""
    t = tenant_of(client)
    pre = t["row_prefix"]
    if pre and not str(row_id).startswith(pre):
        raise TransitionRefused("tenant lock: %s rows start %r, got %r" % (client, pre, row_id))
    if not pre:
        for other, ot in TENANTS.items():
            if other != client and ot["row_prefix"] and str(row_id).startswith(ot["row_prefix"]):
                raise TransitionRefused("tenant lock: %r is a %s row, not %s" % (row_id, other, client))
    if t["queue_name"] and os.path.basename(path) != t["queue_name"]:
        raise TransitionRefused("tenant lock: %s writes only %s, got %s" % (client, t["queue_name"], os.path.basename(path)))
    return t


def _tenant_lock(client, row_id, path):   # one indirection: the mutation test swaps this to prove the lock tests can fail
    return check_tenant_lock(client, row_id, path)


STATES = ("queued", "found", "claimed-unverified", "created-unlisted") + Q.PORTAL_STATES  # queued, found, claimed-unverified, created-unlisted, submitted, pending-verify, needs-human, live, rejected
ALLOWED_FROM = {
    "found": {"queued"},  # internal: SCC already listed, claim not done; no client activity
    "claimed-unverified": {"queued", "found", "needs-human"},  # internal: listed + claimed, but edits are ID-gated (dnb, t_d13bd638); no client activity
    "created-unlisted": {"queued", "found", "needs-human", "submitted"},   # t_3f38d45e: submitted -> created-unlisted (smartcustomer: a page with name and website only)  # internal: the listing EXISTS on the Directory but is not public yet, or is public without full NAP (t_f707b644); In flight, no client activity
    "submitted": {"queued", "found", "needs-human"},
    "pending-verify": {"submitted", "found", "needs-human"},
    "live": {"found", "claimed-unverified", "created-unlisted", "submitted", "pending-verify", "needs-human"},  # needs-human: a row parked for phone/sms/postcard verification goes live once verified
}
ANY_FROM = {"rejected", "needs-human"}
ACTIVITY_SOURCE = "citation_engine"
FLAG = "CE_ACTIVITIES_WRITE"
HOLD_FLAG = "CE_ACTIVITIES_HOLD"
ACTIVITY_CHANNEL_LABEL = "SEO & Local SEO"  # t_ef2b05e9: directory listings are Local SEO; shared contract with portal card t_9bc7d948
ACTIVITY_STATES = ("submitted", "pending-verify", "live", "rejected")  # needs-human is internal, never client news
VERIFY_TYPES = ("phone-call", "sms", "postcard", "id-check", "client-email")
# client-email (t_d2f75685, Nate 2026-10-27): the Directory wants the owner to attest the email "belongs directly to the business and is not a proxy or
# agency-controlled address" (showmelocal ACTIVATE). listings@ is ours, so we NEVER attest it. The client's own address is needed: a client gate in the portal.
CLIENT_EMAIL_NOTE = "parked for client verification (client-email): needs the client's own email address; we never attest listings@ as the business's own address"
POSTCARD_DEADLINE_DAYS = 30
VERIFY_UPSERT_PATH = "citation_verification?on_conflict=client_id,directory"


class TransitionRefused(Exception):
    pass


PROOF_FIELDS = ("proof_url", "proof_nap", "proof_at", "proof_nap_match", "build_action")
BUILD_ACTIONS = ("new", "claim", "fix")


def proof_problems(proof):
    """Pure. [] when `proof` is a complete Proof (t_d660babc): http(s) proof_url, non-empty proof_nap, proof_at, proof_nap_match True, build_action new|claim|fix."""
    if not isinstance(proof, dict): return ["no proof"]
    bad = []
    u = str(proof.get("proof_url") or "")
    if not u.startswith(("http://", "https://")) or "@" in urlsplit(u).netloc: bad.append("proof_url")
    if not str(proof.get("proof_nap") or "").strip(): bad.append("proof_nap")
    if not str(proof.get("proof_at") or "").strip(): bad.append("proof_at")
    if proof.get("proof_nap_match") is not True: bad.append("proof_nap_match")
    if proof.get("build_action") not in BUILD_ACTIONS: bad.append("build_action")
    return bad


def check_proof(proof):
    bad = proof_problems(proof)
    if bad: raise TransitionRefused("live needs complete Proof; missing or invalid: %s" % ", ".join(bad))
    return {k: proof[k] for k in PROOF_FIELDS}


def db_proof_by_directory(db=None):
    """Read-only GET of the Proof columns in ce_directory_status for SCC: {directory: {5 proof fields}}. None when the sink is off (CE_DIRECTORIES_WRITE=0)."""
    db = db or (D.DirDB() if D.enabled() else None)
    if db is None: return None
    rows = db.call("GET", "ce_directory_status?biz=eq.SCC&owner=eq.%s&select=directory,%s" % (D._owner(db), ",".join(PROOF_FIELDS)), None, "return=representation") or []
    return {r["directory"]: {k: r.get(k) for k in PROOF_FIELDS} for r in rows if r.get("directory")}


def live_rows_missing_proof(q, db_proof=None):
    """Guard (t_d660babc): [(row id, [bad fields])] for every live queue row without a complete Proof.
    The ce_directory_status Proof columns are the source of truth (`db_proof` = db_proof_by_directory()): a live row whose status row has
    complete Proof is fine even if the queue row has no `proof` key (every live row written before this guard). With db_proof=None (sink off)
    only the queue row's own `proof` is checked."""
    out = []
    for _key, _kind, rows in _row_lists(q):
        for r in rows:
            if r.get("state") == "live":
                bad = proof_problems(r.get("proof"))
                if bad and db_proof is not None:
                    d = db_proof.get(r.get("directory"))
                    if d is not None:
                        bad = proof_problems(d)
                if bad: out.append((r.get("id"), bad))
    return out


NOTE_ONLY_STATES = ("found", "claimed-unverified", "created-unlisted", "needs-human", "submitted", "pending-verify")  # a same-state move is a note refresh on a waiting row (the weekly recheck names a wrong field); needs a note


REASON_MIN = 10
BACKOFF_MARKERS = ("no-permalink",)   # t_8d1865a3: a structured history field (not prose) so a cap can count them
PARK_REASONS = ("no-public-permalink",)
MAX_NO_URL_BACKOFFS = 3


def no_url_backoffs(row):
    """How many no-URL backoffs the row's history records (entries with backoff == 'no-permalink'). A prose note is not a counter (lesson 2026-10-27)."""
    return sum(1 for h in (row.get("history") or []) if isinstance(h, dict) and h.get("backoff") == "no-permalink")


def check_transition(old, new, note=None, reason=None, refresh_url=False):
    if refresh_url:   # t_962161f4: a LIVE row whose Directory URL moved (redirect to a new slug): same state, new URL, a note
        if old != "live" or new != "live" or not (note or "").strip():
            raise TransitionRefused("--refresh-url is live -> live only and needs a note")
        return
    if new == "queued":   # t_d2f75685: the ONE way back. A rejected listing may be re-created, with a written reason; never a silent reset.
        if old != "rejected":
            raise TransitionRefused("only a rejected row can go back to queued (row is %s)" % (old,))
        if len((reason or "").strip()) < REASON_MIN:
            raise TransitionRefused("rejected -> queued needs --reason (at least %d characters: why a re-create can succeed this time)" % REASON_MIN)
        return
    if reason:
        raise TransitionRefused("--reason only applies to rejected -> queued")
    if new not in STATES:
        raise TransitionRefused("unknown or unsupported target state %r" % (new,))
    if old not in STATES:
        raise TransitionRefused("row has unknown current state %r" % (old,))
    if old == new and new in NOTE_ONLY_STATES and note:
        return
    if new in ANY_FROM:
        if old == new:
            raise TransitionRefused("row is already %s" % new)
        return
    if old not in ALLOWED_FROM[new]:
        raise TransitionRefused("transition %s -> %s is not allowed" % (old, new))


def check_evidence(url, new):
    if url in (None, ""):
        if new == "live":
            raise TransitionRefused("live needs an evidence url")
        return None
    s = urlsplit(url)
    if s.scheme not in ("http", "https") or not s.netloc or "@" in s.netloc:
        raise TransitionRefused("evidence url must be plain http(s) with no credentials")
    return url


def activity_title(new, directory):
    """Client-voiced, no terminal period, domain only (no NAP)."""
    t = {
        "submitted": "Submitted your business listing to %s",
        "pending-verify": "Your %s listing is awaiting verification",
        "live": "Your %s listing is live",
        "rejected": "%s declined the listing",
    }[new]
    if new == "rejected":   # t_ac6e82a6: factual receipt, no promise; "Fixr.com declined the listing"
        directory = directory[:1].upper() + directory[1:]
    return t % directory


def activities_enabled(explicit=None):
    """Default ON. CE_ACTIVITIES_WRITE=0 (or activities_flag=False) turns it off."""
    return bool(explicit) if explicit is not None else os.environ.get(FLAG) != "0"


def activities_hold(explicit=None):
    """Default OFF. CE_ACTIVITIES_HOLD=1 (or activities_hold_flag=True) writes approved_at null: the row waits in the portal's staff hold."""
    return bool(explicit) if explicit is not None else os.environ.get(HOLD_FLAG) == "1"


def verification_note(verify_type):
    if verify_type == "client-email": return CLIENT_EMAIL_NOTE
    return "parked for client verification (%s)" % verify_type


def check_verify_type(verify_type, new):
    if verify_type in (None, ""):
        return None
    if verify_type not in VERIFY_TYPES:
        raise TransitionRefused("verify type must be one of %s, got %r (a mailbox-link email verification never uses this path; client-email is the client's own address)" % ("/".join(VERIFY_TYPES), verify_type))
    if new != "needs-human":
        raise TransitionRefused("verify type only applies to a needs-human transition")
    return verify_type


ID_CHECK_BAD = re.compile(r"\b(password|passcode)\b", re.I)


def check_id_check_fields(verify_type, steps, directory_url):
    """Mirror the portal DB checks so a bad id-check row is refused here, not by a failed write. steps/directory_url apply to id-check only."""
    if verify_type != "id-check":
        if steps or directory_url: raise TransitionRefused("steps and directory_url only apply to an id-check verification")
        return None, None
    steps = [str(x).strip() for x in (steps or []) if str(x).strip()]
    if not steps: raise TransitionRefused("id-check needs at least one plain-language step for the client")
    if len(steps) > 12 or len("\n".join(steps)) > 3000: raise TransitionRefused("id-check steps: 12 steps and 3000 characters at most")
    if ID_CHECK_BAD.search("\n".join(steps)): raise TransitionRefused("id-check steps must not mention a password or passcode (the client sees them)")
    if directory_url and not re.match(r"^https://\S+$", directory_url): raise TransitionRefused("directory_url must be an https URL with no spaces")
    return steps, (directory_url or None)


def build_verification_record(client_id, directory, verify_type, day, deadline_days=POSTCARD_DEADLINE_DAYS, steps=None, directory_url=None):
    """One citation_verification row. parked_at is left to the table default and never resent, so a re-park does not restart the 14-day clock."""
    r = {"client_id": client_id, "directory": directory, "verification_type": verify_type, "state": "requires_verification"}
    if verify_type == "postcard":
        r["deadline"] = (datetime.date.fromisoformat(day) + datetime.timedelta(days=deadline_days)).isoformat()
    if verify_type == "id-check":
        # Plain instructions the client sees. Never a credential: the portal DB also refuses password/passcode text.
        if steps: r["steps"] = list(steps)
        if directory_url: r["directory_url"] = directory_url
    return r


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _replace_retry(src, dst, tries=12, delay=0.05):
    """os.replace with a short backoff on PermissionError. Windows (Defender, indexers, a lingering handle) can briefly lock the file; POSIX never raises here, so behavior is unchanged there."""
    for i in range(tries):
        try:
            os.replace(src, dst); return
        except PermissionError:
            if i == tries - 1: raise
            time.sleep(delay * (i + 1))


def _write_atomic(path, data):
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        _replace_retry(tmp, path)
    except Exception:
        if os.path.exists(tmp): os.unlink(tmp)
        raise


def set_nap_check(row_id, nap_check, queue_path=None):
    """t_f6267312: store the latest NAP read of a LIVE row's listing page on the queue row (`nap_check`). No state change, no history entry, no portal write:
    the snapshot overlay reads it. Refuses a row that is not live."""
    path = queue_path or Q.QUEUE_PATH
    q = _read(path)
    row = _find(q, row_id)
    if row.get("state") != "live": raise TransitionRefused("nap_check is only stored on a live row, %s is %s" % (row_id, row.get("state")))
    row["nap_check"] = nap_check
    _write_atomic(path, q)
    return row


def record_proof(row_id, proof, *, queue_path=None, today=None, db=None):
    """Proof for a row ALREADY live (backfill, --proof-live). Same validation as the live move; state unchanged; queue row + ce_directory_status. Refuses a non-live row."""
    path = queue_path or Q.QUEUE_PATH
    day = today or datetime.date.today().isoformat()
    proof = check_proof(proof)
    q = _read(path)
    row = _find(q, row_id)
    if row.get("state") != "live": raise TransitionRefused("record_proof is for a live row, %s is %s" % (row_id, row.get("state")))
    db = db or (D.DirDB() if D.enabled() else None)
    if db is not None:   # status first: a failed write leaves the queue unchanged and the audit still lists the row
        D._upsert_status(db, [D._status_row(db, "SCC", row["directory"], day, **proof)])
    row["proof"] = dict(proof)
    mirror_proof_quiet(q, db)   # t_78dc54b5: other live rows with a complete DB Proof but no queue proof
    _write_atomic(path, q)
    return {"row_id": row_id, "proof": proof, "queue_written": path, "directories_written": db is not None}


def mirror_proof(q, db_proof):
    """t_78dc54b5: copy the 5 PROOF_FIELDS from the DB (`db_proof` = db_proof_by_directory()) into every live row whose own `proof` is missing or incomplete,
    when the DB copy is complete. A complete queue proof is never touched; a row with no or an incomplete DB copy is left alone. db_proof None (sink off) = no-op.
    Mutates q; returns the ids of the rows filled."""
    out = []
    if db_proof is None: return out
    for _key, _kind, rows in _row_lists(q):
        for r in rows:
            if r.get("state") != "live" or not proof_problems(r.get("proof")): continue
            d = db_proof.get(r.get("directory"))
            if d is not None and not proof_problems(d):
                r["proof"] = {k: d[k] for k in PROOF_FIELDS}
                out.append(r.get("id"))
    return out


def mirror_proof_quiet(q, db=None):
    """Writer hook: mirror_proof with a lazy read-only GET (only when a live row needs it). Never raises: a DB failure is printed and the queue write goes on."""
    try:
        if not any(r.get("state") == "live" and proof_problems(r.get("proof")) for _k, _kd, rows in _row_lists(q) for r in rows): return []
        return mirror_proof(q, db_proof_by_directory(db))
    except Exception as e:
        print("MIRROR-PROOF skipped: " + (str(e)[:200] or type(e).__name__), file=sys.stderr, flush=True)
        return []


def _md5(path):
    import hashlib
    with open(path, "rb") as f: return hashlib.md5(f.read()).hexdigest()


def mirror_proof_file(path, write=False, today=None, db_proof="fetch"):
    """One-shot (--mirror-proof): dry run lists the rows that would be filled; write=True backs the file up, writes atomically, and returns md5 before/after.
    Sink off (db_proof None) = skipped, nothing written. No state change, no DB write."""
    if isinstance(db_proof, str): db_proof = db_proof_by_directory()
    if db_proof is None: return {"skipped": "directories sink is off (CE_DIRECTORIES_WRITE=0)", "filled": [], "written": False}
    q = _read(path)
    before = _md5(path)
    filled = mirror_proof(q, db_proof)
    res = {"filled": filled, "written": False, "md5_before": before, "md5_after": before}
    if write and filled:
        import shutil
        day = (today or datetime.date.today().isoformat()).replace("-", "")
        bak = "%s.bak-%s-mirror-proof" % (path, day)
        if not os.path.exists(bak): shutil.copy2(path, bak)
        _write_atomic(path, q)
        res.update(written=True, backup=bak, md5_after=_md5(path))
    return res


def _row_lists(q):
    """(key, kind, list) for every list that holds queue rows. The weekly create discovery writes create rows under
    create_queue.rows (a dict); create_rows is the older flat list. Lists are returned live so callers can replace rows in place."""
    out = [("fix_queue", "fix", q.get("fix_queue") or []), ("create_rows", "create", q.get("create_rows") or [])]
    cq = q.get("create_queue")
    if isinstance(cq, dict):
        out.append(("create_queue", "create", cq.get("rows") or []))
    elif isinstance(cq, list):
        out.append(("create_queue", "create", cq))
    return out


def _find(q, row_id):
    for _key, _kind, rows in _row_lists(q):
        for r in rows:
            if r.get("id") == row_id:
                return r
    raise TransitionRefused("no queue row with id %r" % (row_id,))


def _kind_of(q, row_id):
    for _key, kind, rows in _row_lists(q):
        if any(r.get("id") == row_id for r in rows):
            return kind
    return "fix"


def portal_payload_for(base, row, day):
    """Overlay ONE row's state on a snapshot payload (counts unchanged). base None (dry run) gives just the row patch."""
    if base is None:
        base = {"directories": []}
    return Q.overlay_directories(base, [row], day)


def full_portal_payload(base, q, new_row, day):
    """Snapshot overlay from ALL live / pending-verify / submitted queue rows (each at its own last history date), then the moved row.
    A single transition therefore never drops another row's state from the snapshot (t_bb08988c needed an ad hoc rewrite for this)."""
    if base is None:
        base = {"directories": []}
    payload = base
    for _key, _kind, rows in _row_lists(q):
        for r in rows:
            if r.get("id") == new_row.get("id") or r.get("state") not in Q.LISTING_STATES:
                continue
            hist = r.get("history") or []
            at = (hist[-1].get("at") if hist and isinstance(hist[-1], dict) else None) or day
            payload = Q.overlay_directories(payload, [r], at)
    return Q.overlay_directories(payload, [new_row], day)


def build_activity_record(client_id, row, new, evidence_url, day, hold=None, now=None):
    approved = None if activities_hold(hold) else (now or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return {"approved_at": approved, "client_id": client_id, "deliverable_type": "citation", "title": activity_title(new, row["directory"]),
            "date_completed": day, "in_scope": True, "units": 1, "evidence_url": evidence_url,
            "source": ACTIVITY_SOURCE, "source_ref": "citation-transition:%s:%s" % (row["id"], new),
            "channel_label": ACTIVITY_CHANNEL_LABEL}


def set_verification_live(portal, verification_id, client_id, now=None):
    """t_0d601426 (Verify Now): the ONE writer of citation_verification state=live for a client-typed phone code that the Directory accepted.
    Same PATCH as the verification-queue step of record_transition (state, verified_at, updated_at), but guarded: only the row with this id AND
    this client_id AND state requires_verification. -> True when exactly one row changed. The QUEUE row's own move to live still needs public-page
    Proof and goes through record_transition; this does not touch the queue file."""
    P.check_client(client_id)
    t = (now or datetime.datetime.now(datetime.timezone.utc)).isoformat()
    path = "citation_verification?id=eq.%s&client_id=eq.%s&state=eq.requires_verification" % (verification_id, client_id)
    rows = portal.call("PATCH", path, {"state": "live", "verified_at": t, "updated_at": t}, prefer="return=representation")
    return isinstance(rows, list) and len(rows) == 1


def record_transition(client, row_id, new_state, evidence_url=None, note=None, *, queue_path=None, today=None, portal=None,
                      dry_run=False, activities=None, activities_flag=None, directories=None, verify_type=None, verification=None,
                      verify_deadline_days=POSTCARD_DEADLINE_DAYS, steps=None, directory_url=None, listing_url=None, listing_id=None, recheck_due=None, reason=None, refresh_url=False, activities_hold_flag=None, backoff=None, park_reason=None, proof=None, observation=None, reason_code=None, vault_item=None, allowlist_path=None, vault_items_lookup=None, signin_url=None):
    """Returns a dict describing what was (or, in dry_run, would be) written. Refusals raise TransitionRefused before any write.
    portal: object with latest_snapshot(client_id)/upsert_snapshot(...) (default: real Portal from the prod env pointer).
    activities: object with call(method, path, body, prefer) (default: the same Portal).
    verify_type: phone-call|sms|postcard with new_state needs-human; upserts a citation_verification row via `verification` (default: the Portal).
    directories: object with .owner and call(method, path, body, prefer) for the Directory database (default: DirDB from the weekly job env;
    CE_DIRECTORIES_WRITE=0 turns the sink off)."""
    real_sink = portal is None and verification is None   # t_f31e2490: only a run on the real Portal writes the machine-wide allowlist file; an injected fake (tests) needs allowlist_path
    tenant = tenant_of(client)
    client_id = P.client_for(client)
    path = queue_path or tenant["queue_default"]()
    tenant = _tenant_lock(client, row_id, path)
    day = today or datetime.date.today().isoformat()
    q = _read(path)
    Q.parse_rows(q)
    row = _find(q, row_id)
    old = row["state"]
    if W.is_stopped(row) and new_state != "needs-human":
        raise TransitionRefused("row %s is STOPPED by the hard-block cap; only Mike's --reset-wall (job/walls.py) clears it" % row_id)
    check_transition(old, new_state, note, reason, refresh_url)
    if new_state == "live" and not refresh_url:   # t_d660babc: the ONE live writer fails closed: no live without complete Proof
        proof = check_proof(proof)
    elif proof is not None:
        raise TransitionRefused("proof only applies to a move into live")
    if backoff is not None and (backoff not in BACKOFF_MARKERS or old != new_state or not recheck_due):
        raise TransitionRefused("backoff %r: only %s, as a same-state move with --recheck-due" % (backoff, "/".join(BACKOFF_MARKERS)))
    if park_reason is not None:   # t_8d1865a3: the cap move. Any waiting row -> needs-human, with a structured reason.
        if park_reason not in PARK_REASONS or new_state != "needs-human" or old == "needs-human" or not (note or "").strip():
            raise TransitionRefused("park_reason %r: only %s, on a move INTO needs-human from another state, with a note" % (park_reason, "/".join(PARK_REASONS)))
    if reason_code is not None and (reason_code not in D.REASON_CODES or new_state != "needs-human"):   # t_8d61ef01: refused BEFORE any write (the sink used to fail after the queue was written)
        raise TransitionRefused("reason_code %r: one of %s, and only on a move to needs-human" % (reason_code, "/".join(D.REASON_CODES)))
    if refresh_url:   # the evidence URL is the new URL; listing_url follows it, so the next recheck reads the live slug
        if not evidence_url: raise TransitionRefused("--refresh-url needs --evidence (the final URL after redirects)")
        listing_url = evidence_url
    requeue = new_state == "queued"
    if requeue: note = "re-create after rejection: %s" % reason.strip()   # t_d2f75685: logged, never a silent reset (the history entry also carries requeue + reason)
    evidence_url = check_evidence(evidence_url, new_state)
    verify_type = check_verify_type(verify_type, new_state)
    if verify_type:   # t_e2db63f0: the Your turn gate. Refused BEFORE any write unless an agent saw the live verify step this cycle.
        dir_row = None
        if directories is not None or D.enabled():
            try: dir_row = ((directories or D.DirDB()).call("GET", "ce_directories?domain=eq.%s&select=dead,dead_reason,cost,verification_methods" % row["directory"], None, "return=representation") or [None])[0]
            except Exception as e: raise TransitionRefused("Your turn gate: could not read the Directory DB row for %s (%s); fail closed" % (row["directory"], type(e).__name__))
        problems = YT.check_your_turn(row["directory"], verify_type, observation, dir_row, day)
        if problems: raise TransitionRefused("Your turn gate refused %s: %s" % (row["directory"], "; ".join(problems)))
    steps, directory_url = check_id_check_fields(verify_type, steps, directory_url)
    if signin_url is not None:   # t_9de1c978: refused before any write; only a phone/SMS park reaches the allowlist
        if verify_type not in AL.AUTO_TYPES: raise TransitionRefused("--signin-url only applies to an sms or phone-call park")
        try: signin_url = AL.check_signin_url(row["directory"], signin_url)
        except ValueError as e: raise TransitionRefused("--signin-url: %s" % e)
    if verify_type: note = verification_note(verify_type)

    approval_before = copy.deepcopy(row.get("mike_approval"))
    new_row = copy.deepcopy(row)
    new_row["state"] = new_state
    if proof: new_row["proof"] = dict(proof)
    if evidence_url: new_row["evidence_url"] = evidence_url
    if old != new_state: new_row.pop("recheck_due", None)   # t_d2f75685: a retry-later marker belongs to the state it was set in
    listing_url = check_evidence(listing_url, "submitted") if listing_url else None   # t_3ac43137: the URL the Directory showed at submit (permalink, owner view or confirmation); plain http(s) only
    if listing_url: new_row["listing_url"] = listing_url
    if recheck_due:   # t_6b1e01ff: the earliest day recheck reads this row (foursquare: 2 days after the edit is sent)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(recheck_due)): raise TransitionRefused("recheck_due must be YYYY-MM-DD")
        new_row["recheck_due"] = str(recheck_due)
    if listing_id and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-]{2,40}", str(listing_id)): new_row["listing_id"] = str(listing_id)
    entry = {"at": day, "from": old, "to": new_state, "evidence_url": evidence_url, "note": note or None}
    if verify_type: entry["verify_type"] = verify_type  # history carries the type, not only the note text (t_568f1ee6)
    if requeue: entry["requeue"] = True; entry["reason"] = reason.strip()
    if recheck_due: entry["recheck_due"] = str(recheck_due)
    if backoff: entry["backoff"] = backoff
    if park_reason: entry["park_reason"] = park_reason
    if reason_code: entry["reason_code"] = reason_code   # t_8d61ef01: stored at park time so a backfill can send it
    new_row.setdefault("history", [])
    new_row["history"] = list(new_row["history"]) + [entry]
    assert new_row.get("mike_approval") == approval_before  # never touched

    out = {"dry_run": bool(dry_run), "row_id": row_id, "from": old, "to": new_state, "history_entry": entry, "reason_code": reason_code, "errors": []}
    same_state = old == new_state  # note refresh: no client news, no Activities row
    rec = build_activity_record(client_id, new_row, new_state, evidence_url, day, hold=activities_hold_flag) if tenant["activities"] and new_state in ACTIVITY_STATES and not same_state else None
    out["activity_record"] = rec
    out["activities_written"] = False
    use_act = tenant["activities"] and activities_enabled(activities_flag) and new_state in ACTIVITY_STATES and not same_state
    out["activities_flag_on"] = use_act
    ver_rec = build_verification_record(client_id, row["directory"], verify_type, day, verify_deadline_days, steps=steps, directory_url=directory_url) if verify_type else None
    out["verification_record"] = ver_rec
    out["tenant"] = {"client": client, "slug": tenant["slug"], "client_id": client_id}
    if ver_rec: assert ver_rec["client_id"] == client_id == P.client_for(client)   # the portal row can only carry THIS tenant's id
    out["verification_written"] = False
    out["allowlist"] = None
    ver_patch_path = "citation_verification?client_id=eq.%s&directory=eq.%s&state=eq.requires_verification" % (client_id, row["directory"])

    if dry_run:
        pp = portal_payload_for(None, new_row, day)
        out["queue_row_after"] = {k: new_row[k] for k in ("id", "directory", "state", "evidence_url", "history") if k in new_row}
        out["portal_request"] = ({"method": "POST", "path": "footprint_snapshot?on_conflict=client_id,source,captured_day",
                                  "row": {"client_id": client_id, "source": P.SOURCE, "captured_day": day,
                                          "payload": "latest snapshot payload, directories patched with:",
                                          "directory_patch": pp["directories"]}} if tenant["snapshot"]
                                 else "skipped: %s queue has no portal snapshot (Your turn row + allowlist only)" % client)
        out["directories_request"] = {"queue_state": new_state, "reason_code": reason_code if new_state == "needs-human" else None}
        out["activities_request"] = ({"method": "POST", "path": "deliverables?on_conflict=client_id,source_ref", "body": [rec]} if use_act
                                     else "skipped: %s=0 or state %s is not client news" % (FLAG, new_state))
        out["verification_request"] = (
            {"method": "POST", "path": VERIFY_UPSERT_PATH, "body": [ver_rec]} if ver_rec else
            {"method": "PATCH", "path": ver_patch_path, "body": {"state": "live", "verified_at": "<now>"}} if new_state == "live"
            else "skipped: no verification step")
        out["allowlist_request"] = ({"directory": row["directory"], "channel": verify_type, "tenant": client, "vault_item": vault_item or "<resolved from the vault at write time; no guess>"}
                                    if verify_type in AL.AUTO_TYPES else "skipped: not a phone/SMS park")
        return out

    # 1 queue file (source of truth). Replace the row in place, preserving the rest of the file.
    kind = _kind_of(q, row_id)
    for _key, _kind, rows in _row_lists(q):
        for i, r in enumerate(rows):
            if r.get("id") == row_id: rows[i] = new_row
    out["proof_mirrored"] = mirror_proof_quiet(q, directories)   # t_78dc54b5: fill live rows whose DB Proof is complete but whose queue row has none
    if tenant["queue_name"]:   # NM: first write of the day keeps a backup, as nm_transitions does
        import shutil
        bak = "%s.bak-nm-%s" % (path, day)
        if not os.path.exists(bak): shutil.copyfile(path, bak)
        out["backup"] = bak
    _write_atomic(path, q)
    out["queue_written"] = path

    # 2 portal snapshot (SCC only; the NM queue has none)
    if not tenant["snapshot"]:
        out["portal_written"] = "skipped"
    else:
        try:
            portal = portal or P.Portal(*P.load_portal_env())
            latest = portal.latest_snapshot(client_id)
            base = latest["payload"] if latest else None
            if base is None: raise P.PortalWriteError("no existing SCC snapshot to overlay; run the weekly scan first")
            portal.upsert_snapshot(client_id, day, full_portal_payload(base, q, new_row, day))
            out["portal_written"] = True
        except Exception as e:
            out["portal_written"] = False
            out["errors"].append("portal: %s" % e)

    # 3 activities (gated)
    if use_act:
        try:
            act = activities or portal or P.Portal(*P.load_portal_env())
            act.call("POST", "deliverables?on_conflict=client_id,source_ref", [rec], prefer="resolution=merge-duplicates,return=minimal")
            out["activities_written"] = True
        except Exception as e:
            out["errors"].append("activities: %s" % e)

    # 3b verification queue (phone/sms/postcard). Never blocks the queue write above.
    if ver_rec or new_state == "live":
        try:
            ver = verification or portal or P.Portal(*P.load_portal_env())
            if ver_rec:
                ver.call("POST", VERIFY_UPSERT_PATH, [ver_rec], prefer="resolution=ignore-duplicates,return=minimal")  # existing row untouched: no deadline restart, a live row is not flipped back
            else:
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                ver.call("PATCH", ver_patch_path, {"state": "live", "verified_at": now, "updated_at": now}, prefer="return=minimal")
            out["verification_written"] = True
        except Exception as e:
            out["errors"].append("verification: %s" % e)
        # 3b2 t_f31e2490: in the same transition, a phone/SMS park puts the Directory on the Verify Now allowlist (runtime file outside the repo). Never blocks.
        if ver_rec and out["verification_written"] and verify_type in AL.AUTO_TYPES and (real_sink or allowlist_path):
            try:
                item = vault_item or _resolve_vault_item(row["directory"], vault_items_lookup, client)
                if item:
                    out["allowlist"] = AL.auto_add(row["directory"], verify_type, client, item, row_id, day, path=allowlist_path, signin_url=signin_url)
                    out["allowlist"]["vault_item_resolved"] = not vault_item
                else:
                    out["errors"].append("allowlist: vault item unresolved, pass --vault-item")
            except Exception as e:
                out["errors"].append("allowlist: %s" % type(e).__name__)
        # 3c t_79c39f75: client-facing id-check parks get a one-time sign-in Send. Flag-gated (CE_SIGNIN_SEND_WRITE=1), fails closed, never blocks the writes above.
        if ver_rec and out["verification_written"] and os.environ.get("CE_SIGNIN_SEND_WRITE") == "1":
            try:
                import signin_send as S
                out["signin_send"] = S.issue(client, row["directory"], verify_type, write=True, table=verification or portal)
            except Exception as e:
                out["errors"].append("signin_send: %s" % type(e).__name__)

    # 4 Directory database (ce_directory_status + needs-human blocker on ce_directories). Never blocks the queue write above.
    out["directories_written"] = False
    if directories is not None or D.enabled():
        try:
            out["directories"] = D.sync_transition(client, new_row, new_state, note, day, kind=kind, db=directories, proof=proof, reason_code=reason_code, old_state=old)
            out["directories_written"] = True
        except Exception as e:
            out["errors"].append("directories: %s" % e)
    return out


def create_row(client, domain, kind, *, queue_path=None, today=None, dry_run=False, note=None, directories=None):
    """t_cb7bad04: add ONE queued row for a Directory that has no row yet (NM: nm-fix-queue.json, fix_queue). No hand JSON edits.
    Refused: a tenant without create_row, a bad domain/kind, a Directory that already has a row (any list), an id collision. Backup (first write of the day) + atomic write."""
    t = tenant_of(client)
    if not t["create_row"]:
        raise TransitionRefused("--create-row is not available for %s (SCC rows come from job/buildrows.py)" % client)
    if kind not in ("fix", "create"): raise TransitionRefused("kind must be fix or create, got %r" % (kind,))
    domain = str(domain or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9\-]*(\.[a-z0-9][a-z0-9\-]*)+", domain): raise TransitionRefused("domain %r is not a bare domain like example.com" % (domain,))
    path = queue_path or t["queue_default"]()
    day = today or datetime.date.today().isoformat()
    rid = "%s%s-%s" % (t["row_prefix"] or "", kind, domain.split(".")[0])
    _tenant_lock(client, rid, path)
    q = _read(path)
    Q.parse_rows(q)
    have = {r.get("directory") for _k, _kd, rows in _row_lists(q) for r in rows}
    if domain in have: raise TransitionRefused("%s already has a queue row; use --row to move it" % domain)
    taken = {r.get("id") for _k, _kd, rows in _row_lists(q) for r in rows}
    if rid in taken: rid = "%s%s-%s" % (t["row_prefix"] or "", kind, domain.replace(".", "-"))
    if rid in taken: raise TransitionRefused("row id %s would collide" % rid)
    row = {"id": rid, "group": "C-new-row", "kind": kind, "directory": domain, "state": "queued", "cost": "free", "mike_approval": None,
           "build_note": (note or "row added by transitions.py --create-row (t_cb7bad04); no listing read yet").strip(),
           "history": [{"at": day, "from": None, "to": "queued", "evidence_url": None, "note": "row created (--create-row)"}]}
    out = {"dry_run": bool(dry_run), "client": client, "queue": path, "row": row, "backup": None, "directory_row_added": False}
    if directories is not None or D.enabled():   # t_9a722352: the Directory row first (the park's status row has an FK to it); a clear refusal, nothing written, when it cannot be added
        try: out["directory_row_added"] = D.ensure_directory(directories or D.DirDB(), domain, day, dry_run=dry_run)
        except Exception as e: raise TransitionRefused("%s is not in ce_directories and could not be added (%s: %s); nothing written" % (domain, type(e).__name__, e))
    if dry_run: return out
    import shutil
    bak = "%s.bak-nm-%s" % (path, day)
    if not os.path.exists(bak): shutil.copyfile(path, bak)
    out["backup"] = bak
    q.setdefault("fix_queue", []).append(row)
    _write_atomic(path, q)
    return out


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="Record a citation state transition (queue + Local SEO + gated Activities)")
    a.add_argument("--client", default="SCC")
    a.add_argument("--row", default=None)
    a.add_argument("--to", default=None, dest="new_state")
    a.add_argument("--evidence", default=None)
    a.add_argument("--note", default=None)
    a.add_argument("--verify-type", default=None, choices=VERIFY_TYPES, help="needs-human only: stopped at a phone call, SMS or postcard; writes the portal verification queue")
    a.add_argument("--step", action="append", default=None, help="id-check only: one plain instruction for the client (repeat per step)")
    a.add_argument("--directory-url", default=None, help="id-check only: the https page where the owner does the check")
    a.add_argument("--observed-type", default=None, help="Your turn gate: the verify type the agent SAW on the live verify step")
    a.add_argument("--screenshot", default=None, help="Your turn gate: path of the screenshot of that verify step")
    a.add_argument("--price-seen", default=None, help="Your turn gate: price shown on the verify step ('none' if no price)")
    a.add_argument("--observed-at", default=None, help="Your turn gate: YYYY-MM-DD the step was opened (this cycle: 7 days)")
    a.add_argument("--observed-url", default=None, help="Your turn gate: https URL of the verify step")
    a.add_argument("--final-url", default=None, help="Your turn gate: URL after redirects (a different domain = dead/redirect)")
    a.add_argument("--vault-item", default=None, help="sms/phone-call park: the Citations vault item name the build run signed in with (Verify Now allowlist entry); omitted: resolved with vault_item.resolve_for_domain, and no item = no auto-add")
    a.add_argument("--signin-url", default=None, dest="signin_url", help="sms/phone-call park: the Directory's real sign-in or signup page (https, on the Directory's own domain) for the Verify Now allowlist entry; omitted: the bare domain root")
    a.add_argument("--queue", default=None)
    a.add_argument("--dry-run", action="store_true", help="no queue write, no network; print the payloads")
    a.add_argument("--today", default=None)
    a.add_argument("--reason", default=None, help="rejected -> queued only: why a re-create can succeed this time (10+ characters; logged in the row history)")
    a.add_argument("--recheck-due", default=None, help="YYYY-MM-DD: batch tools skip this row until that day (retry later, e.g. a Directory sender limit)")
    a.add_argument("--park-reason", default=None, choices=PARK_REASONS, help="needs-human only: why the row is parked by a cap (no-public-permalink: 3 backoffs and still no listing URL)")
    a.add_argument("--refresh-url", action="store_true", help="live -> live only: store --evidence as both evidence_url and listing_url (the Directory moved the listing; needs --note)")
    a.add_argument("--reason-code", default=None, help="needs-human only: the badge the page shows for this row (paid, captcha, cloudflare, bot_wall, site_down, signup_form, nap, ...; job/directories.py REASON_CODES)")
    a.add_argument("--audit", action="store_true", help="read-only: list live rows with incomplete Proof; exit 1 if any")
    a.add_argument("--mirror-proof", action="store_true", dest="mirror_proof", help="t_78dc54b5: copy complete ce_directory_status Proof into live queue rows that lack it (dry run unless --write; backup first; no DB write, no state change)")
    a.add_argument("--write", action="store_true", help="with --mirror-proof: write the queue file")
    a.add_argument("--create-row", action="store_true", dest="create_row", help="t_cb7bad04: add ONE queued row for a Directory that has no row yet (needs --domain and --kind; NM only; --dry-run prints the row)")
    a.add_argument("--domain", default=None, help="with --create-row: the Directory domain, e.g. foursquare.com")
    a.add_argument("--kind", default=None, choices=("fix", "create"), help="with --create-row: fix (a wrong listing exists) or create (no listing yet)")
    n = a.parse_args(argv)
    if n.create_row:
        if not n.domain or not n.kind: a.error("--create-row needs --domain and --kind")
        try: res = create_row(n.client, n.domain, n.kind, queue_path=n.queue, today=n.today, dry_run=n.dry_run, note=n.note)
        except (TransitionRefused, Q.QueueError) as e:
            print("REFUSED: %s" % e, file=sys.stderr); return 1
        print(json.dumps(res, indent=2)); return 0
    if n.audit:
        miss = live_rows_missing_proof(_read(n.queue or Q.QUEUE_PATH), db_proof_by_directory())   # one read-only GET; DB Proof columns are the truth
        for rid, bad in miss: print("LIVE WITHOUT PROOF %s: %s" % (rid, ", ".join(bad)))
        print("%d live rows without complete Proof" % len(miss)); return 1 if miss else 0
    if n.mirror_proof:
        print(json.dumps(mirror_proof_file(n.queue or Q.QUEUE_PATH, write=n.write, today=n.today), indent=2)); return 0
    if n.write: a.error("--write only applies to --mirror-proof")
    if not n.row or not n.new_state: a.error("--row and --to are required")
    try:
        res = record_transition(n.client, n.row, n.new_state, n.evidence, n.note, queue_path=n.queue, today=n.today, dry_run=n.dry_run, verify_type=n.verify_type, steps=n.step, directory_url=n.directory_url, reason=n.reason, recheck_due=n.recheck_due, refresh_url=n.refresh_url, park_reason=n.park_reason, reason_code=n.reason_code, vault_item=n.vault_item, signin_url=n.signin_url,
                                observation=({"observed_type": n.observed_type, "screenshot": n.screenshot, "price_seen": n.price_seen, "observed_at": n.observed_at, "url": n.observed_url, "final_url": n.final_url} if n.verify_type else None))
    except (TransitionRefused, Q.QueueError, P.PortalWriteError) as e:
        print("REFUSED: %s" % e, file=sys.stderr)
        return 1
    print(json.dumps(res, indent=2))
    return 2 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
