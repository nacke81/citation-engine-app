"""Portal writer: one footprint_snapshot row per business (SCC, NM), source='citation_engine', from a run's ce_checks rows.

Only two portal clients can ever be written (ALLOWED, in code). The client id comes from the business code here, never from a caller,
and is checked before any network call. The prod service-role key is read in place from the portal repo's .env.prod.local; it is never
copied, printed or logged, and error text is scrubbed of it. No Directory traffic, no portal-seed call, no other table.
"""
import json, os, re, urllib.request

PORTAL_ENV_PTR = os.path.expandvars("%LOCALAPPDATA%/citation-engine/portal_env_path.txt")  # one line: path of the portal repo's .env.prod.local (outside this repo)
SOURCE = "citation_engine"  # underscore: the key the prod portal reader uses (Nate 2026-10-19)
ALLOWED = {
    "SCC": "e1fb5abd-8d7f-4d83-8cde-18934d149bb5",  # SCC client (prod lookup by slug, 2026-10-16)
    "NM": "fe3062b5-c956-4358-9e77-840e18be9f85",   # NM client
}
FORBIDDEN = {
    "430b764e-1a44-4246-959f-6b8945bf6a7c",  # Fitness by the Sea
    "7caf0d65-333d-4ba3-b71e-f03aaad5a578",
}


class PortalWriteError(Exception):
    pass


def check_client(client_id):
    """Raise unless client_id is exactly one of the two allow-listed ids. Called before any network call."""
    if client_id in FORBIDDEN:
        raise PortalWriteError("refusing forbidden client id")
    if client_id not in ALLOWED.values():
        raise PortalWriteError("client id is not on the SCC + NM allow-list")
    return client_id


def client_for(biz):
    if biz not in ALLOWED:
        raise PortalWriteError("business %r is not on the SCC + NM allow-list" % (biz,))
    return check_client(ALLOWED[biz])


def _issues(diffs):
    out = []
    for d in diffs or []:
        f = "website" if d.get("field") == "site" else d.get("field")
        if f and f not in out: out.append(f)
    return out


def _status(c):
    r = c["result"]
    if r == "found": return "nap"
    if r == "absent": return "undiscovered"
    if r == "couldnt_check": return "blocked" if c.get("note") == "blocked" else "unavailable"
    return "unavailable"  # unsearchable


STATE = {"found": "live", "absent": "absent"}  # everything else -> couldnt_check




def _errors(diffs):
    out = []
    for d in diffs or []:
        f = "website" if d.get("field") == "site" else d.get("field")
        if f: out.append({"field": f, "live": d.get("live"), "right": d.get("canonical")})
    return out


def build_payload(checks, captured_day=""):
    """checks: ce_checks-shaped dicts for ONE business. Found = Correct + With NAP errors.
    Unchecked rows carry napConsistent None (never False). pctFound is over checked rows only (found + notFound).
    A found row's url is a listing permalink or None with urlKind 'search' (never a search, category or guessed-slug URL)."""
    import listing
    dirs = []
    for c in sorted(checks, key=lambda x: x["directory"]):
        isf = c["result"] == "found"
        errs = _errors(c.get("diffs")) if isf else []
        issues = _issues(c.get("diffs")) if isf else []
        url, kind = None, None
        if isf:
            if c.get("url") and listing.is_permalink(c["directory"], c["url"]): url, kind = c["url"], "listing"
            else: kind = "search"
        reason, text = listing.reason_for(c["directory"], c["result"], c.get("note"))
        cl = (c.get("_claim") or {}) if isf else {}
        dirs.append({
            "name": c["directory"], "state": STATE.get(c["result"], "couldnt_check"), "stateDate": captured_day,
            "domain": c["directory"], "authority": None, "permalinkUnverified": bool(isf and c.get("_permalink_unverified")),
            "napConsistent": (not issues) if isf else None,
            "url": url, "urlKind": kind,
            "issues": issues, "napErrors": errs, "status": _status(c), "httpStatus": None, "method": c.get("method") if isf else None,
            "reason": reason, "reasonText": text,
            "claim_status": cl.get("claim_status", "unknown"), "claim_evidence": cl.get("claim_evidence"),   # extra fields; portal rendering ignores them for now
        })
    # t_f6267312: the scan totals (found / correct / couldntCheck / checked / directoriesChecked) were frozen at the last scan and went stale
    # against the queue overlay. They are no longer written; `summary` is recounted from `directories` here and again after every overlay.
    import snapshot as SN
    return SN.finalize({"keyScore": None, "keyScoreMax": 100, "directories": dirs})


def load_portal_env(path=None):
    path = path or os.environ.get("CE_PORTAL_ENV") or (open(PORTAL_ENV_PTR, encoding="utf-8").read().strip() if os.path.exists(PORTAL_ENV_PTR) else "")
    if not path: raise PortalWriteError("portal env path not configured")
    E = {}
    for l in open(path, encoding="utf-8"):
        m = re.match(r"\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", l)
        if m: E[m.group(1)] = m.group(2).strip("\"'")
    url, key = E.get("NEXT_PUBLIC_SUPABASE_URL"), E.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key: raise PortalWriteError("portal env missing url or key")
    if "127.0.0.1" in url or "localhost" in url: raise PortalWriteError("refusing: portal env resolves to local")
    return url, key


class Portal:
    """PostgREST client for footprint_snapshot only."""
    def __init__(self, url, key, opener=None):
        self.url, self._key, self._open = url.rstrip("/"), key, opener or (lambda req: urllib.request.urlopen(req, timeout=30))

    def _scrub(self, s): return str(s).replace(self._key, "***")

    def call(self, method, path, body=None, prefer=None):
        h = {"apikey": self._key, "Authorization": "Bearer " + self._key, "Content-Type": "application/json"}
        if prefer: h["Prefer"] = prefer
        req = urllib.request.Request(self.url + "/rest/v1/" + path, method=method, headers=h, data=json.dumps(body).encode() if body is not None else None)
        try:
            with self._open(req) as r:
                t = r.read(); return json.loads(t) if t else None
        except Exception as e:
            raise PortalWriteError(self._scrub("portal %s %s failed: %s: %s" % (method, path.split("?")[0], type(e).__name__, e)))

    def latest_snapshot(self, client_id):
        check_client(client_id)
        rows = self.call("GET", "footprint_snapshot?select=client_id,source,captured_day,payload&client_id=eq.%s&source=eq.%s&order=captured_day.desc&limit=1" % (client_id, SOURCE))
        return rows[0] if rows else None

    def upsert_snapshot(self, client_id, captured_day, payload):
        check_client(client_id)
        self.call("POST", "footprint_snapshot?on_conflict=client_id,source,captured_day",
                  [{"client_id": client_id, "source": SOURCE, "captured_day": captured_day, "payload": payload}],
                  prefer="resolution=merge-duplicates,return=minimal")
        rows = self.call("GET", "footprint_snapshot?select=client_id,source,captured_day,payload&client_id=eq.%s&source=eq.%s&captured_day=eq.%s" % (client_id, SOURCE, captured_day))
        if not rows or rows[0]["payload"].get("summary") != payload.get("summary"):
            raise PortalWriteError("portal readback did not match what was written")
        return rows[0]


def write_run(checks, captured_day, portal=None, queue_rows=None):
    """Write both businesses. Validates every id BEFORE the first network call. Returns {biz: readback summary}."""
    by = {b: [c for c in checks if c["biz"] == b] for b in ALLOWED}
    for b in {c["biz"] for c in checks}:
        client_for(b) if b != "FAKE" else None
    ids = {b: client_for(b) for b in ALLOWED}
    for b, cs in by.items():
        if not cs: raise PortalWriteError("no checks for %s; refusing a partial portal write" % b)
    portal = portal or Portal(*load_portal_env())
    out = {}
    for b, cs in by.items():
        p = build_payload(cs, captured_day)
        if b == "SCC":  # fix/create queue state is shown on SCC only
            import buildqueue
            p = buildqueue.overlay_directories(p, queue_rows if queue_rows is not None else buildqueue.load_all_rows(), captured_day)
        row = portal.upsert_snapshot(ids[b], captured_day, p)
        out[b] = {"client_id": row["client_id"], "source": row["source"], "captured_day": row["captured_day"],
                  "summary": p["summary"]}
    return out
