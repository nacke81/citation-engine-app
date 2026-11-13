"""Verify Now allowlist: the runtime (auto) half. t_f31e2490.

When record_transition parks a row on a phone/SMS code step, the Directory joins the Verify Now allowlist here, in a file OUTSIDE the repo
(%LOCALAPPDATA%/citation-engine/verify_directories.local.json) so the runtime clone stays clean for fast-forwards. The repo file wins on conflict
(verify_bridge.load_directories). Only sms and phone-call are ever added. No network, no portal."""
import datetime, json, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
AUTO_TYPES = ("sms", "phone-call")      # postcard, id-check, client-email, document-upload are never added
LOCAL_NAME = "verify_directories.local.json"


def local_path():
    p = os.environ.get("CE_VERIFY_DIRECTORIES_LOCAL")
    if p: return p
    if os.environ.get("CE_VERIFY_DIRECTORIES"): return None     # tests point at a fixture: no machine-wide file leaks in
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "citation-engine", LOCAL_NAME)


def _inside_repo(path):
    a, r = os.path.normcase(os.path.abspath(path)), os.path.normcase(REPO_ROOT)
    return a == r or a.startswith(r + os.sep)


def _read_rows(path):
    try:
        with open(path, encoding="utf-8") as f: rows = json.load(f).get("directories")
    except Exception:
        return []
    return rows if isinstance(rows, list) else []


def _write_rows(p, rows):
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(p)), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"_comment": "Auto-added by record_transition on a phone/SMS park. The repo file wins on conflict; a row for a repo Directory only supplements it (adds a channel or a tenant vault item).", "directories": rows}, f, indent=2); f.write("\n")
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp): os.unlink(tmp)
        raise


def _find(entries, dom):
    for e in entries:
        if dom in [e["domain"]] + e["aliases"]: return e
    return None


def check_signin_url(directory, url):
    """t_9de1c978: park --signin-url. -> the clean https URL; ValueError when it is not one https address on the Directory's own host
    (no userinfo, no spaces, no other host). The bare domain root was the auto-add default and is not a sign-in page."""
    import verify_bridge as B
    from urllib.parse import urlparse
    dom = B.norm_domain(directory)
    if not isinstance(url, str) or not re.match(r"^https://[^\s]+$", url): raise ValueError("signin_url must be one https URL with no spaces")
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if p.username or p.password or "@" in (p.netloc or ""): raise ValueError("signin_url carries a login")
    if not dom or not (host == dom or host.endswith("." + dom)): raise ValueError("signin_url host is not the Directory's own domain")
    return url


def auto_add(directory, verify_type, tenant, vault_item, row_id, day=None, path=None, signin_url=None):
    """-> {"added": bool, "reason": str, "path": str|None, "kind": "new"|"merged"|"supplement"|None}.
    The bridge matches domain AND channel and the send needs vault_items[tenant], so "domain listed" is not enough:
      * not listed anywhere            -> a new local entry;
      * listed in the LOCAL file       -> that entry gains the missing channel and/or tenant vault item (atomic rewrite);
      * listed in the REPO file (agent)-> a local supplement row adds only the missing channel/tenant (the repo file is never touched; load_directories merges it);
      * a repo send=script entry       -> untouched (changing a script send needs a PR).
    Idempotent: when channel and tenant item are both already present (repo, supplement or local), nothing is written."""
    import verify_bridge as B
    if verify_type not in AUTO_TYPES: return {"added": False, "reason": "type %s is never auto-added" % verify_type, "path": None, "kind": None}
    dom = B.norm_domain(directory)
    if not dom or not re.fullmatch(r"[a-z0-9.\-]+", dom): return {"added": False, "reason": "bad directory", "path": None, "kind": None}
    if not tenant or not vault_item: return {"added": False, "reason": "tenant and vault item are required", "path": None, "kind": None}
    p = path or local_path()
    if not p: return {"added": False, "reason": "no local file configured", "path": None, "kind": None}
    if _inside_repo(p): raise ValueError("the auto allowlist file must live outside the repo")
    repo = _find(B._load_file(os.environ.get("CE_VERIFY_DIRECTORIES") or B.DIRECTORIES_PATH, "repo"), dom)   # the target file itself, not the machine default
    rows = _read_rows(p)
    loc = None
    for r in rows:
        if isinstance(r, dict) and dom in [B.norm_domain(r.get("domain"))] + [B.norm_domain(x) for x in r.get("aliases") or []]: loc = r; break
    have_ch = set((repo or {}).get("channels") or []) | set((loc or {}).get("channels") or [])
    have_vi = set(((repo or {}).get("vault_items") or {}).keys()) | set(((loc or {}).get("vault_items") or {}).keys())
    need_ch, need_vi = verify_type not in have_ch, tenant not in have_vi
    # a LOCAL auto entry's wrong item is replaced by a later explicit/resolved one; a repo value is never replaced
    fix_vi = (not need_vi and tenant not in ((repo or {}).get("vault_items") or {}) and loc is not None and loc.get("added_by") == "auto"
              and (loc.get("vault_items") or {}).get(tenant) not in (None, vault_item))
    if signin_url is not None: signin_url = check_signin_url(dom, signin_url)
    # a LOCAL auto entry still on the bare domain root is upgraded to the given sign-in page; a repo entry's URL is never replaced
    fix_url = bool(signin_url and loc is not None and loc.get("added_by") == "auto" and loc.get("signin_url") in (None, "https://%s/" % dom) and loc.get("signin_url") != signin_url)
    if not need_ch and not need_vi and not fix_vi and not fix_url: return {"added": False, "reason": "already listed", "path": p, "kind": None}
    if repo and repo["send"] != "agent": return {"added": False, "reason": "repo entry is send=%s; extending it needs a PR" % repo["send"], "path": p, "kind": None}
    if loc is not None:
        if need_ch: loc["channels"] = list(loc.get("channels") or []) + [verify_type]
        if need_vi or fix_vi: loc["vault_items"] = dict(loc.get("vault_items") or {}, **{tenant: vault_item})
        if fix_url: loc["signin_url"] = signin_url
        _write_rows(p, rows)
        return {"added": True, "reason": "merged", "path": p, "kind": "merged"}
    entry = {"domain": repo["domain"] if repo else dom, "aliases": [], "channels": [verify_type] if need_ch else [], "send": "agent",
             "signin_url": signin_url or "https://%s/" % dom, "vault_items": {tenant: vault_item} if need_vi else {}, "added_by": "auto", "row_id": row_id,
             "added_on": day or datetime.date.today().isoformat()}
    if repo: entry["supplement"] = True
    _write_rows(p, rows + [entry])
    return {"added": True, "reason": "added", "path": p, "kind": "supplement" if repo else "new"}
