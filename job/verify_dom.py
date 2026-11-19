"""Verify Now DOM landed check (t_00a83602). `step_sent` records code_sent only when the tenant's Chrome shows a visible code input, not just when
the agent's quoted text reads like a landed send (a free-text gate cannot tell "Press the button to send your verification code" from a landed page).

Two halves, so tests never need a browser:
  snapshot_inputs(cdp_url)  read-only Playwright connect_over_cdp; every <input> in every frame of every page -> list of plain dicts. Never clicks,
                            types or navigates. Any problem -> None ("cannot see"), never an exception.
  has_code_input(snapshot)  the selector rule (pure Python over those dicts).
  check(cdp_url, ...)       -> True (code input seen) | False (page seen, no code input) | None (cannot see). Re-reads a no-input page a few times.
"""
import os, re, time
from urllib.parse import urlparse

# the fields the collector returns for each input (all strings/bools/ints; no value, no page text)
COLLECT_JS = """() => {
  const ids = new Map(); let n = 0;
  const key = (el) => { const p = el.parentElement; if (!p) return 0; if (!ids.has(p)) ids.set(p, ++n); return ids.get(p); };
  return Array.from(document.querySelectorAll('input')).map((el) => {
    const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    const visible = r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity || '1') > 0;
    return {type: (el.getAttribute('type') || 'text').toLowerCase(), autocomplete: (el.getAttribute('autocomplete') || '').toLowerCase(),
            inputmode: (el.getAttribute('inputmode') || '').toLowerCase(), maxlength: el.getAttribute('maxlength'),
            name: el.getAttribute('name') || '', id: el.id || '', aria: el.getAttribute('aria-label') || '', placeholder: el.getAttribute('placeholder') || '',
            visible: visible, disabled: !!el.disabled, readonly: !!el.readOnly, group: key(el)};
  });
}"""

TEXTY_TYPES = ("text", "tel", "number", "password", "search", "")
# t_00a83602 review round 1: a token allowlist, not a substring match. A label is split on case changes, _ - spaces and punctuation.
OTP_WORDS = frozenset(("otp", "totp", "passcode"))
CODE_PARTNERS = frozenset(("verification", "verify", "security", "confirmation", "confirm", "sms", "auth", "authentication", "time", "onetime"))
COMPOUNDS = frozenset(("verificationcode", "verifycode", "securitycode", "smscode", "authcode", "confirmationcode", "confirmcode", "otpcode", "onetimecode"))
SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|[^A-Za-z0-9]+")
NOT_A_CODE = re.compile(r"(?i)(zip|postal|phone|\btel|promo|coupon|referral|invite|country|area|card|cvc|cvv|ssn|year|\bexp)")
# t_00a83602 review round 2 (Nate, comment 787): address/category/count fields that are numeric with a short maxlength, and the human labels of a real code box.
NOT_CODE_TOKENS = frozenset(("post", "postcode", "employee", "employees", "founded", "street", "house", "suite", "unit", "apt", "quantity", "qty", "amount",
                             "price", "age", "dob", "birth", "naics", "sic"))
PHONEISH = frozenset(("phone", "mobile", "cell", "tel", "telephone", "email", "mail"))
FILLER_BEFORE = frozenset(("enter", "type", "input", "the", "your", "a", "an", "please", "digit", "digits", "4", "5", "6", "7", "8"))
FILLER_AFTER = frozenset(("here", "below", "we", "sent", "texted", "emailed", "you", "to", "your", "by", "via", "phone", "mobile", "number", "email", "sms",
                          "text", "message"))
ROW_MIN, ROW_MAX = 4, 8
READS, READ_GAP_S = 3, 1.0


def _maxlen(i):
    try: return int(str(i.get("maxlength")).strip())
    except (TypeError, ValueError): return None


def _label(i): return " ".join(str(i.get(k) or "") for k in ("name", "id", "aria", "placeholder"))


def _usable(i):
    """A real, reachable, typeable text-ish box: visible, enabled, not read-only."""
    return bool(i.get("visible")) and not i.get("disabled") and not i.get("readonly") and (i.get("type") or "text") in TEXTY_TYPES


def rule_one_time_code(i, row=None):
    return str(i.get("autocomplete") or "").split()[-1:] == ["one-time-code"]


def rule_numeric_maxlen(i, row=None):
    m = _maxlen(i)
    return (i.get("inputmode") in ("numeric", "decimal") and m is not None and ROW_MIN <= m <= ROW_MAX and not NOT_A_CODE.search(_label(i))
            and "captcha" not in _label(i).lower() and not NOT_CODE_TOKENS.intersection(_tokens(_label(i))))


def _tokens(text):
    return [t.lower() for t in SPLIT.split(str(text or "")) if t]


def _field_is_code(text, exact_ok):
    toks = _tokens(text)
    if any(t in OTP_WORDS or t in COMPOUNDS for t in toks): return True
    if exact_ok and toks == ["code"]: return True
    return any(t == "code" and ((k > 0 and toks[k - 1] in CODE_PARTNERS) or (k + 1 < len(toks) and toks[k + 1] in CODE_PARTNERS)) for k, t in enumerate(toks))


def _human_code(text):
    """aria/placeholder only: a bare `code` with only filler around it."""
    toks = _tokens(text)
    if "code" not in toks: return False
    k = toks.index("code")
    return all(t in FILLER_BEFORE for t in toks[:k]) and all(t in FILLER_AFTER for t in toks[k + 1:])


def _phone_first(text):
    """aria/placeholder only: a phone/email word before any code word = the phone (or email) field."""
    for t in _tokens(text):
        if t in OTP_WORDS or t in COMPOUNDS or t == "code": return False
        if t in PHONEISH: return True
    return False


def _name_not_code(i):
    """t_8f631f1b: a name/id naming a promo/coupon/referral/invite/zip/phone field is not the code box, whatever its placeholder says. A name/id that is itself
    a code field (phoneVerificationCode, otp) is exempt, so it still records."""
    return any(NOT_A_CODE.search(str(i.get(k) or "")) and not _field_is_code(i.get(k), True) for k in ("name", "id"))


def rule_named_code(i, row=None):
    """name/id/aria-label/placeholder reads as a code field: otp/totp/passcode, `code` next to verification/verify/security/confirmation/sms/auth/one-time,
    or a name/id that is exactly `code`. Never with `captcha` in the label; a password box only with otp/passcode."""
    label = _label(i)
    if "captcha" in label.lower(): return False
    if (i.get("type") or "") == "password" and not any(t in ("otp", "totp", "passcode") for t in _tokens(label)): return False
    if any(_phone_first(i.get(k)) for k in ("aria", "placeholder")): return False
    if _name_not_code(i): return False
    return (any(_field_is_code(i.get(k), k in ("name", "id")) for k in ("name", "id", "aria", "placeholder"))
            or any(_human_code(i.get(k)) for k in ("aria", "placeholder")))


def rule_single_char_row(i, row=None):
    """4-8 usable inputs under one parent, each maxlength 1 (the six-box OTP widget)."""
    return _maxlen(i) == 1 and row is not None and ROW_MIN <= row <= ROW_MAX


RULES = {"one_time_code": rule_one_time_code, "numeric_maxlen": rule_numeric_maxlen, "named_code": rule_named_code, "single_char_row": rule_single_char_row}


def host_on(url, domains):
    """True when the URL's host is one of `domains` or a subdomain of one."""
    try: h = (urlparse(str(url or "")).hostname or "").lower().rstrip(".")
    except ValueError: return False
    return bool(h) and any(h == d or h.endswith("." + d) for d in (str(x).lower().strip(".") for x in (domains or ())) if d)


def scope(snapshot, domains):
    """-> (items on pages of `domains`, pages seen, pages matched). Items with no page url never match."""
    pages = {i.get("page") for i in (snapshot or []) if isinstance(i, dict)}
    mine = {p for p in pages if host_on(p, domains)}
    return [i for i in (snapshot or []) if isinstance(i, dict) and i.get("page") in mine], len(pages), len(mine)


def has_code_input(snapshot, rules=None):
    """True when the snapshot (list of input dicts) holds a visible, enabled code input by any rule."""
    rules = RULES if rules is None else rules
    usable = [i for i in (snapshot or []) if isinstance(i, dict) and _usable(i)]
    rows = {}
    for i in usable:
        if _maxlen(i) == 1: rows[(i.get("frame"), i.get("group"))] = rows.get((i.get("frame"), i.get("group")), 0) + 1
    return any(fn(i, rows.get((i.get("frame"), i.get("group")))) for i in usable for fn in rules.values())


def snapshot_inputs(cdp_url):
    """Every input of every frame of every page in the browser at cdp_url -> list of dicts, or None when the browser cannot be read."""
    if os.environ.get("CE_NO_CDP"): return None
    p = None
    try:
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        b = p.chromium.connect_over_cdp(cdp_url)
        out, n = [], 0
        for c in b.contexts:
            for pg in c.pages:
                pu = pg.url or ""
                for fr in pg.frames:
                    try: items = fr.evaluate(COLLECT_JS)
                    except Exception: continue
                    n += 1
                    out.append({"page": pu, "frame": id(fr)})   # a page with no inputs still counts as seen
                    for it in items or []:
                        it["frame"] = id(fr); it["page"] = pu; out.append(it)
        return out if n else None
    except Exception:
        return None
    finally:
        try:
            if p: p.stop()
        except Exception: pass


def tenant_cdp(client_id):
    """The tenant's browser CDP URL from the request's client id, or None (unknown client, no browser configured)."""
    try:
        import portal as P
        import verify_send as S
        biz = next((k for k, v in P.ALLOWED.items() if v == client_id), None)
        return S.tenant_browser(biz)[2] if biz else None
    except Exception:
        return None


LAST = {"pages": 0, "matched": 0, "shapes": ""}   # of the last check(): pages seen, pages on the Directory's domain (for the refusal log)


def shapes(items, n=5):
    """Attributes only (never values): up to n usable inputs as type/inputmode/maxlength/autocomplete/name|id|aria|placeholder, for the refusal log."""
    out = []
    for i in items or []:
        if isinstance(i, dict) and _usable(i):
            out.append("%s/%s/%s/%s/%s" % (i.get("type") or "text", i.get("inputmode") or "-", i.get("maxlength") if i.get("maxlength") is not None else "-",
                                          i.get("autocomplete") or "-", "|".join(str(i.get(k) or "-")[:40] for k in ("name", "id", "aria", "placeholder"))))
        if len(out) >= n: break
    return "; ".join(out)


def check(cdp_url, domains=(), snap=snapshot_inputs, sleep=time.sleep, reads=READS, gap=READ_GAP_S, rules=None):
    """True: a visible code input is on a page of `domains`. False: those pages were read `reads` times and never showed one (or no page is on the
    domain). None: the browser cannot be read. Pages of other hosts are never counted."""
    if not cdp_url: return None
    for n in range(reads):
        s = snap(cdp_url)
        if s is None: return None
        mine, LAST["pages"], LAST["matched"] = scope(s, domains)
        LAST["shapes"] = shapes(mine)
        if has_code_input(mine, rules): return True
        if n + 1 < reads: sleep(gap)
    return False
