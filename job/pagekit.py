"""Page helpers shared by the scripted builds (t_560dd259). Pure functions over a Playwright-style page; every edge is injectable, nothing here touches the network on import.

  clear_ads(page)         remove `ins` ad nodes, google_ads / doubleclick / adsbygoogle iframes and the #google_vignette overlay BEFORE a click. Returns how many nodes went.
  wait_out_wall(page)     wait (never solve) for a Cloudflare / Turnstile interstitial that clears by itself in the real Chrome.
  set_file(page, sel, p)  attach a local file to an <input type=file> over CDP (DOM.setFileInputFiles), no file dialog.
  ensure_logo()           the stored local copy of SCC's own published logo (md5 prefix 72900a7f), copied from the vault source if missing.
  redact(text)            mask password-looking values in page text (find-us-here dashboards print the account password in plain text).
"""
import hashlib, os, re, shutil

LOGO_URL = "https://seniorcaresolutions.co/wp-content/uploads/2023/11/senior-care-consulting-logo.png"
LOGO_MD5_PREFIX = "72900a7f"
LOGO_PATH = os.environ.get("CE_LOGO_PATH") or os.path.expandvars("%LOCALAPPDATA%/citation-engine/assets/scc-logo.png")
LOGO_SOURCE = os.environ.get("CE_LOGO_SOURCE")   # vault copy of the same file; the path is not stored in the repo (set it only to re-create the local copy)

WALL_RE = re.compile(r"(?i)just a moment|performing a quick security check|checking your browser|verify you are (a )?human|security verification")

CLEAR_ADS_JS = """() => {
  let n = 0;
  const kill = e => { try { e.remove(); n++; } catch (x) {} };
  document.querySelectorAll('ins, ins.adsbygoogle, [id^="google_ads"], [id^="aswift"], iframe[src*="googlesyndication"], iframe[src*="doubleclick"], iframe[src*="googleads"], iframe[id^="google_ads"]').forEach(kill);
  const v = document.getElementById('google_vignette'); if (v) kill(v);
  // a fixed full-viewport layer above everything that is not a form/dialog the page needs: only ad containers (name says ad) are touched
  document.querySelectorAll('div[id*="google_vignette"], div[class*="google-vignette"], div[id*="ad_overlay"], div[class*="ad-overlay"]').forEach(kill);
  document.documentElement.style.overflow = ''; document.body && (document.body.style.overflow = '');
  return n;
}"""


def clear_ads(page, target=None):
    """Call before any click on a page that shows ads. Never raises (a page that navigated away has nothing to clear).
    Removes ad nodes; with `target` (a CSS selector) it also removes fixed / high-z layers covering that element (see clear_overlays)."""
    try: n = int(page.evaluate(CLEAR_ADS_JS) or 0)
    except Exception: n = 0
    return n + (clear_overlays(page, target) if target else 0)


def wait_out_wall(page, seconds=60):
    """The interstitial clears by itself in the real Chrome. Wait; never solve. Raises RuntimeError if it does not clear."""
    for _ in range(max(1, seconds // 2)):
        try: txt = page.inner_text("body")[:3000]
        except Exception: txt = ""
        if not WALL_RE.search(txt): return
        page.wait_for_timeout(2000)
    raise RuntimeError("security check did not clear in %ds; needs a human or a proxy, not a bypass" % seconds)


def md5_hex(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""): h.update(chunk)
    return h.hexdigest()


def ensure_logo(path=None, source=None, fetch=None):
    """-> path of the stored local logo, verified by md5 prefix. Copies from the vault source when missing. `fetch(url)->bytes` (optional) also proves the published
    URL still serves the same bytes; it is injectable so tests make no call."""
    path, source = path or LOGO_PATH, source or LOGO_SOURCE
    if not os.path.exists(path):
        if not source or not os.path.exists(source): raise RuntimeError("logo copy missing at %s and no CE_LOGO_SOURCE to re-create it from" % path)
        os.makedirs(os.path.dirname(path), exist_ok=True); shutil.copyfile(source, path)
    got = md5_hex(path)
    if not got.startswith(LOGO_MD5_PREFIX): raise RuntimeError("logo at %s has md5 %s, expected %s..." % (path, got[:8], LOGO_MD5_PREFIX))
    if fetch is not None:
        data = fetch(LOGO_URL)
        if hashlib.md5(data).hexdigest() != got: raise RuntimeError("published logo URL no longer serves the stored file")
    return path


def set_file(page, selector, file_path, cdp_session=None):
    """Attach file_path to the first <input type=file> matching selector with CDP DOM.setFileInputFiles. No dialog, no click. Returns the file name attached."""
    if not os.path.isfile(file_path): raise RuntimeError("upload file not found: %s" % file_path)
    s = cdp_session or page.context.new_cdp_session(page)
    try:
        root = s.send("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
        node = s.send("DOM.querySelector", {"nodeId": root, "selector": selector}).get("nodeId")
        if not node: raise RuntimeError("file input %s not found" % selector)
        s.send("DOM.setFileInputFiles", {"files": [os.path.abspath(file_path)], "nodeId": node})
    finally:
        if cdp_session is None:
            try: s.detach()
            except Exception: pass
    return os.path.basename(file_path)


# ---- overlays (t_d7a907d5) ---------------------------------------------------------------------------------------------
# clear_ads() removes ad NODES. Pages also put a fixed, high z-index layer (cookie wall, newsletter modal, "ad-free" prompt, backdrop) over the form and
# swallow the click. Two passes: (1) with a target selector, remove whatever elementFromPoint finds on top of the target's centre while it is a fixed /
# sticky / high-z layer that does not contain the target; (2) without one, remove fixed high-z layers covering >= 40% of the viewport that hold no form field.
OVERLAY_JS = """(arg) => {
  const target = arg && arg.sel ? document.querySelector(arg.sel) : null;
  const layerOf = el => { for (let e = el; e && e !== document.body && e !== document.documentElement; e = e.parentElement) {
    const cs = getComputedStyle(e), z = parseInt(cs.zIndex, 10) || 0;
    if ((cs.position === 'fixed' || cs.position === 'sticky') || (cs.position === 'absolute' && z >= 1000)) return e; } return null; };
  let removed = 0;
  if (target) {
    try { target.scrollIntoView({block: 'center'}); } catch (x) {}
    for (let i = 0; i < 6; i++) {
      const r = target.getBoundingClientRect();
      const top = document.elementFromPoint(Math.min(Math.max(r.left + r.width / 2, 0), innerWidth - 1), Math.min(Math.max(r.top + r.height / 2, 0), innerHeight - 1));
      if (!top || top === target || target.contains(top) || top.contains(target)) break;
      const layer = layerOf(top);
      if (!layer || layer.contains(target)) break;
      layer.remove(); removed++;
    }
  } else {
    document.querySelectorAll('body *').forEach(e => {
      const cs = getComputedStyle(e);
      if (cs.position !== 'fixed' || (parseInt(cs.zIndex, 10) || 0) < 1000) return;
      const r = e.getBoundingClientRect();
      if (r.width * r.height < 0.4 * innerWidth * innerHeight) return;
      if (e.querySelector('form, input:not([type=hidden]), select, textarea')) return;
      e.remove(); removed++;
    });
  }
  document.documentElement.style.overflow = ''; document.body && (document.body.style.overflow = '');
  return removed;
}"""


def clear_overlays(page, target=None):
    """Remove fixed / high-z layers that cover `target` (a CSS selector), or the big form-less ones when no target. Never raises. Returns nodes removed."""
    try: return int(page.evaluate(OVERLAY_JS, {"sel": target}) or 0)
    except Exception: return 0


def clear_all(page, target=None):
    """clear_ads + clear_overlays: call before a click."""
    return clear_ads(page) + clear_overlays(page, target)


def _origin(u):
    from urllib.parse import urlparse
    p = urlparse(u or ""); return (p.scheme, p.netloc)


def find_in_frames(page, selectors):
    """-> (frame, selector) for the first selector found in the main page or a SAME-ORIGIN iframe (getlistedusa puts its submit button in one); None otherwise.
    Cross-origin frames (ads, payment widgets) are never searched. `selectors` may be one string or a list."""
    sels = [selectors] if isinstance(selectors, str) else list(selectors)
    frames = list(getattr(page, "frames", None) or [])
    main = getattr(page, "main_frame", None)
    order = ([main] if main is not None else []) + [f for f in frames if f is not main]
    base = _origin(page.url)
    for fr in order:
        if fr is not main and _origin(getattr(fr, "url", "")) != base: continue
        for s in sels:
            try:
                if fr.locator(s).count(): return fr, s
            except Exception:
                continue
    return None


SUBMIT_SELECTORS = ("button[type=submit]", "input[type=submit]", "button#submit", "#submit", "button.submit", "input[value*=Submit i]", "button:has-text('Submit')")


def click_in_frames(page, selectors=SUBMIT_SELECTORS, timeout=15000):
    """Clear overlays, find the button in the page or a same-origin iframe, click it. Returns where it was found ('page' | 'frame <url>'). RuntimeError when absent."""
    clear_all(page)
    hit = find_in_frames(page, selectors)
    if not hit: raise RuntimeError("no %s found in the page or a same-origin iframe" % (selectors if isinstance(selectors, str) else "/".join(list(selectors)[:3])))
    fr, s = hit
    fr.locator(s).first.click(timeout=timeout)
    return "page" if fr is getattr(page, "main_frame", None) else "frame %s" % getattr(fr, "url", "?")[:80]


# ---- select helper (t_d7a907d5) ----------------------------------------------------------------------------------------
# One call for three widgets: a native <select>; select2 (hidden <select> + .select2 container, results in a body-level dropdown); Choices.js
# (.choices wrapper, click .choices__inner, type in the cloned search input, pick from the dropdown list).
SELECT_PROBE_JS = """(arg) => {
  let el = null; const want = (arg.sel || '').trim().toLowerCase().replace(/[*:]+$/, '').trim();
  if (arg.by === 'label') {
    for (const l of document.querySelectorAll('label')) {
      const t = (l.textContent || '').trim().toLowerCase().replace(/[*:]+$/, '').trim();
      if (t === want) { el = l.control || (l.htmlFor && document.getElementById(l.htmlFor)) || l.querySelector('select,input') || (l.parentElement && l.parentElement.querySelector('select,.choices,.select2')); if (el) break; }
    }
    if (!el) el = [...document.querySelectorAll('select,.choices')].find(e => (e.getAttribute('aria-label') || '').trim().toLowerCase() === want || (e.getAttribute('data-placeholder') || '').trim().toLowerCase() === want) || null;
  } else { el = document.querySelector(arg.sel); }
  if (!el) return null;
  const choices = el.closest('.choices'), s2c = el.closest('.select2-container');
  let kind = 'native', root = el;
  if (choices) { kind = 'choices'; root = choices; }
  else if (s2c) { kind = 'select2'; root = s2c; }
  else if (el.tagName === 'SELECT' && (el.classList.contains('select2-hidden-accessible') || (el.nextElementSibling && el.nextElementSibling.classList.contains('select2-container')))) { kind = 'select2'; root = el.nextElementSibling; }
  else if (el.tagName !== 'SELECT') { return {kind: 'unknown'}; }
  document.querySelectorAll('[data-ce-pick]').forEach(n => n.removeAttribute('data-ce-pick'));
  root.setAttribute('data-ce-pick', '1');
  return {kind: kind};
}"""

FIND_OPTION_JS = """(arg) => {
  const norm = s => (s || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim().toLowerCase();
  const want = norm(arg.text), nodes = [...document.querySelectorAll(arg.css)];
  const vis = n => !!(n.offsetWidth || n.offsetHeight || n.getClientRects().length);
  const pick = f => nodes.findIndex(n => vis(n) && f(norm(n.textContent)));
  let i = pick(t => t === want); if (i < 0) i = pick(t => t.startsWith(want)); if (i < 0) i = pick(t => t.includes(want));
  return i;
}"""

NATIVE_VALUE_JS = """(arg) => {
  const root = document.querySelector('[data-ce-pick]'); const s = root && (root.tagName === 'SELECT' ? root : root.querySelector('select')); if (!s) return null;
  const norm = x => (x || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim().toLowerCase(), want = norm(arg.text), o = [...s.options];
  const hit = o.find(x => norm(x.textContent) === want) || o.find(x => norm(x.textContent).startsWith(want)) || o.find(x => norm(x.value) === want);
  return hit ? hit.value : null;
}"""

SHOWN_JS = """(arg) => {
  const root = document.querySelector('[data-ce-pick]'); if (!root) return '';
  const norm = s => (s || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();
  if (arg.kind === 'choices') { const n = root.querySelector('.choices__list--single .choices__item, .choices__item--selectable'); return norm(n ? n.textContent : ''); }
  if (arg.kind === 'select2') { const n = root.querySelector('.select2-selection__rendered, .select2-selection__choice'); return norm(n ? n.textContent : ''); }
  const s = root.tagName === 'SELECT' ? root : root.querySelector('select'); if (!s || s.selectedIndex < 0) return '';
  return norm(s.options[s.selectedIndex].textContent);
}"""

_CSS_RE = re.compile(r"^(css=)?([#.\[]|[a-z][a-z0-9]*[#.\[:>]|[a-z][a-z0-9]*\s*[>+~]|select$)", re.I)


def _is_css(target):
    return bool(_CSS_RE.match(target.strip())) or "[" in target or ">" in target


def _pick_option(page, css, text, wait_ms=6000):
    waited = 0
    while True:
        idx = page.evaluate(FIND_OPTION_JS, {"css": css, "text": text})
        if isinstance(idx, int) and idx >= 0:
            page.locator(css).nth(idx).click(timeout=10000); return
        if waited >= wait_ms: raise RuntimeError("no option reading %r in %s" % (text, css.split(" ")[-1]))
        page.wait_for_timeout(300); waited += 300


def select(page, target, text):
    """Choose `text` in the dropdown named by `target` (a label like 'City', or a CSS selector like '#category'). Detects native / select2 / Choices.js.
    Verifies the widget shows the choice afterwards. Returns {'kind', 'shown'}. RuntimeError when the control, the option or the readback is missing."""
    t = target.strip()
    by = "css" if _is_css(t) else "label"
    sel = t[4:] if t.lower().startswith("css=") else t[6:] if t.lower().startswith("label=") else t
    if t.lower().startswith("label="): by = "label"
    clear_overlays(page, sel if by == "css" else None)
    probe = page.evaluate(SELECT_PROBE_JS, {"by": by, "sel": sel})
    if not probe: raise RuntimeError("select: no control found for %s %r" % (by, sel))
    kind = probe.get("kind")
    if kind == "unknown": raise RuntimeError("select: %r is not a select, select2 or Choices.js control" % sel)
    root = "[data-ce-pick]"
    if kind == "native":
        # option text often carries &nbsp; indents (citylocalpro categories): match on normalized text, then select by value
        val = page.evaluate(NATIVE_VALUE_JS, {"text": text})
        if val is None: raise RuntimeError("select %r: no option reading %r" % (sel, text))
        page.select_option(root, value=val)
    elif kind == "select2":
        page.locator(root + " .select2-selection").first.click(timeout=10000)
        if page.locator(".select2-container--open .select2-search__field").count():
            page.type(".select2-container--open .select2-search__field", text, delay=25)
        _pick_option(page, ".select2-container--open .select2-results__option:not(.select2-results__message)", text)
    else:   # choices
        page.locator(root + " .choices__inner").first.click(timeout=10000)
        if page.locator(root + " input.choices__input--cloned").count():
            page.type(root + " input.choices__input--cloned", text, delay=25)
        _pick_option(page, root + " .choices__list--dropdown .choices__item--choice.choices__item--selectable", text)
    shown = str(page.evaluate(SHOWN_JS, {"kind": kind}) or "")
    if text.strip().lower() not in shown.lower() and shown.lower() not in text.strip().lower() or not shown:
        raise RuntimeError("select %r: the %s control shows %r after choosing %r" % (sel, kind, shown, text))
    return {"kind": kind, "shown": shown}


_SECRET_LINE = re.compile(r"(?im)^(.*(?:password|passwd|pass word)\b[^\n:=]*[:=]?\s*)(\S+)\s*$")


def redact(text):
    """Mask the value after a 'password' label. Use for any page text that is printed or logged; find-us-here dashboards show the password in plain text."""
    return _SECRET_LINE.sub(lambda m: m.group(1) + "****", text or "")
