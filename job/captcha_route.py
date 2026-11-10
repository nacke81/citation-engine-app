"""CAPTCHA router (kanban t_1c503c7f). Reads a page's HTML and says what kind of widget it holds, its sitekey, and the exact logged command (python job/capsolver_solve.py ...) to run.

Rules (Mike 10/26, citation-submit skill):
  * reCAPTCHA v2 / v3 and Cloudflare Turnstile WIDGETS on a form -> CapSolver via capsolver-cli.js, 3 tries at most per row.
  * Image CAPTCHA -> CapSolver image, 3 tries at most per row.
  * hCaptcha -> capsolver-cli.js has no hcaptcha kind, so park `WALL:hcaptcha`.
  * A full-page Cloudflare "Just a moment" interstitial is NOT a form widget: `WALL:cloudflare-click`, never CapSolver.
Pure: no network, no browser. Reads text you hand it. Never reads or prints the CapSolver key (the CLI reads it from the profile .env by name).

  python job/captcha_route.py --url https://site.example/claim --html saved_page.html
  python job/captcha_route.py --url https://site.example/claim --stdin < saved_page.html
"""
import html as html_lib, json, os, re, sys

MAX_TRIES = 3
CLI = os.environ.get("CAPSOLVER_CLI") or "capsolver-cli.js"
CAP = "2"

INTERSTITIAL_RE = re.compile(r"(?is)<title>\s*just a moment|cf-browser-verification|challenge-platform/h/./orchestrate/chl_page|_cf_chl_opt|<title>\s*attention required")
# A Turnstile widget on a form carries data-sitekey on .cf-turnstile or loads the explicit-render api; an interstitial has neither a form nor a sitekey of ours.
TURNSTILE_RE = re.compile(r"""(?is)(?:class=["'][^"']*cf-turnstile[^"']*["'][^>]*data-sitekey=["']([^"']+)["']|data-sitekey=["']([^"']+)["'][^>]*class=["'][^"']*cf-turnstile)""")
TURNSTILE_JS_RE = re.compile(r"""(?is)turnstile\.render\([^,]+,\s*\{[^}]*sitekey\s*:\s*["']([^"']+)["']""")
HCAPTCHA_RE = re.compile(r"""(?is)(?:class=["'][^"']*h-captcha[^"']*["'][^>]*data-sitekey=["']([^"']+)["']|data-sitekey=["']([^"']+)["'][^>]*class=["'][^"']*h-captcha|hcaptcha\.com/1/api\.js)""")
RECAPTCHA_V3_RE = re.compile(r"""(?is)recaptcha/(?:api|enterprise)\.js\?[^"'>]*render=(?!explicit)([A-Za-z0-9_\-]{20,})""")
RECAPTCHA_V2_RE = re.compile(r"""(?is)(?:class=["'][^"']*g-recaptcha[^"']*["'][^>]*data-sitekey=["']([^"']+)["']|data-sitekey=["']([^"']+)["'][^>]*class=["'][^"']*g-recaptcha|grecaptcha\.render\([^,]+,\s*\{[^}]*sitekey\s*:\s*["']([^"']+)["'])""")
RECAPTCHA_FRAME_RE = re.compile(r"""(?is)recaptcha/(?:api2|enterprise)/anchor\?(?:[^"'>]*?&)?k=([A-Za-z0-9_\-]{20,})""")
IMAGE_RE = re.compile(r"""(?is)<img\b[^>]*(?:captcha|securimage|security[-_ ]?code)[^>]*>""")
HAS_FORM_RE = re.compile(r"(?is)<form\b|<input\b")


def _first(m):
    return next((g for g in m.groups() if g), None) if m else None


def detect(html, url=""):
    """-> {"interstitial": bool, "widgets": [{"type", "sitekey"}]}. A walled interstitial reports no widgets even if the page text mentions Turnstile."""
    html = html or ""
    inter = bool(INTERSTITIAL_RE.search(html)) and not HAS_FORM_RE.search(re.sub(r"(?is)<script.*?</script>", "", html))
    if inter:
        return {"interstitial": True, "widgets": []}
    out = []
    def add(t, k):
        if not any(w["type"] == t and w["sitekey"] == k for w in out): out.append({"type": t, "sitekey": k})
    k = _first(TURNSTILE_RE.search(html)) or _first(TURNSTILE_JS_RE.search(html))
    if k: add("turnstile", k)
    m = HCAPTCHA_RE.search(html)
    if m: add("hcaptcha", _first(m))
    m = RECAPTCHA_V3_RE.search(html)
    if m: add("recaptcha-v3", m.group(1))
    k = _first(RECAPTCHA_V2_RE.search(html)) or _first(RECAPTCHA_FRAME_RE.search(html_lib.unescape(html)))
    if k and not any(w["type"] == "recaptcha-v3" and w["sitekey"] == k for w in out): add("recaptcha-v2", k)
    if IMAGE_RE.search(html): add("image", None)
    return {"interstitial": False, "widgets": out}


def verdict(widget_type):
    """-> (route, wall). route is 'capsolver' or 'park'."""
    if widget_type in ("recaptcha-v2", "recaptcha-v3", "turnstile", "image"): return "capsolver", None
    if widget_type == "hcaptcha": return "park", "WALL:hcaptcha"
    return "park", "WALL:unknown-captcha"


def _check(widget, url):
    t = widget["type"]
    if verdict(t)[0] != "capsolver": raise ValueError("%s is not routed to CapSolver (%s)" % (t, verdict(t)[1]))
    if not re.match(r"^https?://", url or ""): raise ValueError("url must be an http(s) page URL")
    if t != "image":
        if not widget.get("sitekey"): raise ValueError("%s widget has no sitekey" % t)
        if not re.match(r"^[A-Za-z0-9_\-]{10,}$", widget["sitekey"]): raise ValueError("sitekey has an unexpected shape")
    return t


def command(widget, url, row=None, page_action=None):
    """The command a worker runs: job/capsolver_solve.py, which calls pagekit.solve_captcha so the solve is logged (one line in the solve log) and
    the 3-tries-per-row cap applies. `row` fills --row (else the <row-id> placeholder). page_action (reCAPTCHA v3 only) adds --page-action.
    Never returns the raw capsolver-cli.js line: that path writes no log. Raises ValueError for a widget CapSolver does not handle here."""
    t = _check(widget, url)
    if page_action is not None and not re.match(r"^[A-Za-z0-9_/]{1,100}$", page_action): raise ValueError("page_action has an unexpected shape")
    line = "python job/capsolver_solve.py --row %s --kind %s --url %s" % (row or "<row-id>", t, url)
    if t == "image":
        return line + " --extra '{\"body\":\"<base64 of the captcha image, no data: prefix>\"}'"
    line += " --sitekey %s" % widget["sitekey"]
    if page_action and t == "recaptcha-v3": line += " --page-action %s" % page_action
    return line


def argv(widget, url, cli=None, extra=None):
    """The subprocess list pagekit runs: the REAL capsolver-cli.js (the logging wrapper calls pagekit, which calls this). Not for workers to paste.
    Image widgets pass extra={"body": <base64>}; v3 passes extra={"pageAction": a}."""
    t = _check(widget, url)
    base = ["node", cli or CLI, "--kind", t, "--url", url]
    if t != "image": base += ["--sitekey", widget["sitekey"]]
    if extra: base += ["--extra", json.dumps(extra)]
    return base + ["--cap", CAP]


PAGE_ACTION_RE = re.compile(r"""grecaptcha(?:\.enterprise)?\.execute\(\s*[^,)]+,\s*\{[^}]*?\baction\s*:\s*["']([A-Za-z0-9_/]{1,100})["']""", re.I)


def detect_page_actions(html):
    """-> every distinct action string in visible grecaptcha.execute(key, {action: 'x'}) calls, in page order."""
    out = []
    for m in PAGE_ACTION_RE.finditer(html or ""):
        if m.group(1) not in out: out.append(m.group(1))
    return out


def plan(html, url, cli=None, row=None):
    """One dict the caller can print or act on: {"route", "wall", "commands", "max_tries", "notes"}."""
    d = detect(html, url)
    if d["interstitial"]:
        return {"route": "park", "wall": "WALL:cloudflare-click", "commands": [], "max_tries": 1, "notes": ["full-page Cloudflare interstitial, not a form widget: click it in the build Chrome once (if it is off-screen run: python job/chrome_keepalive.py --show, then --hide after); never CapSolver (Mike's rule)", "if parked: transitions.py --to needs-human --reason-code cloudflare"]}
    if not d["widgets"]:
        return {"route": "none", "wall": None, "commands": [], "max_tries": 0, "notes": ["no CAPTCHA widget found on this page"]}
    cmds, notes, wall = [], [], None
    acts = detect_page_actions(html)
    for w in d["widgets"]:
        route, w_wall = verdict(w["type"])
        if route == "park":
            wall = wall or w_wall; notes.append("%s: capsolver-cli.js has no such kind, park %s" % (w["type"], w_wall)); continue
        act = acts[0] if (acts and w["type"] == "recaptcha-v3") else None
        if act and len(acts) > 1: notes.append("page calls grecaptcha.execute with %d actions %s: --page-action %s is the first one; pass the submit action instead if it differs" % (len(acts), acts, act))
        try: cmds.append(command(w, url, row=row, page_action=act))
        except ValueError as e: notes.append(str(e))
    if cmds: wall = None
    return {"route": "capsolver" if cmds else "park", "wall": wall, "commands": cmds, "max_tries": MAX_TRIES, "notes": notes + ["%d tries at most per row; after that park needs-human with the CAPTCHA note and --reason-code captcha" % MAX_TRIES]}


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="Read a saved page, print the CAPTCHA widget type, sitekey and the logged capsolver_solve.py command")
    a.add_argument("--url", required=True)
    a.add_argument("--row", help="queue row id to put in the printed command (else <row-id>)")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--html"); g.add_argument("--stdin", action="store_true")
    n = a.parse_args(argv)
    html = sys.stdin.read() if n.stdin else open(n.html, encoding="utf-8", errors="replace").read()
    p = plan(html, n.url, row=n.row)
    print(json.dumps(p, indent=1))
    return 0 if p["route"] in ("capsolver", "none") else 3


if __name__ == "__main__":
    sys.exit(main())
