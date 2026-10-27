"""listings@ approval scan (kanban t_6b1e01ff). Moderated Directories with no account (bbb, loc8nearme, businessyab, discoverourtown) give no permalink at submit;
they mail listings@ when the listing is approved / "now live". This reads those mails and pulls the listing URL out of them, so recheck can read the public page.

Read-only: IMAP EXAMINE + BODY.PEEK (nothing marked read, nothing deleted, nothing sent). Never prints a mail body or the mailbox credentials; the report is
row | mail found (date + subject) | URL.

  python job/mail_scan.py [--days 30] [--directory bbb.org ...]       (needs LISTINGS_IMAP_HOST/PORT/USER/PASSWORD in the environment, like the build runner)

find_approval() is pure: hand it message dicts and it needs no network.
"""
import email, email.utils, html, imaplib, os, re, sys, datetime
import buildqueue as Q
from email.header import decode_header, make_header
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Directory -> the registrable domain its mails and listing URLs carry. These four have no account, so no permalink exists until the approval mail.
SCAN_DIRECTORIES = {
    "bbb.org": "bbb.org",
    "loc8nearme.com": "loc8nearme.com",
    "businessyab.com": "businessyab.com",
    "discoverourtown.com": "discoverourtown.com",
}
APPROVED_RE = re.compile(r"(?i)\b(now live|is live|went live|has been (approved|published|activated|accepted)|was (approved|published|accepted)|(approved|published) and (is )?(now )?(live|visible|active)|"
                         r"listing (is )?(now )?(live|published|active|approved)|congratulations|accreditation is complete|profile is (now )?(live|published|active))\b")
# "will be visible once approved" / "pending approval" are the submit receipt, not an approval.
PENDING_RE = re.compile(r"(?i)(once|until|after|when|if) (it is |it's |your (listing|business) is |we |our team )?(approved|reviewed|verified)|pending (review|approval)|awaiting (review|approval)|will be (reviewed|visible)|under review|we('| a)re reviewing|thank you for (submitting|your submission)")
URL_RE = re.compile(r"""https?://[^\s"'<>)\]]+""")
# Paths that are the way INTO a Directory or a mail action, never the listing itself.
NOT_LISTING_RE = re.compile(r"(?i)/(log-?in|sign-?in|signin|register|sign-?up|unsubscribe|optout|opt-out|preferences|account|dashboard|my-|payment|checkout|add(-|_)?(business|listing)?|get-listed|thank-?you[^/]*|verify|confirm|activate|contact|help|support|privacy|terms|about)([/?#.]|$)|unsubscribe|[?&](unsubscribe|optout)=")
TRACKING_HOSTS = ("list-manage.com", "sendgrid.net", "mandrillapp.com", "mailchimp.com", "click.", "links.", "email.", "track.")


def _brand(domain): return domain.split(".")[0]


def _slug_hits(url, name):
    """How many name words (3+ letters) appear in the URL: a listing URL carries the business name, a footer link does not."""
    words = [w for w in re.findall(r"[a-z0-9]+", (name or "").lower()) if len(w) > 2 and w not in ("and", "the")]
    low = url.lower()
    return sum(1 for w in words if w in low)


def host_ok(url, domain):
    h = (urlparse(url).hostname or "").lower()
    return h == domain or h.endswith("." + domain)


def candidate_urls(text, domain):
    seen = []
    for m in URL_RE.finditer(html.unescape(text or "")):
        u = m.group(0).rstrip(".,;:!?)")
        if u not in seen and host_ok(u, domain) and not NOT_LISTING_RE.search(urlparse(u).path + ("?" + urlparse(u).query if urlparse(u).query else "")):
            if (urlparse(u).path or "/").strip("/") == "": continue   # the bare homepage is not a listing
            seen.append(u)
    return seen


def gate_ok(directory, url):
    """The permalink gate (permalink.is_permalink + listing.is_permalink): True only for a record page of the Directory. A search, category or entry-form URL is refused."""
    import permalink as PL, listing as L
    return bool(PL.is_permalink(directory, url)[0] and L.is_permalink(directory, url))


def is_approval(subject, body):
    """True for an approval / 'now live' mail. A mail that only says the listing WILL be visible once approved is the submit receipt."""
    s, b = subject or "", body or ""
    if APPROVED_RE.search(s): return True
    if not APPROVED_RE.search(b): return False
    return not (PENDING_RE.search(s) or (PENDING_RE.search(b) and not APPROVED_RE.search(re.sub(PENDING_RE, " ", b))))


def mail_is_from(msg, domain):
    b = _brand(domain)
    frm = (msg.get("from") or "").lower()
    return b in frm or any(host_ok(u, domain) for u in URL_RE.findall(msg.get("body") or "")[:40])


def find_approval(directory, messages, name=None):
    """-> {"uid", "date", "subject", "url"} for the NEWEST approval mail of `directory` that carries a listing URL on its domain, else None. Pure.
    messages: dicts with uid, from, subject, body (text or html, unescaped), date (iso, optional). The URL with the most business-name words wins, then the first."""
    domain = SCAN_DIRECTORIES.get(directory)
    if not domain: return None
    mine = [m for m in messages if mail_is_from(m, domain) and is_approval(m.get("subject"), m.get("body"))]
    for m in sorted(mine, key=lambda x: (x.get("date") or "", x.get("uid") or 0), reverse=True):
        urls = [u for u in candidate_urls(m.get("body"), domain) if gate_ok(directory, u)]   # t_bbc32230: a search / category / non-listing URL never leaves the scan
        if not urls: continue
        best = max(urls, key=lambda u: (_slug_hits(u, name), -urls.index(u)))
        return {"uid": m.get("uid"), "date": m.get("date"), "subject": (m.get("subject") or "")[:120], "url": best}
    return None


# ---- t_2d15878c: password-reset mails (bbb, businessyab). The link is printed to the terminal ONLY: never written to the repo, the queue or a note.
RESET_SUBJECT_RE = re.compile(r"(?i)(reset|forgot|recover|change)[^a-z]{0,3}(your )?(password|login|account)|password (reset|recovery|change)")
RESET_PATH_RE = re.compile(r"(?i)(reset|recover|forgot|new[-_]?password|change[-_]?password|set[-_]?password|password)[-_/a-z]*([/?=#&]|$)|[?&](token|code|key|hash)=")
RESET_CODE_RE = re.compile(r"(?i)(?:code|pin|otp)[^0-9a-z]{0,20}\b(\d{4,8})\b|\b(\d{6})\b")   # a labelled code, else a lone 6-digit number in a reset mail


def reset_urls(text, domain):
    out = []
    for m in URL_RE.finditer(html.unescape(text or "")):
        u = m.group(0).rstrip(".,;:!?)")
        p = urlparse(u)
        if u in out or not host_ok(u, domain): continue
        if re.search(r"(?i)unsubscribe|/privacy|/terms", p.path): continue
        if RESET_PATH_RE.search(p.path + ("?" + p.query if p.query else "")): out.append(u)
    return out


def find_reset(directory, messages):
    """-> {"uid","date","subject","url","code"} for the NEWEST password-reset mail from `directory` (a link on its own domain, and/or a numeric code), else None. Pure.
    bbb says it sends a CODE; businessyab says instructions: either is returned. The caller prints it; nothing here stores it."""
    domain = SCAN_DIRECTORIES.get(directory)
    if not domain: return None
    for m in sorted([x for x in messages if mail_is_from(x, domain)], key=lambda x: (x.get("date") or "", x.get("uid") or 0), reverse=True):
        subj, body = m.get("subject") or "", m.get("body") or ""
        if not (RESET_SUBJECT_RE.search(subj) or re.search(r"(?i)reset your password|password reset", body)): continue
        urls = reset_urls(body, domain)
        cm = RESET_CODE_RE.search(re.sub(r"https?://\S+", " ", html.unescape(body)))
        code = (cm.group(1) or cm.group(2)) if cm else None
        if urls or code: return {"uid": m.get("uid"), "date": m.get("date"), "subject": subj[:120], "url": urls[0] if urls else None, "code": code}
    return None


def reset_main(directories, days, messages=None, out=print):
    """`--reset-link`: print the newest reset link / code per Directory to stdout. Read-only mail access. Exit 0 found, 1 none, 2 mailbox unreadable."""
    try: msgs = messages if messages is not None else read_messages(days=days)
    except Exception as e:
        print("MAILBOX NOT READ: %s" % (type(e).__name__ + ": " + str(e)[:100]), file=sys.stderr); return 2
    found = 0
    for d in directories:
        hit = find_reset(d, msgs)
        if not hit: out("%s | no password-reset mail" % d); continue
        found += 1
        out("%s | %s %s | link: %s | code: %s" % (d, hit["date"], hit["subject"], hit["url"] or "-", hit["code"] or "-"))
    return 0 if found else 1


def _text_of(msg):
    out = []
    for part in msg.walk():
        if part.get_content_type() not in ("text/plain", "text/html"): continue
        raw = part.get_payload(decode=True)
        if raw: out.append(html.unescape(raw.decode(part.get_content_charset() or "utf-8", "replace")))
    return "\n".join(out)


def read_messages(env=None, imap_cls=imaplib.IMAP4_SSL, days=30, limit=300, vault=None):
    """Recent mail from listings@ as dicts. Read-only (EXAMINE + PEEK). Raises PlaybookError when LISTINGS_IMAP_* is not set."""
    sys.path.insert(0, os.path.join(HERE, "playbooks"))
    import hotfrog as H
    cfg = H.mail_env(env, vault)   # t_d2f75685: env empty -> the vault item (password in memory only); unreadable -> MailboxNotRead "MAILBOX NOT READ"
    since = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%d-%b-%Y")
    m = imap_cls(cfg["host"], int(cfg["port"]))
    out = []
    try:
        m.login(cfg["user"], cfg["password"]); m.select("INBOX", readonly=True)
        typ, data = m.uid("SEARCH", None, "SINCE", since)
        for uid in sorted((int(u) for u in (data[0] or b"").split()), reverse=True)[:limit]:
            typ, d = m.uid("FETCH", str(uid), "(BODY.PEEK[])")
            raw = next((x[1] for x in d if isinstance(x, tuple)), None)
            if raw is None: continue
            msg = email.message_from_bytes(raw)
            try: dt = email.utils.parsedate_to_datetime(msg.get("Date")).strftime("%Y-%m-%dT%H:%M")
            except Exception: dt = ""
            out.append({"uid": uid, "from": str(make_header(decode_header(msg.get("From", "")))), "subject": str(make_header(decode_header(msg.get("Subject", "")))),
                        "date": dt, "body": _text_of(msg)})
    finally:
        try: m.logout()
        except Exception: pass
    return out


class MailScanner:
    """recheck's mail source: reads the mailbox ONCE (lazily), then answers find(directory) from memory. A mailbox that cannot be read is reported once and
    answers None, so a recheck run never fails on mail. messages= injects fixtures."""
    def __init__(self, messages=None, reader=None, name=None, log=print):
        self._msgs, self._reader, self.name, self.log, self.error = messages, reader or read_messages, name, log, None

    def messages(self):
        if self._msgs is None:
            try: self._msgs = self._reader()
            except Exception as e:
                self._msgs, self.error = [], type(e).__name__ + ": " + str(e)[:100]
                self.log("mail scan unavailable: %s" % self.error)
        return self._msgs

    def find(self, directory, name=None):
        return find_approval(directory, self.messages(), name or self.name)


def report(rows, scanner):
    """rows: [(row_id, directory)] -> lines 'row | mail found | URL'. Names and URLs only, no mail text."""
    lines = ["%-26s | %-60s | %s" % ("row", "mail found", "url")]
    for rid, d in rows:
        hit = scanner.find(d)
        if not hit and scanner.error:   # an unreadable mailbox is NOT "no approval mail": say so
            lines.append("%-26s | %-60s | %s" % (rid, "MAILBOX NOT READ (%s)" % scanner.error[:30], "-")); continue
        tag = " [mail-only: this scan is its only status path]" if Q.is_mail_only(d) else ""   # t_03a74bae
        lines.append("%-26s | %-60s | %s%s" % (rid, ("%s  %s" % (hit["date"], hit["subject"]))[:60] if hit else "none", hit["url"] if hit else "-", tag))
    return "\n".join(lines)


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="Read listings@ for approval / now-live mails of the moderated, account-less Directories (read-only)")
    a.add_argument("--days", type=int, default=30)
    a.add_argument("--directory", action="append", default=None)
    a.add_argument("--queue", default=None)
    a.add_argument("--reset-link", action="store_true", help="print the newest password-reset link / code from bbb / businessyab mail (terminal only; never stored)")
    n = a.parse_args(argv)
    if n.reset_link: return reset_main(n.directory or ["bbb.org", "businessyab.com"], n.days)
    import buildqueue as Q
    wanted = set(n.directory) if n.directory else set(SCAN_DIRECTORIES)
    import datetime
    today = datetime.date.today().isoformat()
    rows = [(r["id"], r["directory"]) for r in Q.load_all_rows(n.queue) if r.get("directory") in wanted and r.get("state") in ("submitted", "pending-verify", "found", "created-unlisted")
            and not Q.not_due(r, today)]   # t_d2f75685: recheck_due in the future = skip
    from cfg import IDENT
    sc = MailScanner(reader=lambda: read_messages(days=n.days), name=IDENT["BIZ"]["SCC"]["name"])
    print(report(rows, sc))
    if sc.error and rows: print("MAILBOX NOT READ: %s" % sc.error, file=sys.stderr)   # t_d2f75685: never read as "no approval mail"
    return 2 if sc.error and rows else 0


if __name__ == "__main__":
    sys.exit(main())
