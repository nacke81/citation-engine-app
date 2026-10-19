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


def build_payload(checks, captured_day=""):
    """checks: ce_checks-shaped dicts for ONE business. Counts follow the build app: Found = Correct + With NAP errors."""
    dirs = []
    for c in sorted(checks, key=lambda x: x["directory"]):
        issues = _issues(c.get("diffs")) if c["result"] == "found" else []
        dirs.append({
            "name": c["directory"], "state": STATE.get(c["result"], "couldnt_check"), "stateDate": captured_day,
            "domain": c["directory"], "authority": None,
            "napConsistent": c["result"] == "found" and not issues,
            "url": (c.get("url") or None) if c["result"] == "found" else None,
            "issues": issues, "status": _status(c), "httpStatus": None, "method": c.get("method") if c["result"] == "found" else None,
        })
    found = sum(1 for c in checks if c["result"] == "found")
    correct = sum(1 for d in dirs if d["status"] == "nap" and d["napConsistent"])
    not_found = sum(1 for c in checks if c["result"] == "absent")
    cant = sum(1 for c in checks if c["result"] in ("couldnt_check", "unsearchable"))
    denom = found + not_found
    return {"keyScore": None, "keyScoreMax": 100, "found": found, "notFound": not_found, "correct": correct,
            "withNapErrors": found - correct, "couldntCheck": cant,
            "pctFound": 0 if denom == 0 else round(found / denom * 100), "directories": dirs}


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

    def upsert_snapshot(self, client_id, captured_day, payload):
        check_client(client_id)
        self.call("POST", "footprint_snapshot?on_conflict=client_id,source,captured_day",
                  [{"client_id": client_id, "source": SOURCE, "captured_day": captured_day, "payload": payload}],
                  prefer="resolution=merge-duplicates,return=minimal")
        rows = self.call("GET", "footprint_snapshot?select=client_id,source,captured_day,payload&client_id=eq.%s&source=eq.%s&captured_day=eq.%s" % (client_id, SOURCE, captured_day))
        if not rows or rows[0]["payload"].get("found") != payload["found"]:
            raise PortalWriteError("portal readback did not match what was written")
        return rows[0]


def write_run(checks, captured_day, portal=None):
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
        row = portal.upsert_snapshot(ids[b], captured_day, p)
        out[b] = {"client_id": row["client_id"], "source": row["source"], "captured_day": row["captured_day"],
                  "found": p["found"], "correct": p["correct"], "withNapErrors": p["withNapErrors"], "notFound": p["notFound"], "couldntCheck": p["couldntCheck"]}
    return out
