"""Verify Now page evidence and pre-flight (t_761c9558).

A verify run saves what the Directory showed (a screenshot and the visible text) at sign-in, right after the send click and at the end, under
logs/verify-evidence/<request_id>/, and the scoreboard row links them. The same page read decides the pre-flight: a CAPTCHA or a signed-out page
stops the run at once (agents never solve a CAPTCHA).

  read_page(cdp_url, domains)  read-only Playwright connect_over_cdp. Never clicks, types or navigates. -> dict or None ("cannot see").
  classify(page, signup)       pure: "captcha" | "signed_out" | "signed_in".
  save(rid, label, page)       writes the png and the redacted text; records both in the request's stage file. Never raises.
"""
import os, re, json

LABELS = ("signin", "after_send", "after_send_wait", "end", "arm")
TEXT_MAX = 8000
DIR_NAME = "verify-evidence"

CAPTCHA_TEXT = re.compile(r"(?i)(captcha|verify (that )?you(?:'|\u2019)?re (a )?human|verify you are (a )?human|i(?:'|\u2019)?m not a robot|are you a robot|press (and|&) hold|"
                          r"checking your browser|performing security verification|security check to access|unusual (activity|traffic))")
# a challenge frame, not the invisible badge: recaptcha's anchor frame sits on many signed-in pages, its bframe is the challenge
CAPTCHA_FRAME = re.compile(r"(?i)(recaptcha/(api2|enterprise)/bframe|hcaptcha\.com/captcha/.*challenge|captcha-delivery|challenges\.cloudflare|arkoselabs|funcaptcha|geetest|/captcha(/|\?|$))")
CAPTCHA_BADGE = re.compile(r"(?i)(protected|secured|covered) by (re)?captcha[^.\n]*[.\n]?|this (site|page) is (protected|secured) by[^.\n]*captcha[^.\n]*")
SIGNIN_PATH = re.compile(r"(?i)/(log-?in|sign-?in|sign_in|sign-?up|register)(/|$|\.)")
SIGNIN_TEXT = re.compile(r"(?i)^\W*(log in|sign in)( to (your|continue)| with)\b|\b(log in|sign in) to (your account|continue)\b|\bwelcome back\b.{0,60}\b(log in|sign in)\b")
LOADING = re.compile(r"(?i)\bloading\b")


def evidence_root():
    import sitegate
    return os.path.join(sitegate.logs_dir(), DIR_NAME)


# ---- the page read -------------------------------------------------------------------------------------------------------------------------------
READ_JS = """() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  const pw = Array.from(document.querySelectorAll('input[type=password]')).some(vis);
  const frames = Array.from(document.querySelectorAll('iframe')).map((f) => f.src || '').filter(Boolean);
  return {text: (document.body ? document.body.innerText : '') || '', password: pw, frames: frames};
}"""


def read_page(cdp_url, domains=()):
    """-> {url, text, password, frames, png} of the page on one of `domains` (else the last page), or None when the browser cannot be read.
    Read-only. CE_NO_CDP (set by every test suite) = None, so a test never touches a real Chrome."""
    if os.environ.get("CE_NO_CDP") or not cdp_url: return None
    import verify_dom as VD
    p = None
    try:
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        b = p.chromium.connect_over_cdp(cdp_url)
        pages = [pg for c in b.contexts for pg in c.pages]
        if not pages: return None
        mine = [pg for pg in pages if VD.host_on(pg.url, domains)]
        pg = (mine or pages)[-1]
        got = pg.evaluate(READ_JS) or {}
        try: png = pg.screenshot(type="png")
        except Exception: png = None
        items = []
        for fr in pg.frames:   # the same input collector the landed check uses: a visible code box on this page, any frame
            try: fi = fr.evaluate(VD.COLLECT_JS) or []
            except Exception: continue
            for it in fi: it["frame"] = id(fr); it["page"] = pg.url or ""; items.append(it)
        return {"url": pg.url or "", "text": str(got.get("text") or ""), "password": bool(got.get("password")),
                "frames": list(got.get("frames") or []), "png": png, "on_domain": bool(mine), "code_input": VD.has_code_input(items)}
    except Exception:
        return None
    finally:
        try:
            if p: p.stop()
        except Exception: pass


def classify(page, signup=False):
    """-> "captcha" | "signed_out" | "signed_in". None page -> None (cannot tell). A signup Directory is never 'signed out' (its send IS the signup);
    a CAPTCHA stops either way."""
    if not isinstance(page, dict): return None
    text, url = str(page.get("text") or ""), str(page.get("url") or "")
    if CAPTCHA_TEXT.search(CAPTCHA_BADGE.sub(" ", text[:TEXT_MAX])) or CAPTCHA_FRAME.search(url) or any(CAPTCHA_FRAME.search(str(f)) for f in page.get("frames") or []):
        return "captcha"
    if signup: return "signed_in"
    path = re.sub(r"^https?://[^/]+", "", url.split("?")[0].split("#")[0])
    if SIGNIN_PATH.search(path) or page.get("password") or SIGNIN_TEXT.search(text[:600]):
        return "signed_out"
    return "signed_in"


def is_loading(page):
    return bool(isinstance(page, dict) and LOADING.search(str(page.get("text") or "")))


# ---- redaction + save ----------------------------------------------------------------------------------------------------------------------------
DIGITS6 = re.compile(r"\d{6,}")
PHONE = re.compile(r"\(\d{3}\)\s?\d{3}[\s.-]\d{4}|\b\d{3}[\s.-]\d{3}[\s.-]\d{4}\b")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


def redact(text):
    """Page text is kept for people to read; a typed value must never ride in it: emails, phone numbers and runs of 6+ digits become [x]. Short digit groups
    (a year, a masked phone like (502) ***-0101) stay."""
    t = EMAIL.sub("[x]", str(text or ""))
    return DIGITS6.sub("[x]", PHONE.sub("[x]", t))[:TEXT_MAX]


def save(request_id, label, page):
    """Write NN-<label>.png and NN-<label>.txt under logs/verify-evidence/<request_id>/ and link them in the stage file. -> the relative text path or None.
    A page that could not be read still leaves a .txt saying so (a missing file is not evidence). Never raises."""
    try:
        import verify_scoreboard as SB
        rid = SB._clean_rid(request_id)
        if not rid or label not in LABELS: return None
        d = os.path.join(evidence_root(), rid); os.makedirs(d, exist_ok=True)
        n = len([f for f in os.listdir(d) if f.endswith(".txt")]) + 1
        base = "%02d-%s" % (n, label)
        rel = {}
        if isinstance(page, dict):
            body = "url: %s\n\n%s\n" % (re.sub(r"[?#].*$", "", str(page.get("url") or "")), redact(page.get("text")))
            if page.get("png"):
                with open(os.path.join(d, base + ".png"), "wb") as h: h.write(page["png"])
                rel["png"] = "%s/%s/%s.png" % (DIR_NAME, rid, base)
        else:
            body = "page could not be read (no browser or no CDP)\n"
        with open(os.path.join(d, base + ".txt"), "w", encoding="utf-8") as h: h.write(body)
        rel["txt"] = "%s/%s/%s.txt" % (DIR_NAME, rid, base)
        SB.add_evidence(rid, label, rel)
        return rel["txt"]
    except Exception as e:
        print("verify_evidence: save skipped: %s" % type(e).__name__, file=__import__("sys").stderr, flush=True)
        return None


def _stage(request_id):
    import verify_scoreboard as SB
    try:
        with open(SB._stage_file(SB._clean_rid(request_id)), encoding="utf-8") as h: return json.load(h)
    except Exception:
        return {}


def request_page(portal, request_id, reader=None):
    """-> (page or None, signup bool). Reads the request's tenant Chrome (read-only) at the Directory's domain. Never raises."""
    reader = reader or READER
    try:
        import verify_bridge as B, verify_dom as VD
        req = B.request_row(portal, request_id) or {}
        row = B.verification_row(portal, req.get("citation_verification_id")) or {}
        ent = B.directory_entry(row.get("directory"), req.get("channel")) or {}
        doms = [d for d in [ent.get("domain")] + list(ent.get("aliases") or []) if d]
        cdp = VD.tenant_cdp(req.get("client_id"))
        page = reader(cdp, doms) if cdp else None
    except Exception:
        page = None
    return page, bool(_stage(request_id).get("signup"))


def capture_for(portal, request_id, label, reader=None, only_agent_runs=False):
    """Read the page and save it under `label`. -> the page dict or None. only_agent_runs: skip a request whose agent never started (a swept row has nothing to show)."""
    if only_agent_runs and not _stage(request_id).get("agent_start_at"): return None
    page, _signup = request_page(portal, request_id, reader)
    save(request_id, label, page)
    return page


def short_text(page, limit=280):
    """A one-line, redacted slice of the page for the `fail` evidence argument (the helper's own, not the agent's)."""
    t = re.sub(r"\s+", " ", redact((page or {}).get("text") if isinstance(page, dict) else "")).strip()
    return t[:limit]


READER = read_page   # tests swap this for a mock page (a suite never reads a real Chrome: CE_NO_CDP)
