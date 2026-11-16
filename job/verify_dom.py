"""Verify Now DOM landed check (t_00a83602). `step_sent` records code_sent only when the tenant's Chrome shows a visible code input, not just when
the agent's quoted text reads like a landed send (a free-text gate cannot tell "Press the button to send your verification code" from a landed page).

Two halves, so tests never need a browser:
  snapshot_inputs(cdp_url)  read-only Playwright connect_over_cdp; every <input> in every frame of every page -> list of plain dicts. Never clicks,
                            types or navigates. Any problem -> None ("cannot see"), never an exception.
  has_code_input(snapshot)  the selector rule (pure Python over those dicts).
  check(cdp_url, ...)       -> True (code input seen) | False (page seen, no code input) | None (cannot see). Re-reads a no-input page a few times.
"""
import os, re, time

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
NAMED = re.compile(r"(?i)(code|otp|verif)")
NOT_A_CODE = re.compile(r"(?i)(zip|postal|phone|\btel|promo|coupon|referral|invite|country|area|card|cvc|cvv|ssn|year|\bexp)")
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
    return i.get("inputmode") in ("numeric", "decimal") and m is not None and ROW_MIN <= m <= ROW_MAX and not NOT_A_CODE.search(_label(i))


def rule_named_code(i, row=None):
    return bool(NAMED.search(_label(i))) and not NOT_A_CODE.search(_label(i))


def rule_single_char_row(i, row=None):
    """4-8 usable inputs under one parent, each maxlength 1 (the six-box OTP widget)."""
    return _maxlen(i) == 1 and row is not None and ROW_MIN <= row <= ROW_MAX


RULES = {"one_time_code": rule_one_time_code, "numeric_maxlen": rule_numeric_maxlen, "named_code": rule_named_code, "single_char_row": rule_single_char_row}


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
                for fr in pg.frames:
                    try: items = fr.evaluate(COLLECT_JS)
                    except Exception: continue
                    n += 1
                    for it in items or []:
                        it["frame"] = id(fr); out.append(it)
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


def check(cdp_url, snap=snapshot_inputs, sleep=time.sleep, reads=READS, gap=READ_GAP_S, rules=None):
    """True: a visible code input is on the page. False: the page was read `reads` times and never showed one. None: the browser cannot be read."""
    if not cdp_url: return None
    for n in range(reads):
        s = snap(cdp_url)
        if s is None: return None
        if has_code_input(s, rules): return True
        if n + 1 < reads: sleep(gap)
    return False
