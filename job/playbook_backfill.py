"""One-time backfill of ce_directory_playbooks from the vault build playbooks + the ce_directories fields (t_2cb780c2).

  python job/playbook_backfill.py                      dry run (default): reads, classifies, validates, prints counts per task, writes nothing
  python job/playbook_backfill.py --report out.json    also save the full report (rows, dropped sentences with reasons)
  python job/playbook_backfill.py --write              upsert through playbook.set_playbook (service key; needs migration 017 and, for stale flags, 018)

Rules (every one is tested in tests/playbook_backfill_test.py):
- PLACEHOLDERS ONLY. A sentence is DROPPED (never scrubbed into a guess) when it holds a tenant token (sha256 denylist tests/denylist.json plus the
  identity file when present), an email, a phone number, a 6+ digit run, or fails playbook.validate_steps. Only two scrubs are allowed: a vault item name
  (`SCC - site`, `NM - site`) -> {vault_item}, and a phone from the identity file -> {phone}.
- last_proven_at is ALWAYS null. A backfill is not a run that reached its goal.
- A directory whose note says rejected / no-fit / dead / 404 (or a bot-wall note while ce_directories now says the agent has access) is written STALE.
  All of that directory's backfilled rows are stale, including the ones built from the Directory fields.
- An existing (domain, task) row is never overwritten.
- Notes are prose, not scripts: only sentences that read as an action (open, click, fill, ...) AND carry a url, a selector or a UI word become steps.
"""
import argparse, glob, hashlib, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import playbook as PB  # noqa: E402

VAULT_DEFAULT = os.environ.get("CE_VAULT_PLAYBOOKS") or ""   # the vault build playbooks dir (Projects/citation-engine/playbooks/build); the path lives outside the repo, so pass --vault or set this
DENY_PATH = os.path.join(HERE, "..", "tests", "denylist.json")

_URL = re.compile(r"https?://[^\s`)\]>\"']+")
_EMAIL = re.compile(r"[^\s@/`]+@[^\s@/`]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"\(?\d{3}\)?[\s.\-]*\d{3}[\s.\-]*\d{4}")
_VAULT_ITEM = re.compile(r"\b(?:SCC|NM) - [A-Za-z0-9][A-Za-z0-9.\-]*\.[a-z]{2,}")
_TICKS = re.compile(r"`([^`]+)`")
_SELECTOR = re.compile(r"^(?:[#.\[][^\s]*|[a-z]+\[[^\]]+\][^\s]*|[a-z]*[#.][\w\-]+[^\s]*)$")
_HEAD_SKIP = re.compile(r"^\s*(?:outcome|time|blocker|scriptable|verify type|facts|row|open issues|state|status|result|nm state)\b", re.I)
_ACTION = re.compile(r"^(?:step \d+[:.]?\s*)?(?:then |next |first |also |finally |after that )?(?:js-|real )?(?:open|navigate|go to|visit|click|press|tap|fill|type|enter|select|choose|tick|check|pick|skip|wait|sign in|sign up|log in|register|create|add|submit|search|upload|confirm|verify|claim|use|set|save|continue|accept|dismiss|reload|edit|update|pass|read|run|load|find|look)\b", re.I)
_UIWORD = re.compile(r"\b(?:button|form|field|page|link|checkbox|modal|dropdown|menu|tab|wizard|dashboard|captcha|recaptcha|input|search box|results?|code)\b", re.I)
_NEG_OUTCOME = re.compile(r"\b(?:rejected|no[- ]fit|dead|defunct|out of business|abandon\w*|404|not a category|no free)\b", re.I)
_WALL = re.compile(r"\b(?:bot wall|cloudflare|datadome|turnstile|captcha wall|blocked|403)\b", re.I)
TASK_RULES = (   # first rule that matches wins; order is deliberate (claim and fix words also say "verify" or "search")
    ("claim", re.compile(r"\bclaim\w*|\bown(?:er|ership)\b|\bis this your business\b", re.I)),
    ("fix", re.compile(r"\b(?:edit|update|correct|change|fix)\b|\bedit[- ]?(?:profile|company|listing)\b", re.I)),
    ("verify", re.compile(r"\b(?:code|otp|sms|text message|postcard|verif\w*|sign[- ]?in|log[- ]?in|password|2fa|email access)\b", re.I)),
    ("create", re.compile(r"\b(?:sign[- ]?up|register\w*|create|add (?:a |your )?(?:business|listing|company)|wizard|submit|new account)\b", re.I)),
    ("check", re.compile(r"\b(?:search\w*|find|look ?up|zero|no results?|could not find|already listed|existing listing)\b", re.I)),
)


def load_denylist(path=DENY_PATH):
    try:
        return set(json.load(open(path, encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def identity_tokens(path=None):
    """Words and phones from the approved identity file (outside the repo). -> (set of lowercase words, set of 10-digit phones). Empty when unreadable."""
    path = path or os.environ.get("CE_IDENTITY") or os.path.expandvars("%LOCALAPPDATA%/citation-engine/identity.json")
    words, phones = set(), set()
    try:
        ident = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return words, phones
    for biz in (ident.get("BIZ") or {}).values():
        if not isinstance(biz, dict): continue
        for k in ("name", "short", "street", "city", "slug", "contact"):
            for w in re.findall(r"[A-Za-z0-9]{4,}", str(biz.get(k) or "").lower()): words.add(w)
        for k in ("phones", "stale_phones"):
            for p in biz.get(k) or []:
                d = re.sub(r"\D", "", str(p))[-10:]
                if len(d) == 10: phones.add(d)
    return words, phones


class Scrubber:
    def __init__(self, deny=None, id_words=None, id_phones=None, use_deny=True):
        self.deny = load_denylist() if deny is None else deny
        self.words, self.phones = (id_words, id_phones) if id_words is not None else identity_tokens()
        self.use_deny = use_deny

    def tenant_hit(self, text):
        for w in set(re.findall(r"[A-Za-z0-9]+", text.lower())):
            if self.use_deny and len(w) >= 3 and hashlib.sha256(w.encode()).hexdigest() in self.deny: return "tenant token"
            if w in self.words: return "tenant token"
        for m in re.finditer(r"\(?(\d{3})\)?[\s.\-]*(\d{3})[\s.\-]*(\d{4})", text):
            if self.use_deny and hashlib.sha256((m.group(1) + m.group(2) + m.group(3)).encode()).hexdigest() in self.deny: return "tenant phone"
        return None

    def clean(self, text):
        """-> (text with the two allowed scrubs applied, drop reason or None)."""
        t = _VAULT_ITEM.sub("{vault_item}", text)
        def ph(m):
            return "{phone}" if re.sub(r"\D", "", m.group(0))[-10:] in self.phones else m.group(0)
        t = _PHONE.sub(ph, t)
        why = self.tenant_hit(t)
        if why: return t, why
        if _EMAIL.search(t): return t, "email address"
        if _PHONE.search(_PH_STRIP.sub("", t)): return t, "phone number"
        return t, None


_PH_STRIP = re.compile(r"\{[a-z_]+\}")


def sentences(md):
    """Candidate sentences from one vault note: heading, bullets and 'Steps:' lines split on sentence ends. Headings and outcome/blocker lines are skipped."""
    out = []
    for line in md.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("|") or s.startswith("---"): continue
        s = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", s).replace("**", "")
        if _HEAD_SKIP.match(s) and not re.match(r"steps?\b", s, re.I): continue
        s = re.sub(r"^steps?(?: that worked)?:\s*", "", s, flags=re.I)
        for part in re.split(r"(?<=[.!?;])\s+(?=[A-Z`#\[(\"'])|\s+->\s+", s):
            part = part.strip()
            if len(part) >= 8: out.append(part)
    return out


def classify(sentence):
    for task, rx in TASK_RULES:
        if rx.search(sentence): return task
    return None


def make_step(sentence, scrub):
    """-> (step dict or None, drop reason or None)."""
    if not _ACTION.search(sentence): return None, "not an action"
    url = None
    m = _URL.search(sentence)
    body = sentence
    if m:
        url = m.group(0).rstrip(".,;:")
        body = body.replace(m.group(0), "").strip()
        # a note url may carry a client's listing id (query or path, e.g. ?ypid=577699341, /company/39540176): query is always dropped, a 5+ digit id drops the url
        url = url.split("?")[0].split("#")[0]
        if re.search(r"\d{5,}", url): url = None
    sel = None
    for t in _TICKS.findall(sentence):
        if _SELECTOR.match(t.strip()): sel = t.strip(); break
    if not (url or sel or _UIWORD.search(sentence)): return None, "no url, selector or UI word"
    body = _TICKS.sub(lambda mm: mm.group(1), body)
    body = re.sub(r"[*_]{1,2}", "", body)
    body = re.sub(r"\s+", " ", body).strip(" -:;,")
    if len(body) > 300: body = body[:297].rstrip() + "..."
    text, why = scrub.clean(body or "Open the page")
    if why: return None, why
    if len(text) < 12 and not url and not sel: return None, "too short to be a step"
    if sel:
        sel, why = scrub.clean(sel)
        if why: sel = None
    if url:
        u, why = scrub.clean(url)
        url = None if why else url
    step = {"text": text}
    if url: step["url"] = url
    if sel: step["selector"] = sel
    try:
        PB.validate_steps([step])
    except PB.PlaybookError:
        step.pop("selector", None)   # a bad selector or url must not sink a good sentence: retry bare, then drop
        try: PB.validate_steps([step])
        except PB.PlaybookError:
            step.pop("url", None)
            try: PB.validate_steps([step])
            except PB.PlaybookError as e: return None, "validator: " + str(e)[:60]
    return step, None


def field_steps(d):
    """Deterministic steps from the ce_directories fields. -> {task: [steps]} (only tasks the fields can support)."""
    out = {}
    dom = d["domain"]
    sm = str(d.get("search_method") or "")
    if sm.startswith("own-search"):
        home = "https://" + dom + "/"
        tpl = d.get("search_url_template") or ""
        m = re.match(r"(https?://[^/{]+)", tpl)
        steps = [{"text": "Open the Directory's own search", "url": (m.group(1) + "/") if m else home}]
        steps.append({"text": "Search for {business_name} with the business city and state" + (" (the Directory row lists the search URL pattern)" if tpl else "")})
        if d.get("zero_marker_text"): steps.append({"text": "No listing exists when the page says: " + str(d["zero_marker_text"]).strip()[:160]})
        steps.append({"text": "Open the result that matches the business name and phone; stop and record not found when none does"})
        out["check"] = steps
    if d.get("signup_url"):
        out["create"] = [{"text": "Open the sign-up page", "url": d["signup_url"]}, {"text": "Register or sign in with {login_email} and the vault item {vault_item}"}]
    if d.get("claim_url") or d.get("claim_markers"):
        st = []
        if d.get("claim_url"): st.append({"text": "Open the claim page", "url": d["claim_url"]})
        if d.get("claim_markers"): st.append({"text": "Claim state on the listing page: " + str(d["claim_markers"]).strip()[:260]})
        out["claim"] = st
    return out


def note_stale(md, direc):
    head = "\n".join(md.splitlines()[:4])
    if _NEG_OUTCOME.search(head): return "note says rejected, dead or 404"
    if _WALL.search(head) and (direc or {}).get("agent_access") == "ok": return "note reports a wall, the Directory row says the agent has access"
    return None


def domain_for(filename):
    n = os.path.basename(filename)
    if not n.endswith(".md") or n.startswith("_") or "_observed" in n or "batch" in n: return None
    n = n[:-3]
    return n[3:] if n.startswith("nm-") else n


def build(vault, dirs, scrub, existing=None):
    """-> (rows, report). rows: [{domain, task, steps, source, stale}]. existing: set of (domain, task) already stored (never overwritten)."""
    existing = existing or set()
    by_dom = {d["domain"]: d for d in dirs}
    notes, unmapped, skipped_files = {}, [], []
    for f in sorted(glob.glob(os.path.join(vault, "*.md"))):
        dom = domain_for(f)
        if dom is None: skipped_files.append(os.path.basename(f)); continue
        if dom not in by_dom: unmapped.append(os.path.basename(f)); continue
        notes.setdefault(dom, []).append((os.path.basename(f), open(f, encoding="utf-8").read()))
    rows, dropped, kept_existing, stale_domains = [], {}, [], {}
    for dom in sorted(by_dom):
        d = by_dom[dom]
        per = {t: [] for t in PB.TASKS}
        srcs = {t: [] for t in PB.TASKS}
        for t, st in field_steps(d).items():
            per[t] += st; srcs[t].append("Directory fields")
        stale = None
        for fn, md in notes.get(dom, []):
            stale = stale or note_stale(md, d)
            for s in sentences(md):
                t = classify(s)
                if t is None: dropped.setdefault("unclassified", []).append((fn, s[:80])); continue
                step, why = make_step(s, scrub)
                if step is None: dropped.setdefault(why, []).append((fn, s[:80])); continue
                if step not in per[t]: per[t].append(step)
                if "vault " + fn not in srcs[t]: srcs[t].append("vault " + fn)
        if stale: stale_domains[dom] = stale
        if stale:
            # A rejected / dead note with no usable step still has to show up (flagged), or the page says "No playbook yet" about a site we tried.
            for fn, md in notes.get(dom, []):
                for s in [x for x in sentences(md) if len(x) >= 25][:3]:
                    t2, why = scrub.clean(re.sub(r"\s+", " ", s.replace("**", "")).strip()[:240])
                    if why or _URL.search(t2): continue
                    per["create"].append({"text": "Old note, not a verified step: " + t2})
                    if "vault " + fn not in srcs["create"]: srcs["create"].append("vault " + fn)
        for t in PB.TASKS:
            if not per[t]: continue
            try:
                clean = PB.validate_steps(per[t])
            except PB.PlaybookError as e:
                dropped.setdefault("row failed validator", []).append((dom + "/" + t, str(e)[:80])); continue
            if (dom, t) in existing: kept_existing.append("%s/%s" % (dom, t)); continue
            rows.append({"domain": dom, "task": t, "steps": clean, "source": "backfill 2026-11-13: " + " + ".join(srcs[t]), "stale": bool(stale), "last_proven_at": None})
    counts = {t: sum(1 for r in rows if r["task"] == t) for t in PB.TASKS}
    rep = {"rows": len(rows), "per_task": counts, "stale_rows": sum(1 for r in rows if r["stale"]), "stale_domains": stale_domains,
           "unmapped_files": unmapped, "skipped_files": skipped_files, "kept_existing": kept_existing,
           "dropped": {k: len(v) for k, v in sorted(dropped.items())}, "dropped_detail": dropped,
           "directories": len(dirs), "directories_with_rows": len({r["domain"] for r in rows})}
    return rows, rep


def load_dirs(db=None):
    if db is not None:
        return db.call("GET", "ce_directories?select=*&order=priority", prefer="return=representation") or []
    base = os.path.join(HERE, "..", "db")
    seen = {}
    for fn in ("directories_seed.json", "directories_hunt_seed.json"):
        try: data = json.load(open(os.path.join(base, fn), encoding="utf-8"))
        except (OSError, ValueError): continue
        for d in data: seen.setdefault(d["domain"], d)
    return list(seen.values())


def main(argv=None, db=None, out=print):
    a = argparse.ArgumentParser(description="One-time backfill of ce_directory_playbooks from the vault build playbooks")
    a.add_argument("--vault", default=VAULT_DEFAULT, required=not VAULT_DEFAULT)
    a.add_argument("--from-db", action="store_true", help="read ce_directories and existing playbooks from the Directory DB (default: db/*.json seeds, no network)")
    a.add_argument("--write", action="store_true", help="upsert the rows (default is a dry run)")
    a.add_argument("--report")
    n = a.parse_args(argv)
    if (n.from_db or n.write) and db is None:
        import directories as D
        db = D.DirDB()
    dirs = load_dirs(db if n.from_db or n.write else None)
    existing = set()
    if db is not None:
        for r in db.call("GET", "ce_directory_playbooks?select=domain,task", prefer="return=representation") or []: existing.add((r["domain"], r["task"]))
    rows, rep = build(n.vault, dirs, Scrubber(), existing)
    out(json.dumps({k: v for k, v in rep.items() if k != "dropped_detail"}, indent=1))
    if n.report:
        with open(n.report, "w", encoding="utf-8") as h: json.dump({"report": rep, "rows": rows}, h, indent=1)
    if not n.write:
        out("DRY RUN: nothing written. %d rows would be written." % len(rows)); return 0
    for r in rows:
        PB.set_playbook(db, r["domain"], r["task"], r["steps"], False, r["source"], None, stale=r["stale"])
    out("written: %d rows" % len(rows)); return 0


if __name__ == "__main__":
    sys.exit(main())
