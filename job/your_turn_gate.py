"""Your-turn gate (t_e2db63f0, Mike 2026-10-30). A citation_verification row (the client's Your turn page) may be written ONLY when an agent has
opened the live verify step THIS CYCLE and recorded what it saw: the verify type observed, a screenshot, and any price shown. Even then it is refused if
the Directory is paid, a dead/redirect domain, or email-verifiable (an email verify is an agent job through listings@, never the client's).

Pure: no network, no browser. `check_your_turn` returns a list of refusal strings ([] = allowed).
"""
import datetime, os, re
from urllib.parse import urlsplit

CYCLE_DAYS = 7   # "this cycle": the observation is at most a week old
EMAIL_TYPES = ("email", "email-link", "email-code", "mailbox-link")
FREE_WORDS = ("none", "free", "0", "0.00", "$0", "$0.00", "no charge")
PAID_RE = re.compile(r"\$\s*\d|\bpaid\b|\bper (month|year)\b|/\s*(mo|yr)\b|\bpremium\b|\bupgrade to\b", re.I)


def _host(u):
    h = (urlsplit(str(u or "")).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def price_problem(price_seen):
    """None when the price shown is explicitly free; otherwise the reason."""
    if price_seen is None or str(price_seen).strip() == "": return "price_seen missing (record 'none' if the verify step showed no price)"
    if isinstance(price_seen, (int, float)) and not isinstance(price_seen, bool):
        return None if price_seen == 0 else "paid: price seen %s" % price_seen
    s = str(price_seen).strip().lower()
    if s in FREE_WORDS: return None
    if PAID_RE.search(s): return "paid: price seen %r (we build no paid listings)" % price_seen
    return "price_seen %r is not a number or 'none'" % price_seen


def check_your_turn(directory, verify_type, observation, dir_row=None, today=None):
    bad = []
    if not isinstance(observation, dict) or not observation:
        return ["no live observation: an agent must open the live verify step this cycle and record observed_type, screenshot, price_seen"]
    day = datetime.date.fromisoformat(today) if today else datetime.date.today()
    ot = str(observation.get("observed_type") or "").strip().lower()
    if not ot: bad.append("observed_type missing")
    elif ot in EMAIL_TYPES: bad.append("email-verifiable (%s): an agent job through listings@, not the client's turn" % ot)
    elif verify_type and ot != verify_type: bad.append("observed_type %r != parked verify_type %r" % (ot, verify_type))
    shot = observation.get("screenshot")
    if not shot or not os.path.isfile(str(shot)) or os.path.getsize(str(shot)) == 0: bad.append("screenshot missing or empty")
    p = price_problem(observation.get("price_seen"))
    if p: bad.append(p)
    try:
        seen = datetime.date.fromisoformat(str(observation.get("observed_at"))[:10])
        if seen > day or (day - seen).days > CYCLE_DAYS: bad.append("observation is not from this cycle (observed_at %s, today %s)" % (seen, day))
    except Exception:
        bad.append("observed_at missing or not YYYY-MM-DD")
    url = str(observation.get("url") or "")
    if not url.startswith("https://") or "@" in urlsplit(url).netloc: bad.append("url must be the https verify-step page, no userinfo")
    final = observation.get("final_url")
    if final and directory and _host(final) and _host(final) != directory.lower().removeprefix("www.") and not _host(final).endswith("." + directory.lower()):
        bad.append("redirect/dead domain: %s went to %s" % (directory, _host(final)))
    if isinstance(dir_row, dict):
        if dir_row.get("dead"): bad.append("Directory DB marks %s dead (%s)" % (directory, dir_row.get("dead_reason") or "no reason"))
        if dir_row.get("cost") == "paid": bad.append("Directory DB marks %s paid" % directory)
        vm = dir_row.get("verification_methods")
        if isinstance(vm, str): vm = [x for x in re.split(r"[\s,{}\[\]\"']+", vm) if x]
        em = [m for m in (vm or []) if str(m).strip().lower() in EMAIL_TYPES]
        if em: bad.append("email-verifiable (Directory DB lists %s for %s): an agent job through listings@, even if the site also offers sms or phone" % (",".join(map(str, em)), directory))
    return bad
