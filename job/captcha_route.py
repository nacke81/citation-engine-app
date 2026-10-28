"""CAPTCHA router (kanban t_1c503c7f). Reads a page's HTML and says what kind of widget it holds, its sitekey, and the exact capsolver-cli.js command.

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


def command(widget, url, cli=None):
    """The exact capsolver-cli.js command for one widget. Raises ValueError for a widget CapSolver does not handle here."""
    t = widget["type"]
    if verdict(t)[0] != "capsolver": raise ValueError("%s is not routed to CapSolver (%s)" % (t, verdict(t)[1]))
    if not re.match(r"^https?://", url or ""): raise ValueError("url must be an http(s) page URL")
    cli = cli or CLI
    if t == "image":
        return "node %s --kind image --url %s --extra '{\"body\":\"<base64 of the captcha image, no data: prefix>\"}' --cap %s" % (cli, url, CAP)
    if not widget.get("sitekey"): raise ValueError("%s widget has no sitekey" % t)
    if not re.match(r"^[A-Za-z0-9_\-]{10,}$", widget["sitekey"]): raise ValueError("sitekey has an unexpected shape")
    return "node %s --kind %s --url %s --sitekey %s --cap %s" % (cli, t, url, widget["sitekey"], CAP)


def argv(widget, url, cli=None, extra=None):
    """The same command as command(), as an argument list for subprocess (no shell quoting). Image widgets pass extra={"body": <base64>}."""
    line = command(widget, url, cli)
    t = widget["type"]
    base = ["node", cli or CLI, "--kind", t, "--url", url]
    if t != "image": base += ["--sitekey", widget["sitekey"]]
    if t == "image" and extra: base += ["--extra", json.dumps(extra)]
    return base + ["--cap", CAP]


def plan(html, url, cli=None):
    """One dict the caller can print or act on: {"route", "wall", "commands", "max_tries", "notes"}."""
    d = detect(html, url)
    if d["interstitial"]:
        return {"route": "park", "wall": "WALL:cloudflare-click", "commands": [], "max_tries": 1, "notes": ["full-page Cloudflare interstitial, not a form widget: click it in the build Chrome once; never CapSolver (Mike's rule)"]}
    if not d["widgets"]:
        return {"route": "none", "wall": None, "commands": [], "max_tries": 0, "notes": ["no CAPTCHA widget found on this page"]}
    cmds, notes, wall = [], [], None
    for w in d["widgets"]:
        route, w_wall = verdict(w["type"])
        if route == "park":
            wall = wall or w_wall; notes.append("%s: capsolver-cli.js has no such kind, park %s" % (w["type"], w_wall)); continue
        try: cmds.append(command(w, url, cli))
        except ValueError as e: notes.append(str(e))
    if cmds: wall = None
    return {"route": "capsolver" if cmds else "park", "wall": wall, "commands": cmds, "max_tries": MAX_TRIES, "notes": notes + ["%d tries at most per row; after that park needs-human with the CAPTCHA note" % MAX_TRIES]}


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="Read a saved page, print the CAPTCHA widget type, sitekey and the capsolver-cli.js command")
    a.add_argument("--url", required=True)
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--html"); g.add_argument("--stdin", action="store_true")
    n = a.parse_args(argv)
    html = sys.stdin.read() if n.stdin else open(n.html, encoding="utf-8", errors="replace").read()
    p = plan(html, n.url)
    print(json.dumps(p, indent=1))
    return 0 if p["route"] in ("capsolver", "none") else 3


if __name__ == "__main__":
    sys.exit(main())
