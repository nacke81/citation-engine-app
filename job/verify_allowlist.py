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


def auto_add(directory, verify_type, tenant, vault_item, row_id, day=None, path=None):
    """-> {"added": bool, "reason": str, "path": str|None}. Idempotent: a Directory already listed (repo or local, domain or alias) adds nothing."""
    import verify_bridge as B
    if verify_type not in AUTO_TYPES: return {"added": False, "reason": "type %s is never auto-added" % verify_type, "path": None}
    dom = B.norm_domain(directory)
    if not dom or not re.fullmatch(r"[a-z0-9.\-]+", dom): return {"added": False, "reason": "bad directory", "path": None}
    if not tenant or not vault_item: return {"added": False, "reason": "tenant and vault item are required", "path": None}
    p = path or local_path()
    if not p: return {"added": False, "reason": "no local file configured", "path": None}
    if _inside_repo(p): raise ValueError("the auto allowlist file must live outside the repo")
    for e in B._load_file(os.environ.get("CE_VERIFY_DIRECTORIES") or B.DIRECTORIES_PATH, "repo") + B._load_file(p, "local"):   # the target file itself, not the machine default
        if dom in [e["domain"]] + e["aliases"]: return {"added": False, "reason": "already listed", "path": p}
    rows = _read_rows(p)
    entry = {"domain": dom, "aliases": [], "channels": [verify_type], "send": "agent", "signin_url": "https://%s/" % dom,
             "vault_items": {tenant: vault_item}, "added_by": "auto", "row_id": row_id,
             "added_on": day or datetime.date.today().isoformat()}
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(p)), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"_comment": "Auto-added by record_transition on a phone/SMS park. The repo file wins on conflict.", "directories": rows + [entry]}, f, indent=2); f.write("\n")
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp): os.unlink(tmp)
        raise
    return {"added": True, "reason": "added", "path": p}
