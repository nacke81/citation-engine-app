"""Directory playbooks (t_413687a7): ONE place for every Directory's click-by-click steps, the Directory DB table ce_directory_playbooks
(same Supabase as ce_directories). The app shows them; the agents run from them. No local copy.

A playbook = (domain, task) -> ordered steps [{text, url?, selector?}] + send_is_signup (verify only). Steps carry PLACEHOLDERS, never tenant values:
  {business_name} {login_email} {phone} {website} {vault_item} {contact_name}
validate_steps refuses a secret-shaped or tenant-valued step BEFORE any write (6+ digit runs, emails, phones, `password: x`).
Everything goes through one injectable `db` with call(method, path, body=None, prefer=None) (directories.DirDB for real; tests pass a fake).

  python job/playbook.py show --domain thumbtack.com --task verify
  python job/playbook.py set  --domain thumbtack.com --task verify --file config/playbooks/thumbtack.com.verify.json [--dry-run]
The file is a JSON list of steps, or an object {steps, send_is_signup?, source?, last_proven_at?}.
"""
import argparse, datetime, json, os, re, sys
from urllib.parse import quote, urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TASKS = ("check", "create", "claim", "fix", "verify")
PLACEHOLDERS = ("business_name", "login_email", "phone", "website", "vault_item", "contact_name")
STEP_KEYS = ("text", "url", "selector")
_PH = re.compile(r"\{([A-Za-z_]+)\}")
_EMAIL = re.compile(r"[^\s@/]+@[^\s@/]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"\(?\d{3}\)?[\s.\-]*\d{3}[\s.\-]*\d{4}")
_DIGITS = re.compile(r"\d{6,}")
_SECRET = re.compile(r"(?i)\b((password|passwd|pwd|pw|passcode)\s*(=|:|is)|(code|otp|token)\s*(=|:))\s*\S")
_BAD_QUERY = {"code", "token", "password", "passwd", "pwd", "otp", "pw", "access_token", "api_key", "apikey"}


class PlaybookError(Exception):
    pass


def _check_text(where, s):
    bare = _PH.sub("", s)
    for m in _PH.finditer(s):
        if m.group(1) not in PLACEHOLDERS:
            raise PlaybookError("%s: unknown placeholder {%s} (allowed: %s)" % (where, m.group(1), ", ".join(PLACEHOLDERS)))
    if _EMAIL.search(bare): raise PlaybookError("%s: an email address (use {login_email})" % where)
    if _PHONE.search(bare): raise PlaybookError("%s: a phone number (use {phone})" % where)
    if _DIGITS.search(bare): raise PlaybookError("%s: a 6+ digit run (codes and ids do not belong in steps)" % where)
    if _SECRET.search(bare): raise PlaybookError("%s: a password or code assignment" % where)


def _check_url(where, u):
    if not re.match(r"https?://[^\s]+$", u): raise PlaybookError("%s: url must be one http(s) address" % where)
    p = urlparse(u)
    if p.username or p.password or "@" in (p.netloc or ""): raise PlaybookError("%s: url carries a login" % where)
    if _EMAIL.search(u): raise PlaybookError("%s: url carries an email address" % where)
    bad = _BAD_QUERY & set(k.lower() for k in parse_qs(p.query))
    if bad: raise PlaybookError("%s: url carries a secret-shaped parameter (%s)" % (where, ", ".join(sorted(bad))))
    # the 6+ digit rule is NOT applied here: Thumbtack's category_pk is an 18-digit id


def validate_steps(steps):
    """-> the clean list [{text, url?, selector?}]. PlaybookError on anything that is not a plain, secret-free, placeholder-only step list."""
    if not isinstance(steps, list) or not steps: raise PlaybookError("steps must be a non-empty list")
    out = []
    for i, s in enumerate(steps, 1):
        w = "step %d" % i
        if not isinstance(s, dict): raise PlaybookError("%s: must be an object {text, url?, selector?}" % w)
        extra = set(s) - set(STEP_KEYS)
        if extra: raise PlaybookError("%s: unknown key(s) %s" % (w, ", ".join(sorted(extra))))
        t = s.get("text")
        if not isinstance(t, str) or not t.strip(): raise PlaybookError("%s: text is required" % w)
        _check_text(w + " text", t)
        c = {"text": t.strip()}
        for k in ("url", "selector"):
            v = s.get(k)
            if v is None: continue
            if not isinstance(v, str) or not v.strip(): raise PlaybookError("%s: %s must be a non-empty string" % (w, k))
            (_check_url if k == "url" else _check_text)("%s %s" % (w, k), v.strip())
            c[k] = v.strip()
        out.append(c)
    return out


def check_target(domain, task, send_is_signup=False):
    if not isinstance(domain, str) or not re.match(r"^[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}$", domain): raise PlaybookError("bad domain %r" % (domain,))
    if task not in TASKS: raise PlaybookError("task must be one of %s" % ", ".join(TASKS))
    if send_is_signup and task != "verify": raise PlaybookError("send_is_signup is only for the verify task")


def get_playbook(db, domain, task):
    """-> the stored row {domain, task, steps, send_is_signup, version, ...} or None."""
    rows = db.call("GET", "ce_directory_playbooks?domain=eq.%s&task=eq.%s&select=*&limit=1" % (quote(domain, safe=""), quote(task, safe="")), prefer="return=representation")
    return rows[0] if rows else None


def set_playbook(db, domain, task, steps, send_is_signup=False, source=None, last_proven_at=None, now=None, dry_run=False):
    """Validate, check the Directory exists, bump the version, upsert on (domain, task). -> the row written (or that would be, on dry_run)."""
    domain = (domain or "").strip().lower()
    check_target(domain, task, send_is_signup)
    clean = validate_steps(steps)
    if not db.call("GET", "ce_directories?domain=eq.%s&select=domain&limit=1" % quote(domain, safe=""), prefer="return=representation"):
        raise PlaybookError("%s is not in ce_directories (add the Directory first)" % domain)
    cur = get_playbook(db, domain, task)
    ts = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = {"domain": domain, "task": task, "steps": clean, "send_is_signup": bool(send_is_signup), "source": source,
           "last_proven_at": last_proven_at, "updated_at": ts, "version": (cur or {}).get("version", 0) + 1}
    if not dry_run:
        db.call("POST", "ce_directory_playbooks?on_conflict=domain,task", [row], "resolution=merge-duplicates,return=minimal")
    return row


def render(pb, values):
    """-> [{text, url?, selector?}] with every placeholder filled from `values`. A placeholder with no value is an error (the agent never starts half-filled)."""
    def fill(s):
        def sub(m):
            v = values.get(m.group(1))
            if not isinstance(v, str) or not v: raise PlaybookError("no value for {%s}" % m.group(1))
            return v
        return _PH.sub(sub, s)
    out = []
    for s in validate_steps(pb.get("steps")):
        out.append({k: fill(v) for k, v in s.items()})
    return out


def _load_file(path):
    with open(path, encoding="utf-8") as f: data = json.load(f)
    if isinstance(data, list): return {"steps": data}
    if not isinstance(data, dict): raise PlaybookError("file must be a steps list or an object with steps")
    return data


def main(argv=None, db=None, out=print, err=None):
    a = argparse.ArgumentParser(description="Show or set a Directory playbook in the Directory DB (never any tenant value or secret)")
    sub = a.add_subparsers(dest="cmd", required=True)
    for name in ("show", "set"):
        p = sub.add_parser(name)
        p.add_argument("--domain", required=True)
        p.add_argument("--task", required=True, choices=TASKS)
        if name == "set":
            p.add_argument("--file", required=True)
            p.add_argument("--dry-run", action="store_true", help="validate and print the row; write nothing")
    n = a.parse_args(argv)
    err = err or (lambda m: print(m, file=sys.stderr))
    try:
        if n.cmd == "set":
            f = _load_file(n.file)
            for k, v in (("domain", n.domain), ("task", n.task)):
                if f.get(k) not in (None, v): raise PlaybookError("file %s %r does not match --%s %r" % (k, f.get(k), k, v))
            if n.dry_run and db is None:
                d = n.domain.strip().lower(); check_target(d, n.task, bool(f.get("send_is_signup")))
                out(json.dumps({"domain": d, "task": n.task, "steps": validate_steps(f.get("steps")), "send_is_signup": bool(f.get("send_is_signup")), "dry_run": True}, indent=1))
                return 0
            db = db or _real_db()
            row = set_playbook(db, n.domain, n.task, f.get("steps"), bool(f.get("send_is_signup")), f.get("source"), f.get("last_proven_at"), dry_run=n.dry_run)
            out(("DRY RUN, nothing written: " if n.dry_run else "written: ") + json.dumps({k: row[k] for k in ("domain", "task", "send_is_signup", "version")}) + " steps=%d" % len(row["steps"]))
            return 0
        db = db or _real_db()
        pb = get_playbook(db, n.domain.strip().lower(), n.task)
        if not pb: err("no %s playbook for %s" % (n.task, n.domain)); return 1
        out(json.dumps(pb, indent=1)); return 0
    except PlaybookError as e:
        err("REFUSED: %s" % e); return 1
    except (OSError, ValueError) as e:
        err("REFUSED: %s" % e); return 1


def _real_db():
    import directories as D
    return D.DirDB()


if __name__ == "__main__":
    sys.exit(main())
