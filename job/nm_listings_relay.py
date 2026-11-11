#!/usr/bin/env python3
"""No-agent relay: mail sent to listings@nackemedia.com -> a seat-readable file (kanban t_04751f6a).

listings@nackemedia.com is a Gmail alias on mike@nackemedia.com, so the seat's IMAP (listings@seniorcaresolutions.co) cannot see it. This reads Gmail
through `gog` with ONE pinned query, keeps only messages actually addressed to listings@nackemedia.com, pulls out verify links and codes, and appends
{id, from, subject, received, links, codes} to %LOCALAPPDATA%/citation-engine/mail/nm-listings.jsonl. `mail_scan.py --mailbox nm-relay` reads that file.

Scope guard: the query must start with `to:listings@nackemedia.com` and may not broaden (OR, negation, braces, parentheses, from:/in:/label:/...). Anything
else exits 2 before gog is called. Read-only: only `gmail search` and `gmail thread get` are ever built; nothing is sent, forwarded, labelled or deleted.
Nothing from the rest of the inbox is read into the file.

  python nm_listings_relay.py [--dry] [--query 'to:listings@nackemedia.com newer_than:2d'] [--out PATH]

--dry prints id | from | subject | link/code COUNTS only (never a link or code) and writes nothing. Exit 0 ok, 2 refused/gog failed.
"""
import base64, datetime, email.utils, html, json, os, re, subprocess, sys

ACCOUNT = "mike@nackemedia.com"
TARGET = "listings@nackemedia.com"
DEFAULT_QUERY = "to:listings@nackemedia.com newer_than:2d"
ALLOWED_TOKEN = re.compile(r"^(newer_than:\d{1,2}d|older_than:\d{1,2}d)$")
TO_HEADERS = ("to", "cc", "bcc", "delivered-to", "x-original-to", "envelope-to")
READ_VERBS = (("gmail", "search"), ("gmail", "thread", "get"))
URL_RE = re.compile(r"""https?://[^\s"'<>)\]]+""")
NOISE_RE = re.compile(r"(?i)unsubscribe|optout|opt-out|/privacy|/terms|\.(png|jpe?g|gif|svg|css|ico)(\?|$)|list-manage\.com/(track|unsub)|mailto:")
CODE_RE = re.compile(r"(?i)(?:code|pin|otp)[^0-9a-z]{0,20}\b(\d{4,8})\b|\b(\d{6})\b")   # same rule as mail_scan.RESET_CODE_RE


def default_out():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(base, "citation-engine", "mail", "nm-listings.jsonl")


class QueryRefused(Exception):
    pass


def check_query(q):
    """Raise QueryRefused unless q is exactly `to:listings@nackemedia.com` plus optional newer_than:/older_than: tokens."""
    toks = (q or "").split()
    if not toks or toks[0].lower() != "to:" + TARGET:
        raise QueryRefused("query must start with to:%s" % TARGET)
    for t in toks[1:]:
        if not ALLOWED_TOKEN.match(t):
            raise QueryRefused("query token not allowed: %r" % t[:40])
    return " ".join(toks)


def gog_argv(*verb_and_args):
    if tuple(verb_and_args[:2]) != READ_VERBS[0] and tuple(verb_and_args[:3]) != READ_VERBS[1]:
        raise QueryRefused("gog verb not allowed: %s" % " ".join(verb_and_args[:3]))
    return ["gog", "-a", ACCOUNT, *verb_and_args]


def run_gog(argv):
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError("gog rc=%s: %s" % (r.returncode, (r.stderr or r.stdout).strip()[:200]))
    return json.loads(r.stdout) if r.stdout.strip() else {}


def _hdrs(m):
    out = {}
    for h in (m.get("payload") or {}).get("headers", []):
        out.setdefault(h.get("name", "").lower(), []).append(h.get("value", ""))
    return out


def addressed_to_target(m):
    """True only when the message itself names listings@nackemedia.com in a recipient header. The query is the first guard, this is the second."""
    hs = _hdrs(m)
    for name in TO_HEADERS:
        for _n, addr in email.utils.getaddresses(hs.get(name, [])):
            if (addr or "").strip().lower() == TARGET:
                return True
    return False


def _body_text(part):
    out = []
    data = (part.get("body") or {}).get("data")
    if data and part.get("mimeType") in ("text/plain", "text/html"):
        try:
            out.append(html.unescape(base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")))
        except Exception:
            pass
    for p in part.get("parts", []) or []:
        out.append(_body_text(p))
    return "\n".join(x for x in out if x)


def extract(body):
    links = []
    for mt in URL_RE.finditer(body or ""):
        u = mt.group(0).rstrip(".,;:!?)")
        if u not in links and not NOISE_RE.search(u):
            links.append(u)
    plain = re.sub(r"https?://\S+", " ", body or "")
    codes = []
    for mt in CODE_RE.finditer(plain):
        c = mt.group(1) or mt.group(2)
        if c and c not in codes:
            codes.append(c)
    return links[:15], codes[:5]


def record(m):
    hs = _hdrs(m)
    try:
        ms = int(m.get("internalDate"))
        received = datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        received = ""
    links, codes = extract(_body_text(m.get("payload") or {}))
    return {"id": m["id"], "from": (hs.get("from") or [""])[0], "subject": (hs.get("subject") or [""])[0], "received": received, "links": links, "codes": codes}


def collect(query, gog=run_gog, max_threads=30):
    """-> (records, skipped): records of messages addressed to listings@, skipped = count dropped by the To re-check / DRAFT / SENT."""
    q = check_query(query)
    res = gog(gog_argv("gmail", "search", q, "-j", "--max=%d" % max_threads))
    recs, skipped = [], 0
    for t in res.get("threads", []):
        th = gog(gog_argv("gmail", "thread", "get", t["id"], "-j"))
        th = th.get("thread", th)
        for m in th.get("messages", []):
            lids = m.get("labelIds", [])
            if "DRAFT" in lids or "SENT" in lids or not addressed_to_target(m):
                skipped += 1
                continue
            recs.append(record(m))
    return recs, skipped


def known_ids(path):
    ids = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    ids.add(json.loads(line)["id"])
                except (ValueError, KeyError):
                    pass
    return ids


def append_new(path, recs):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    seen = known_ids(path)
    new = [r for r in recs if r["id"] not in seen]
    if new:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            for r in new:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return new


def main(argv=None, gog=run_gog, out=print):
    import argparse
    a = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    a.add_argument("--dry", action="store_true")
    a.add_argument("--query", default=DEFAULT_QUERY)
    a.add_argument("--out", default=None)
    n = a.parse_args(argv)
    try:
        recs, skipped = collect(n.query, gog)
    except QueryRefused as e:
        print("REFUSED: %s" % e, file=sys.stderr)
        return 2
    except Exception as e:
        print("RELAY FAILED: %s: %s" % (type(e).__name__, str(e)[:200]), file=sys.stderr)
        return 2
    path = n.out or default_out()
    if n.dry:
        out("nm-listings relay DRY: query=%r account=%s to-listings messages=%d dropped=%d (writes nothing)" % (check_query(n.query), ACCOUNT, len(recs), skipped))
        for r in recs:
            out("  %s | %s | %s | %s | links=%d codes=%d" % (r["id"], r["received"], r["from"][:50], r["subject"][:60], len(r["links"]), len(r["codes"])))
        return 0
    new = append_new(path, recs)
    if new:
        out("nm-listings relay: %d new message(s) -> %s" % (len(new), path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
