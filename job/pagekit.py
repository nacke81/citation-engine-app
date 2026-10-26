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


def clear_ads(page):
    """Call before any click on a page that shows ads. Never raises (a page that navigated away has nothing to clear)."""
    try: return int(page.evaluate(CLEAR_ADS_JS) or 0)
    except Exception: return 0


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


_SECRET_LINE = re.compile(r"(?im)^(.*(?:password|passwd|pass word)\b[^\n:=]*[:=]?\s*)(\S+)\s*$")


def redact(text):
    """Mask the value after a 'password' label. Use for any page text that is printed or logged; find-us-here dashboards show the password in plain text."""
    return _SECRET_LINE.sub(lambda m: m.group(1) + "****", text or "")
