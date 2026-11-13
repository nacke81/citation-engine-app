"""Recheck job for rows that wait on a Directory (t_64c4d511). Read-only toward Directories: public GETs only (plain first, the build Chrome on CDP 9333
when the plain page is walled or has no readable listing). No login, no signup, no submit.

For every queue row in submitted / pending-verify / found (and live, report only, with --include-live) that carries a listing permalink:
  fetch the public page -> read the listing's own block -> compare name / street / phone to q["canonical"].
  all three match  -> Proof on ce_directory_status, then live through transitions.record_transition (with the permalink)
  a field differs  -> same-state note naming the field and the value shown (no state change)
  a field is absent / the page is paused-> verdict nap-incomplete, same-state note naming the gap (a created-unlisted row stays created-unlisted)
  page unreadable  -> nothing written
  no permalink     -> nothing written (bbb.org is the exception: its profile URL is looked up by name + city and stored with a same-state note)
A note identical to the row's last history note is not written again, so a weekly run does not pile up duplicates.

  python job/recheck.py [--queue PATH] [--write] [--include-live] [--row ID ...] [--any-state] [--no-chrome]
                        [--live-sweep-ok] [--save-pages DIR | --replay DIR]
t_e34fc55c: one read per row (a row about to change state is confirmed once more, spaced by the site guard); per-domain gap / daily cap / cooldown (sitegate.py);
a quota or Cloudflare wall gives verdict `rate-limited` (nothing written, domain cooled down, one line in logs/site-walls.jsonl); --include-live over the whole queue needs
--live-sweep-ok (weekly job only); --replay DIR scores pages saved by --save-pages with no network.
Without --write nothing is written (dry run); the report still shows before -> after and any mismatch.
"""
import html, json, os, re, sys, urllib.parse, urllib.request, urllib.error
from urllib.parse import quote, urljoin, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buildqueue as Q
import sitegate as SG
import fixlist as F
import listing as L
import walls as W
import mail_scan as MS

US_STATES = {n.lower(): a for n, a in (("Alabama", "AL"), ("Alaska", "AK"), ("Arizona", "AZ"), ("Arkansas", "AR"), ("California", "CA"), ("Colorado", "CO"), ("Connecticut", "CT"), ("Delaware", "DE"), ("Florida", "FL"), ("Georgia", "GA"), ("Hawaii", "HI"), ("Idaho", "ID"), ("Illinois", "IL"), ("Indiana", "IN"), ("Iowa", "IA"), ("Kansas", "KS"), ("Kentucky", "KY"), ("Louisiana", "LA"), ("Maine", "ME"), ("Maryland", "MD"), ("Massachusetts", "MA"), ("Michigan", "MI"), ("Minnesota", "MN"), ("Mississippi", "MS"), ("Missouri", "MO"), ("Montana", "MT"), ("Nebraska", "NE"), ("Nevada", "NV"), ("New Hampshire", "NH"), ("New Jersey", "NJ"), ("New Mexico", "NM"), ("New York", "NY"), ("North Carolina", "NC"), ("North Dakota", "ND"), ("Ohio", "OH"), ("Oklahoma", "OK"), ("Oregon", "OR"), ("Pennsylvania", "PA"), ("Rhode Island", "RI"), ("South Carolina", "SC"), ("South Dakota", "SD"), ("Tennessee", "TN"), ("Texas", "TX"), ("Utah", "UT"), ("Vermont", "VT"), ("Virginia", "VA"), ("Washington", "WA"), ("West Virginia", "WV"), ("Wisconsin", "WI"), ("Wyoming", "WY"))}   # t_11f5b2b0: full state names on listing pages
STABLE_POLL_MS = 3000   # t_0c4ebee8: poll spacing of the ONE rendered read that waits for the NAP text to hold still
STABLE_MAX_S = 20       # ... and the longest it waits once the page first read
SAVED_MAX_AGE_S = 15 * 60   # t_0c4ebee8: --write --from-read DIR reuses a dry run's saved pages only when younger than this
STABLE_READS = 2   # an OSM (API tags) match on a row that is NOT yet live is confirmed by one more read (t_ac8b1bdd); a row already live is read once (t_e34fc55c)
WAITING = ("submitted", "pending-verify", "found", "created-unlisted")
CDP_URL = "http://127.0.0.1:9333"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
WALL_RE = re.compile(r"(?i)just a moment|quick security check|performing a quick|verify you are (a )?human|attention required|access denied|"
                     r"checking your browser|are you a robot|press (&|and) hold|error 1020|request blocked|security verification")
PLUS_PHONE_RE = re.compile(r"(?<![\w+])\+\d[\d\s().\-]{5,18}\d")
MASKED_NUM_RE = re.compile(r"\+?(?:(\d[\d\s().\-]{0,6}?)\s*[*xX\u2022]{2,}\s*([\d\s().\-]{0,6}\d)|(\(?\d{3}\)?[\s.\-]{0,2}\d{3}[\s.\-]{0,2}\d{0,2})\s*[*\u2022]{2,})")   # +127****2550; or trailing stars only: (270) 841-2*** (group 3, t_6b1e01ff)
HEXID_RE = re.compile(r"(?i)^[0-9a-f]{4,}(-[0-9a-f]{2,})+$")
# t_f707b644: a page that EXISTS but is not a public, complete listing yet (showmelocal "HIDDEN until ACTIVATED", paused). Its NAP may match; it is still not live.
# Not-live markers (t_bbc32230): a page that carries the full NAP AND one of these is NOT a public listing (showmelocal: "This Listing is HIDDEN until ACTIVATED").
# Only markers seen on a real page or named by the Directory are listed; tupalo, acompio and chamberofcommerce public pages have no captured marker text yet
# (the 10/27 owner view said "Unverified" / "pending"), so they are covered by the generic hidden / paused / not activated / pending approval wording below.
NOT_LIVE_MARKERS = (
    r"hidden until activated", r"listing (is |has been )?(currently )?(paused|hidden|unpublished|inactive|not (yet )?(public|visible|published|activated|live))",
    r"this listing is (paused|hidden|inactive|not (yet )?(activated|live|public))", r"not (yet )?activated", r"activate (your |this )?listing to (make|publish)",
    r"pending (review|approval|activation|moderation)", r"awaiting (review|approval|activation|moderation)",
)
UNLISTED_RE = re.compile(r"(?i)" + "|".join(NOT_LIVE_MARKERS))
ADDR_NOT_LISTED_RE = re.compile(r"(?i)address (is )?not (listed|provided|available|shown)")
MASKED_PHONE_RE = re.compile(r"\*{2,}|reveal phone|show phone|click to (call|view)", re.I)   # a hidden phone is not a wrong phone


class Page:
    def __init__(self, status, url, text, links=None, err=None, html=None, limited=None, unstable=None):
        self.status, self.url, self.text, self.links, self.err, self.html = status, url, text or "", links or [], err, html
        self.unstable = unstable   # t_0c4ebee8: the per-poll NAP verdicts when the rendered read never settled (never live)
        self.limited = limited   # t_e34fc55c: why the site guard refused / the page is a quota or wall (rate-limited verdict)


# ---- fetching (every edge injectable) -----------------------------------------------------------------------------
def walled(page):
    return page.status in (None, 0, 401, 403, 429) or (page.status or 0) >= 500 or bool(WALL_RE.search(page.text[:4000])) or len(page.text.strip()) < 200


QUOTA_URL_RE = re.compile(r"(?i)bizapedia\.com/pro-search-subscription")
QUOTA_TEXT_RE = re.compile(r"(?i)run out of (your )?free searches|out of free searches")
CF_WALL_RE = re.compile(r"(?i)just a moment|quick security check|performing a quick|verify you are (a )?human|attention required|checking your browser|press (&|and) hold|error 1020|security verification")


def quota_reason(page):
    """The site's own quota / paywall page (Bizapedia: redirected to pro-search-subscription.aspx, a 200)."""
    if QUOTA_URL_RE.search(page.url or "") or QUOTA_TEXT_RE.search((page.text or "")[:6000]): return "quota page: out of free searches (%s)" % urlparse(page.url or "").path[:60]
    return None


def wall_reason(page):
    """Why this FINAL page is a quota or Cloudflare wall, else None. A plain 403 is not enough here (the Chrome route often passes it); text of the wall page or a 429 is."""
    q = quota_reason(page)
    if q: return q
    if page.status == 429: return "HTTP 429 rate limit"
    if CF_WALL_RE.search((page.text or "")[:4000]): return "Cloudflare wall"
    return None


def guarded(fn, guard, route):
    """Wrap a reader (url -> Page) with the per-domain guard: gap / cap / cooldown before the read, quota detection after it. A refused read is a limited Page, nothing fetched."""
    def read(url, *a, **k):
        dom = SG.domain_of(url)
        g = guard.reserve(dom, key=url) if dom else {"ok": True}
        if not g["ok"]: return Page(0, url, "", err="site guard: " + g["why"], limited=g["why"])
        pg = fn(url, *a, **k)
        q = quota_reason(pg)
        if q:
            guard.wall(dom, q, url=pg.url)
            pg.limited = q
        return pg
    return read


class PageStore:
    """--save-pages / --replay (t_e34fc55c). One JSON file per read: <route>-<sha1(url)[:12]>-<n>.json, n counting the reads of that URL on that route in call order.
    save: wraps a reader and stores what it returned. replay: serves the saved pages in the same order, never touches the network; a URL with no saved page is `err`."""
    def __init__(self, folder, replay=False):
        self.dir, self.replay, self.n, self.reused = folder, replay, {}, 0
        if not replay: os.makedirs(folder, exist_ok=True)

    def _path(self, route, url):
        import hashlib
        k = (route, url); self.n[k] = self.n.get(k, 0) + 1
        return os.path.join(self.dir, "%s-%s-%d.json" % (route, hashlib.sha1(url.encode("utf-8")).hexdigest()[:12], self.n[k]))

    def saving(self, fn, route):
        def read(url, *a, **k):
            pg = fn(url, *a, **k)
            d = {"url": url, "status": pg.status, "final": pg.url, "text": pg.text, "links": pg.links, "err": pg.err, "html": pg.html, "limited": getattr(pg, "limited", None), "unstable": getattr(pg, "unstable", None)}
            with open(self._path(route, url), "w", encoding="utf-8") as f: json.dump(d, f, ensure_ascii=False, sort_keys=True)
            return pg
        return read

    def reusing(self, fn, route, now=None, max_age=SAVED_MAX_AGE_S):
        """--write --from-read DIR (t_0c4ebee8): serve a dry run's saved page instead of reading again, but only when the file is younger than `max_age`, its saved url is the url
        asked for (row/URL match), and the Directory really answered (an HTTP status, not a guard refusal / quota / transport failure; a plain 403 IS reused, it is what the dry run saw). The n-th ask of a URL gets the n-th saved page, like --replay. Anything else
        goes to `fn`, the live reader (guarded, one read). `fn` is the guarded reader, so a reuse never reserves the guard. `self.reused` counts the reuses."""
        import time as _t
        now = now or _t.time
        def read(url, *a, **k):
            p = self._path(route, url)
            try:
                d = json.load(open(p, encoding="utf-8")) if now() - os.path.getmtime(p) <= max_age else None
            except (OSError, ValueError): d = None
            if d and d.get("url") == url and not d.get("limited") and d.get("status") and d["text"] is not None:
                self.reused += 1
                return Page(d["status"], d["final"], d["text"], d["links"], d["err"], d["html"], d.get("limited"), d.get("unstable"))
            return fn(url, *a, **k)
        return read

    def replaying(self, route):
        def read(url, *a, **k):
            p = self._path(route, url)
            if not os.path.exists(p):   # more reads than were saved: the last one repeats; none saved: an error page
                p2 = p.rsplit("-", 1)[0] + "-1.json"
                n = self.n[(route, url)]
                while n > 1 and not os.path.exists(p2): n -= 1; p2 = p.rsplit("-", 1)[0] + "-%d.json" % n
                if not os.path.exists(p2): return Page(0, url, "", err="replay: no saved page", limited=None)
                p = p2
            d = json.load(open(p, encoding="utf-8"))
            return Page(d["status"], d["final"], d["text"], d["links"], d["err"], d["html"], d.get("limited"), d.get("unstable"))
        return read


def plain_fetch(url):
    """One public GET. Never raises."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"})
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", "replace"); status, final = r.status, r.geturl()
    except urllib.error.HTTPError as e:
        return Page(e.code, url, "", err="HTTP %s" % e.code)
    except Exception as e:
        return Page(0, url, "", err=type(e).__name__)
    import claim
    text = claim.html_to_text(html)
    links = []
    for m in re.finditer(r'(?is)<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html):
        ctx = claim.html_to_text(html[max(0, m.start() - 400):m.end() + 200])
        links.append({"href": urljoin(final, m.group(1)), "text": " ".join(claim.html_to_text(m.group(2)).split())[:80], "card": ctx[-400:], "aria": ""})
    return Page(status, final, text, links, html=html)


REVEAL_RE = r"reveal (phone|number)|show (phone|number)|view (phone|number)|click (here )?to (call|view|reveal|show)"
REVEAL_JS = """() => { const re = new RegExp(%r, 'i'); const bare = /^(show|reveal|view)$/i; let n = 0;
  for (const e of document.querySelectorAll('a,button,input[type=button],input[type=submit],span,div,[role=button]')) {
    const t = ((e.innerText || e.value || '') + '').trim();
    if (!t || t.length > 40 || !e.getClientRects().length || e.querySelector('a,button')) continue;
    // t_6b1e01ff: getlistedusa shows "(270) 841-2*** show": the control is a bare "Show" next to masked digits. A bare Show only counts when its container shows a masked number.
    const next = bare.test(t) && e.parentElement && /\\*{2,}|\\u2022{2,}/.test(e.parentElement.innerText || '');
    if (re.test(t) || next) { try { e.click(); n++; } catch (x) {} }
  } return n; }""" % REVEAL_RE


def read_rendered(pg, url, wait_s=30, canonical=None, referer=None, info=None):
    """Open `url` in page `pg`, wait for the JS page to render (past walls), click any 'Reveal Phone Number' control, then read text/links/html.
    Reads only; the one click is a public page's own reveal control (t_3ac43137). -> (status, text, links, html)"""
    import core
    if referer:   # visit the Directory's home first (its cookies + a real Referer), then the search
        try: pg.goto(referer, timeout=40000, wait_until="domcontentloaded"); pg.wait_for_timeout(2500)
        except Exception: pass
    r = pg.goto(url, timeout=40000, wait_until="domcontentloaded", **({"referer": referer} if referer else {}))   # referer: businessyab search answers 403 without a home-page Referer (t_89f4aebf)
    status = r.status if r else None
    text, prev, same, readable, seen, settled = "", None, 0, 0, [], False
    base = max(1, wait_s // 2)   # round 2: the budget to FIND a readable page; once it reads, the loop always gets the full stability window (cap fires), however many wall polls came first
    for i in range(base + int(STABLE_MAX_S * 1000 // STABLE_POLL_MS) + 1):
        if i >= base and readable == 0: break
        pg.wait_for_timeout(STABLE_POLL_MS if readable else 2000)   # t_0c4ebee8: once the page reads, poll ~3s apart
        try: text = pg.inner_text("body", timeout=8000)
        except Exception: text = ""
        if WALL_RE.search(text[:4000]) or len(text.strip()) <= 200: prev, same, readable, seen = None, 0, 0, []; continue
        # t_03a74bae (us-info flip-flop): a lazy-loaded block (the street) appears AFTER the first readable render.
        # t_0c4ebee8: this ONE load is also the stability check (it replaces the second, back-to-back confirm load). Without the canonical NAP: stop once the text held
        # still for 3 polls. With it: stop once the NAP matches AND the text did not change across 2 polls, else after 3 still polls (a page that really lacks the street).
        # Never longer than STABLE_MAX_S after the page first read.
        readable += 1
        if canonical is None:   # no NAP to judge: the whole text must hold still
            key, verdict = text, None
        else:   # t_0c4ebee8 round 1: stability is the NAP READ (verdict + the NAP found) holding still, not the body (a rotating ad / timestamp must not matter)
            try: raw_now = pg.content()   # t_69102cc9: the poll scores with the same comparator inputs (text + markup) as the final read
            except Exception: raw_now = None
            c = compare(text, canonical, raw_now); verdict = c["verdict"]; key = (verdict, json.dumps(c.get("nap"), sort_keys=True, default=str))
        seen.append(verdict)
        same = same + 1 if key == prev else 0; prev = key
        if canonical is None:
            if same >= 2: settled = True; break
        elif (same >= 1 and verdict == "match") or same >= 2: settled = True; break
        if readable * STABLE_POLL_MS / 1000.0 >= STABLE_MAX_S: break
    # t_0c4ebee8 round 2: EVERY exit that is not an early stable stop (the 20s cap, OR the loop running out of iterations after wall/slow polls, OR a small wait_s)
    # with NAP reads that disagreed and a last poll that did not hold is unstable: never scored as a listing, never live, same verdict in both phases.
    if canonical is not None and not settled and same == 0 and len(set(seen)) > 1 and info is not None: info["unstable"] = list(seen)
    try: clicked = pg.evaluate(REVEAL_JS)
    except Exception: clicked = 0
    if isinstance(clicked, int) and not isinstance(clicked, bool) and clicked > 0:   # the phone sits behind a click (us-info): let it appear, then re-read
        pg.wait_for_timeout(1500)
        try: text = pg.inner_text("body", timeout=8000)
        except Exception: pass
    try: links = pg.evaluate(core.LINKS_JS)
    except Exception: links = []
    try: raw = pg.content()
    except Exception: raw = None
    return status, text, links, raw


def chrome_fetch(url, cdp=CDP_URL, wait_s=30, canonical=None, referer=None):
    """Read the rendered page in a FRESH signed-out context of the Chrome on `cdp`. Opens and closes one context; reads only. Walls are waited on, never solved."""
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    try:
        b = p.chromium.connect_over_cdp(cdp)
        ctx = b.new_context()   # fresh, signed out (t_ac8b1bdd): contexts[0] is the signed-in build profile and shows owner-only pending edits
        pg = ctx.new_page()
        try:
            info = {}
            status, text, links, raw = read_rendered(pg, url, wait_s, canonical, referer, info) if referer else read_rendered(pg, url, wait_s, canonical, None, info)
            return Page(status, pg.url, text, links, html=raw, unstable=info.get("unstable"))
        finally:
            try: pg.close()
            except Exception: pass
            try: ctx.close()
            except Exception: pass
    except Exception as e:
        down = "connect" in str(e).lower() or "ECONNREFUSED" in str(e)
        return Page(0, url, "", err=("Chrome not reachable on %s" % cdp) if down else type(e).__name__)
    finally:
        try: p.stop()
        except Exception: pass


class SignedOutReader:
    """The recheck/Proof fallback reader (t_3ac43137): its OWN headful Chrome, clean throwaway profile (never signed in), own random CDP port
    (never 9333, never the build profile). Started on the first page that needs it, closed by close(). Callable: reader(url) -> Page. Never raises."""
    def __init__(self, chrome_factory=None, fetcher=None, wait_s=30):
        self._factory, self._fetch, self.wait_s = chrome_factory, fetcher or chrome_fetch, wait_s
        self.chrome, self.starts = None, 0
        self.canonical = None   # set by recheck(): lets the rendered read wait for the late-loading NAP lines (t_03a74bae)

    def _start(self):
        if self.chrome is None:
            if self._factory: oc = self._factory()
            else:
                import owned_chrome as OC
                oc = OC.OwnedChrome()   # profile=None: throwaway temp profile, deleted on close; port=None: free random port
            oc.__enter__(); self.chrome = oc; self.starts += 1
            if str(oc.port) == "9333":
                self.close(); raise RuntimeError("the signed-out reader must not use the build Chrome port 9333")
        return self.chrome

    def __call__(self, url, referer=None):
        try: oc = self._start()
        except Exception as e: return Page(0, url, "", err="signed-out Chrome did not start: %s" % type(e).__name__)
        if referer: return self._fetch(url, oc.cdp_url, self.wait_s, self.canonical, referer)
        return self._fetch(url, oc.cdp_url, self.wait_s, self.canonical) if self.canonical else self._fetch(url, oc.cdp_url, self.wait_s)

    def close(self):
        oc, self.chrome = self.chrome, None
        if oc is not None:
            try: oc.__exit__(None, None, None)
            except Exception: pass


OSM_NODE_RE = re.compile(r"^https://www\.openstreetmap\.org/node/(\d+)/?$")


def osm_node_id(url):
    m = OSM_NODE_RE.match(url or "")
    return m.group(1) if m else None


def osm_fetch(url, getter=None):
    """openstreetmap.org/node/<id> is a JS map page with no readable text: read the public API node tags instead (no login, one GET) and render them
    as the lines a listing page would show: name / street / city, state zip / phone. Never raises (t_1c503c7f)."""
    nid = osm_node_id(url)
    if not nid: return Page(0, url, "", err="not an OSM node URL")
    api = "https://api.openstreetmap.org/api/0.6/node/%s.json" % nid
    try:
        if getter: data = getter(api)
        else:
            req = urllib.request.Request(api, headers={"User-Agent": "citation-engine-recheck/1.0 (read-only)", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r: data = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return Page(e.code, url, "", err="HTTP %s" % e.code)
    except Exception as e:
        return Page(0, url, "", err=type(e).__name__)
    els = (data or {}).get("elements") or []
    if not els or els[0].get("type") != "node" or els[0].get("visible") is False: return Page(404, url, "", err="node not found or deleted")
    t = els[0].get("tags") or {}
    lines = [t.get("name", "")]
    street = " ".join(x for x in (t.get("addr:housenumber"), t.get("addr:street")) if x)
    if street: lines.append(street)
    csz = " ".join(x for x in ((t.get("addr:city") or "") + ("," if t.get("addr:city") and t.get("addr:state") else ""), t.get("addr:state"), t.get("addr:postcode")) if x)
    if csz: lines.append(csz)
    if t.get("phone"): lines.append(t["phone"])
    if t.get("website"): lines.append(t["website"])
    return Page(200, url, "\n".join(l for l in lines if l))


def get_page(url, plain=None, chrome=None, canonical=None):
    """Plain GET first. The rendered (Chrome) read when the plain page is walled, shows no block for the canonical name, or (t_03a74bae) does not read as a full
    `match`: a plain page with the name block but no street is the server-side shell of a JS listing; keeping it made a dry run and a --write run disagree
    depending on whether the plain GET happened to be good that minute. -> (page, "plain" | "chrome" | "osm")"""
    if osm_node_id(url):   # the API tags ARE the public listing; the map page has no text, so no plain/Chrome fallback
        return osm_fetch(url), "osm"
    page = (plain or plain_fetch)(url)
    if getattr(page, "limited", None) or quota_reason(page): return page, "plain"   # t_e34fc55c: a quota page or a guard refusal is final: no second route to the same site
    if not walled(page) and (canonical is None or chrome is None or compare(page.text, canonical, getattr(page, "html", None))["verdict"] == "match"):
        if canonical is None or read_block(page.text, canonical): return page, "plain"
    if chrome is None:
        return page, "plain"
    cp = chrome(url)
    return (cp if not walled(cp) or walled(page) else page), "chrome"


SEVERITY = ("mismatch", "not-public", "nap-incomplete", "unreadable")   # which non-match verdict wins when the repeat reads disagree


def read_listing(url, plain, chrome, canonical, confirm=True):
    """THE read and verdict for one listing URL (t_03a74bae). Dry run and --write both come through here, so they cannot disagree: one route choice (get_page),
    then (only for a row not yet live) one confirming read on that route. Every read must give the same verdict; a `match` needs all of them to match. Reads that disagree (a street that
    loaded late, an old and a new copy of the data) are never live: the most severe non-match wins and `unstable` lists the verdicts. -> (page, how, cmp_)"""
    page, how = get_page(url, plain, chrome, canonical)
    if getattr(page, "limited", None) or wall_reason(page):   # t_e34fc55c: a quota / wall page is never scored as a listing
        return page, how, {"verdict": "rate-limited", "wrong": [], "gaps": [], "nap": None, "why": getattr(page, "limited", None) or wall_reason(page)}
    cmp_ = compare(page.text, canonical, getattr(page, "html", None))
    if getattr(page, "unstable", None):   # t_0c4ebee8 round 1: the rendered read never settled (its NAP verdicts disagreed at the cap): the most severe non-match, never live, whatever phase the last poll was in
        vs = list(page.unstable); bad = min((v for v in vs if v != "match"), key=lambda v: SEVERITY.index(v) if v in SEVERITY else 99, default="mismatch")
        c = dict(cmp_); c["verdict"] = bad; c["unstable"] = vs
        return page, how, c
    again = {"osm": lambda: osm_fetch(url)}.get(how)   # t_0c4ebee8: the rendered route is confirmed INSIDE its one load (read_rendered waits for stable text), never by a second back-to-back load
    if again is None or not confirm or cmp_["verdict"] not in ("match", "nap-incomplete"): return page, how, cmp_   # confirm=False: a row already live is read ONCE
    reads = [(page, cmp_)]
    for _ in range(STABLE_READS - 1):
        p2 = again()
        if getattr(p2, "limited", None) or wall_reason(p2): return p2, how, {"verdict": "rate-limited", "wrong": [], "gaps": [], "nap": None, "why": getattr(p2, "limited", None) or wall_reason(p2)}
        reads.append((p2, compare(p2.text, canonical, getattr(p2, "html", None))))
    if len({c["verdict"] for _p, c in reads}) == 1: return page, how, cmp_
    bad = min((r for r in reads if r[1]["verdict"] != "match"), key=lambda r: SEVERITY.index(r[1]["verdict"]) if r[1]["verdict"] in SEVERITY else 99)
    c = dict(bad[1]); c["unstable"] = [x["verdict"] for _p, x in reads]
    return bad[0], how, c


# ---- NAP reading ----------------------------------------------------------------------------------------------------
def _digits(s): return re.sub(r"\D", "", s or "")


def phones_in(block):
    """Phones as 10 digits, from phone-shaped text only: never digits inside a longer alphanumeric token (UUID, id, hash) (t_032083dc)."""
    seen = []
    for l in block:
        if len(l) > 200: continue
        for m in F.PHONE_RE.finditer(l):
            a, b = m.start(), m.end()
            if (a > 0 and (l[a - 1].isalnum() or l[a - 1] == "_")) or (b < len(l) and (l[b].isalnum() or l[b] == "_")): continue
            sp = l.find(" ", b)
            tok = l[l.rfind(" ", 0, a) + 1:(sp if sp >= 0 else len(l))]
            tok = re.sub(r"^\w+[:=]", "", tok.strip(".,;:"))
            if HEXID_RE.match(tok) or re.search(r"[A-Za-z]", tok): continue   # an id / uuid / hash token, not a phone
            p = m.group(1) + m.group(2) + m.group(3)
            if p not in seen: seen.append(p)
    return seen


def structured_phones(html_):
    """Phone strings from tel: hrefs, JSON-LD telephone and microdata. May be masked (+127****2550)."""
    if not html_: return []
    out = []
    for m in re.finditer(r'(?i)href=["\']tel:([^"\']+)', html_): out.append(urllib.parse.unquote(m.group(1)).strip())
    for m in re.finditer(r'(?is)"telephone"\s*:\s*(\[[^\]]*\]|"[^"]*")', html_):
        out += re.findall(r'"([^"]+)"', m.group(1))
    for m in re.finditer(r'(?is)itemprop=["\']telephone["\'][^>]*>([^<]+)<', html_): out.append(m.group(1).strip())
    return [html.unescape(x) for x in dict.fromkeys(out) if re.search(r"\d", x)]


ORG_LIKE_TYPES = {"organization", "corporation", "website", "webpage", "ngo", "person", "newsmediaorganization", "educationalorganization"}   # a site's own entity, not a local business


def structured_address(html_, business_name=None, same_entity=False):
    """The listing's postal address from its own markup -> {street, city, state, zip} (missing parts absent) or None. Generic, no per-Directory code:
    schema.org JSON-LD `address` (PostalAddress) first, then the *-selector fields (street-address-selector, city-selector, ...).
    t_ff6ed622: a page can carry several PostalAddress blocks (the directory's own sitewide Organization next to the listing's entity). With `business_name`:
    the block whose enclosing entity name matches it wins; else a LocalBusiness-like entity (not Organization / WebSite); an Organization-like address is never
    used (the *-selector fields are tried, else None and the caller falls back to the text block). Without `business_name` the first block wins, as before."""
    if not html_: return None
    loose = []
    def walk(o, ctx=("", "")):
        if isinstance(o, dict):
            t, n = o.get("@type"), o.get("name")
            if t or isinstance(n, str):
                ts = [x for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)]
                ctx = (" ".join(ts) if t else ctx[0], n if isinstance(n, str) else ctx[1])
            a = o.get("address")
            if isinstance(a, dict) and a.get("streetAddress"): yield a, ctx
            elif isinstance(a, dict) and a: loose.append((a, ctx))   # a street-less block: never read as an address, but a same-name one still counts as disagreeing
            for v in o.values(): yield from walk(v, ctx)
        elif isinstance(o, list):
            for v in o: yield from walk(v, ctx)
    found = []
    for m in re.finditer(r'(?is)<script[^>]*ld\+json[^>]*>(.*?)</script>', html_):
        try: data = json.loads(html.unescape(m.group(1)).strip())
        except Exception: continue
        found += list(walk(data))
    chosen = None
    if same_entity:   # t_69102cc9: only the block whose enclosing entity IS this business (exact name). No LocalBusiness fallback, no Organization, no *-selector fields:
        # this is what may supplement a locality the page text does not show, so a directory HQ or any other entity can never stand in
        same_name = [a for a, (t, n) in found if business_name and n and exact_name(n) == exact_name(business_name)]
        a = same_name[0] if same_name else None
        if not a: return None
        if any(business_name and n and exact_name(n) == exact_name(business_name) for _a, (_t, n) in loose): return None   # a same-name block with no street disagrees with the one that has it
        def _key(x):   # t_0227a3ce: two same-name blocks must say the same street / city / state / zip, whatever their order
            st = str(x.get("addressRegion") or "").strip().lower()
            return (tuple(F._tok(str(x.get("streetAddress") or ""))), tuple(ctok(str(x.get("addressLocality") or ""))), US_STATES.get(st, st).lower(), str(x.get("postalCode") or "").strip()[:5])
        if len({_key(x) for x in same_name}) > 1: return None   # they disagree: nothing is read as this entity's address (never a match, whichever came first)
        out = {k: str(a.get(f) or "").strip() for k, f in (("street", "streetAddress"), ("city", "addressLocality"), ("state", "addressRegion"), ("zip", "postalCode"))}
        return {k: v for k, v in out.items() if v}
    if found and business_name:
        want = F._norm_name(business_name)
        is_org = lambda t: all(x.lower() in ORG_LIKE_TYPES for x in t.split())
        chosen = (next((a for a, (t, n) in found if n and F._norm_name(n) == want), None)
                  or next((a for a, (t, n) in found if t.strip() and not is_org(t)), None))
    elif found:
        chosen = found[0][0]
    if chosen:
        out = {k: str(chosen.get(f) or "").strip() for k, f in (("street", "streetAddress"), ("city", "addressLocality"), ("state", "addressRegion"), ("zip", "postalCode"))}
        return {k: v for k, v in out.items() if v}
    def sel(cls):
        m = re.search(r'(?is)<[a-z0-9]+[^>]*class="[^"]*\b%s-selector\b[^"]*"[^>]*>(.*?)</[a-z0-9]+>' % cls, html_)
        return " ".join(html.unescape(re.sub(r"(?s)<!--.*?-->|<[^>]+>", " ", m.group(1))).split()) if m else ""
    out = {"street": sel("street-address"), "city": sel("city"), "state": sel("state"), "zip": sel("zip-code")}
    out = {k: v for k, v in out.items() if v}
    return out if out.get("street") else None


def masked_match(shown, want10):
    """True/False: do the visible leading and trailing digits of a masked phone agree with the canonical phone. None when not masked."""
    m = MASKED_NUM_RE.search(shown or "")
    if not m: return None
    pre, suf = _digits(m.group(1) or m.group(3)), _digits(m.group(2) or "")
    if not suf and len(pre) < 6: return False   # trailing stars only: need most of the number visible before it counts as the same phone
    return any(full.startswith(pre) and full.endswith(suf) and len(pre) + len(suf) < len(full) for full in (want10, "1" + want10))


def read_block(text, canonical):
    """The listing's own lines: from the first short line carrying the canonical name to the next stop marker. [] when no such line."""
    lines = [l.strip() for l in (text or "").replace("\r", "").split("\n") if l.strip()]
    want, want_x = F._norm_name(canonical["name"]), exact_name(canonical["name"])
    fuzzy, exact_blocks = None, []
    for i, l in enumerate(lines):
        if len(l) > 120: continue
        l2 = re.sub(r"^\d+\.\s*", "", l)
        if NOTFOUND_RE.match(l2): continue   # "We couldn't find 'Name'" is a not-found page quoting our name, not a listing
        if exact_name(l2) == want_x:   # an exact line wins over a near miss
            exact_blocks.append(_block_from(lines, i, l2)); continue
        shown = fuzzy is None and near_miss(l2, canonical["name"])
        if shown:
            fuzzy = _block_from(lines, i, shown)   # near miss (typo): still read, compare() reports name as the mismatch
    if exact_blocks:   # the name also shows in breadcrumbs / titles (freelistingusa): take the first occurrence whose block carries the NAP
        has_nap = lambda b: phones_in(b) or MASKED_NUM_RE.search("\n".join(b)) or F.street_in(b)
        hit = next((b for b in exact_blocks if has_nap(b)), None)
        if hit: return hit
        # the name line sits above a "Claim this listing" panel and the NAP follows it (freelistingusa): read past the claim marker, still stopping at other sections
        for i, l in enumerate(lines):
            if len(l) <= 120 and exact_name(re.sub(r"^\d+\.\s*", "", l)) == want_x:
                ext = [l]
                for l3 in lines[i + 1:i + 40]:
                    if F.STOP_RE.match(l3) and not re.match(r"(?i)claim ", l3): break
                    ext.append(l3)
                if has_nap(ext): return ext
        return exact_blocks[0]
    return fuzzy or []


def near_miss(line, name, threshold=0.85):
    """The text of `line` that reads like `name` with a typo / dropped word, or None. A different business is not a near miss (ratio too low).
    Also tries the tail of a run-together line (breadcrumbs render as 'HomeKYTownCategoryName'). Returns the name-sized text, not the whole line."""
    import difflib
    w = exact_name(name); x = exact_name(line)
    if not w or not x: return None
    if w in x and len(x) <= len(w) + 12: return line
    for cand, orig in ((x, line), (x[-(len(w) + 2):], line[-(len(w) + 4):].strip())):
        r = difflib.SequenceMatcher(None, w, cand).ratio()
        # close spelling, or most of the name's words (a dropped word) with a still-similar string; a different business fails both
        if r >= threshold or (r >= 0.7 and len(line) <= 90 and L._name_hit(line, name)):
            out = orig if len(orig) <= len(name) + 12 and orig is line else orig[-(len(name) + 6):].strip()
            return re.sub(r"^[a-z]+(?=[A-Z])", "", out)   # drop a cut-off word fragment ("oachesSenior Care ...")
    return None


NOTFOUND_RE = re.compile(r"(?i)^(we (could not|couldn'?t|can'?t) find|no (results|listings?|businesses) (found|for|match)|sorry,? (we|no)|nothing (found|matched)|0 results|your search .{0,60}(did not|didn'?t) match)")


def exact_name(s):
    """Name as compared for a citation match: case, whitespace and &/&amp;/and only. A typo ('Consltng'), a dropped word or 'LLC' is a different name (t_d7a907d5)."""
    s = html.unescape(s or "").lower().replace("&", " and ")
    s = re.sub(r"\band\b", " ", s)
    return " ".join(s.split())


def _block_from(lines, i, first):
    out = [first]
    for l3 in lines[i + 1:]:
        if F.STOP_RE.match(l3): break
        out.append(l3)
        if len(out) > 120: break
    return out


LOGIN_URL_RE = re.compile(r"(?i)/(log-?in|sign-?in|signin|auth)([/?.#]|$)")


def not_public(page, how):
    """Why a CLEANLY RENDERED page without our listing block is `not-public` (login redirect, 404, 'we couldn't find', an add form), else None.
    Walls, errors and unrendered/too-short reads stay unreadable. Only the rendered (Chrome) route or an explicit 404/410 can say it."""
    if page.err or WALL_RE.search((page.text or "")[:4000]): return None
    if page.status in (404, 410): return "HTTP %s" % page.status
    if how != "chrome" or page.status != 200 or len((page.text or "").strip()) < 50: return None
    if LOGIN_URL_RE.search(urlparse(page.url or "").path): return "redirected to a login page"
    t = page.text
    if re.search(r"(?i)\b404\b|page (could )?not (be )?found|doesn'?t exist", t[:600]): return "page not found"
    if NOTFOUND_RE.search(t) or re.search(r"(?im)^we (could not|couldn'?t|can'?t) find|no results found", t): return "not found in the Directory"
    return "rendered page has no listing for this business"


PROSE_ADDR_RE = re.compile(r"(?<![\w#])(\d{1,6}\s+[A-Za-z0-9][A-Za-z0-9 .'\-]{1,40}?),?\s+([A-Za-z][A-Za-z .'\-]{1,30}?),?\s+([A-Z]{2})\.?,?\s+(\d{5})(?:-\d{4})?(?!\d)")


def prose_street(block, canonical):
    """A street that sits inside a sentence or a contact list, not on its own line (listyourbusiness shows it only in the About text and the contact list).
    Looks for '<number> <street words>, <city>, <ST> <zip>' in the block's lines and returns what street_in returns: (shown, parsed, zip) or None.
    Only a hit whose city, state and zip are the canonical ones counts; a street in a sentence about another place is not ours (t_6b1e01ff)."""
    cparts = [p.strip() for p in (canonical.get("address") or "").split(",")]
    cst_zip = re.search(r"\b([A-Z]{2})\s+(\d{5})\b", canonical.get("address") or "")
    ccity = ctok(cparts[1], True) if len(cparts) > 1 else []
    for l in block:
        for m in PROSE_ADDR_RE.finditer(l):
            street, city, st, zp = m.group(1).strip(" ,"), m.group(2).strip(), m.group(3), m.group(4)
            if cst_zip and (st != cst_zip.group(1) or zp != cst_zip.group(2)): continue
            if ccity and not city_same(city, ccity): continue
            p = F.parse_street(street)
            if p and p["num"].lstrip("0") and p["type"]: return street + ", " + city + ", " + st + " " + zp, p, zp
    return None


_CITY_ABBR = {"saint": "st", "fort": "ft", "mount": "mt"}
_STATE_WORDS = set(US_STATES) | {v.lower() for v in US_STATES.values()}
_STATE_ABBRS = {v.upper() for v in US_STATES.values()}


def ctok(s, canon=False):
    """A city as comparable tokens: ALL words; case, punctuation, hyphens and apostrophes ignored; Saint = St, Fort = Ft, Mount = Mt (t_0227a3ce: one comparator for every city check)."""
    out = [_CITY_ABBR.get(t, t) for t in F._tok(re.sub(r"['\u2019\-]", " ", html.unescape(s or "")))]
    if canon:   # the canonical address part may be "City ST 40000" (no comma before the state): drop the trailing zip and state, keep every city word
        while out and re.fullmatch(r"\d{5}(\d{4})?", out[-1]): out.pop()
        if len(out) > 1 and out[-1].upper() in _STATE_ABBRS: out.pop()
    return out


def city_same(shown, want, tail_ok=False):
    """True when the WHOLE shown city equals the canonical city (a first word alone never counts: Fort Wayne != Fort Worth). `shown` / `want` are text or ctok lists.
    tail_ok: the shown text may end with a state name / abbreviation and / or a ZIP (one run of text such as "Exampleton KY 40000"); nothing else may follow."""
    a, b = (shown if isinstance(shown, list) else ctok(shown)), (want if isinstance(want, list) else ctok(want, True))
    if not a or not b or a[:len(b)] != b: return False
    rest = [t for t in a[len(b):] if not re.fullmatch(r"\d{5}(\d{4})?", t)]
    return not rest or (tail_ok and " ".join(rest) in _STATE_WORDS)


def vis_state(line):
    """The state a visible locality line names -> upper-case abbreviation or None. 2-letter in ANY case ("Exampleton, tn") when upper-case or a real state; else a full name."""
    m = re.search(r"(?<![A-Za-z])([A-Za-z]{2})\.?(?=\s+\d{5}\b|\s*$)", line)
    if m and (m.group(1).isupper() or m.group(1).upper() in _STATE_ABBRS): return m.group(1).upper()
    fm = re.search(r"(?i)(?<![A-Za-z])(" + "|".join(sorted(US_STATES, key=len, reverse=True)) + r")(?![A-Za-z])", line)
    return US_STATES[fm.group(1).lower()] if fm else None


def strip_locality_tail(line):
    """The city words of a visible locality line: the part before the first comma, minus a ZIP and minus a state that is the LAST token (full name in any case, or a
    2-letter real abbreviation in any case). Never a leading / middle word: St, Mt, El, La, Le, De are city words (t_d64aefb4)."""
    if "," in line: return line.split(",")[0].strip(" .")   # a comma ends the city: strip nothing from what is before it
    s = line
    s = re.sub(r"\s*\b\d{5}(-\d{4})?\b\s*$", " ", s).strip(" .")
    m = re.search(r"(?i)(?<![A-Za-z])(" + "|".join(sorted(US_STATES, key=len, reverse=True)) + r")\.?\s*$", s)
    if m: return s[:m.start()].strip(" .")   # a state / zip-only line (\"KY 40000\") has no city words at all
    m = re.search(r"(?<![A-Za-z])([A-Za-z]{2})\.?\s*$", s)
    if m and m.group(1).upper() in _STATE_ABBRS: return s[:m.start()].strip(" .")
    return s


def canon_state_zip(addr):
    """State and ZIP of the canonical address, parsed from the WHOLE string ("street, City, ST zip" and "street, City ST zip" alike). (None, None) when the state cannot be
    read: callers treat the locality as unverifiable, never as 'skip the check'."""
    m = re.search(r"\b([A-Za-z]{2})\.?\s*(\d{5})?(?:-\d{4})?\s*$", (addr or "").strip())
    return (m.group(1).upper(), m.group(2)) if m and m.group(1).upper() in {v.upper() for v in US_STATES.values()} else (None, None)   # "Dr" is not a state


def compare(text, canonical, html_=None):
    """-> {"verdict": match|mismatch|nap-incomplete|not-public|unreadable, "wrong": [(field, shown)], "gaps": [field], "nap": "name | street | phone"}. Pure.
    nap-incomplete (was `gap`, t_f707b644): the page exists but a field is missing or hidden, or the page says the listing is paused / not public yet. A shown value that is wrong is `mismatch`."""
    block = read_block(text, canonical)
    if not block:
        if UNLISTED_RE.search(text or ""):   # t_3ac43137: "HIDDEN until ACTIVATED" with nothing parseable is a page that exists but is not public: nap-incomplete, not unreadable
            return {"verdict": "not-public", "wrong": [], "gaps": ["listing visibility"], "nap": None}
        return {"verdict": "unreadable", "wrong": [], "gaps": [], "nap": None}
    wrong, gaps = [], []
    segs, zfirst = [], None   # t_f2bc28d2: set in the street-match branch below; read at the end to quote the city/state/zip line in the proof
    if exact_name(block[0]) != exact_name(canonical["name"]):
        wrong.append(("name", block[0]))   # 'Senior Care Consltng Solutions' is not our name (t_d7a907d5)
    want_phone = _digits(canonical["phone"])[-10:]
    shown, masked_ok, masked_txt, phone_bad = phones_in(block), False, None, False
    struct = structured_phones(html_)   # structured data first: JSON-LD telephone, tel: hrefs, microdata
    if struct:
        full = [_digits(x)[-10:] for x in struct if not MASKED_NUM_RE.search(x) and len(_digits(x)) >= 10]
        if want_phone in full: shown = [want_phone]
        elif full: shown = full
        else:
            res = [(x, masked_match(x, want_phone)) for x in struct if MASKED_NUM_RE.search(x)]
            if res and all(r for _x, r in res): shown, masked_ok, masked_txt = [], True, res[0][0]
            elif res: wrong.append(("phone", next(x for x, r in res if not r))); phone_bad = True
    if masked_ok or phone_bad:
        pass
    elif shown:
        bad = [p for p in shown if p != want_phone]
        if bad: wrong.append(("phone", F.fmt_phone(bad[0])))
        elif want_phone not in shown: gaps.append("phone")
    else:
        mk = next((m for l in block if len(l) <= 200 for m in [MASKED_NUM_RE.search(l)] if m), None)
        if mk:
            if masked_match(mk.group(0), want_phone): masked_ok, masked_txt = True, mk.group(0)
            else: wrong.append(("phone", mk.group(0)))
        else:
            hidden = any(MASKED_PHONE_RE.search(l) for l in block if len(l) <= 200)
            plus = None if hidden else next((m.group(0).strip() for l in block for m in [PLUS_PHONE_RE.search(l)] if m and len(l) <= 200), None)
            if plus: wrong.append(("phone", plus))
            else: gaps.append("phone")
    cstreet = F.parse_street(canonical["address"].split(",")[0])
    got = F.street_in(block) or prose_street(block, canonical)
    sa_used = False
    if not got:
        sa = structured_address(html_, canonical["name"])   # t_5871cdf9: the address is in the page's own markup (JSON-LD / *-selector fields), not in the text block
        p = F.parse_street(sa["street"]) if sa and sa.get("street") else None
        if p:
            cparts = [x.strip() for x in canonical["address"].split(",")]
            cst_s, cst_z = canon_state_zip(canonical["address"])
            missing = [k for k in ("city", "state", "zip") if not sa.get(k)]
            if missing or not cst_s: gaps.append("address")   # a street alone is not the full canonical NAP; an unreadable canonical state is unverifiable, never skipped
            else:
                if len(cparts) >= 2 and not city_same(sa["city"], cparts[1]): wrong.append(("city", sa["city"]))
                sst = US_STATES.get(sa["state"].strip().lower(), sa["state"]).upper()   # JSON-LD addressRegion may be the full name ("Kentucky")
                if sst != cst_s: wrong.append(("state", sa["state"]))
                if cst_z and sa["zip"][:5] != cst_z: wrong.append(("zip", sa["zip"]))
            sa_used = True
            got = (sa["street"] + ((", %s, %s %s" % (sa["city"], sa["state"], sa["zip"])) if not missing else ""), p, sa.get("zip") if not missing else None)
    if got and cstreet:
        czip = re.search(r"\b(\d{5})\b", canonical["address"])
        street_txt_norm = " ".join(F._tok(re.sub(r"\s[\u00b7|\u2022]\s", ", ", got[0])))   # t_3f38d45e: "street · city" / "street | city" is a separator, only between street and city
        want_norm = " ".join(F._tok(canonical["address"].split(",")[0]))
        # exact street: number, name, type (Drive/Dr only) and unit via street_equal; "street + city on one line" must continue with the city, not extra words
        ccity = ctok(canonical["address"].split(",")[1], True) if canonical["address"].count(",") >= 1 else []
        rest = street_txt_norm[len(want_norm):].split() if street_txt_norm.startswith(want_norm + " ") or street_txt_norm == want_norm else None
        if rest is None:   # "100 Example Dr 40000 Exampleton Kentucky": the street is spelled Dr / Drive; compare the first words as a street
            _w = street_txt_norm.split(); _n = len(want_norm.split())
            _p = F.parse_street(" ".join(_w[:_n])) if len(_w) > _n else None
            if _p and F.street_equal(_p, cstreet) and re.fullmatch(r"\d{5}", _w[_n]): rest = _w[_n:]
        same = F.street_equal(got[1], cstreet) or (rest is not None and (not rest or (bool(ccity) and [_CITY_ABBR.get(x, x) for x in rest][:len(ccity)] == ccity) or bool(re.fullmatch(r"\d{5}", rest[0]))))   # one line: street + city (or street + zip + city)
        if same and rest is None and cstreet.get("type") and got[1].get("type") != cstreet["type"]: same = False   # exact: Drive == Dr only; a dropped type is a different street
        if not same or (got[2] and czip and got[2] != czip.group(1)):
            wrong.append(("address", got[0] if (got[2] or "") in got[0] else got[0] + ((" " + got[2]) if got[2] else "")))
        elif not sa_used and canonical["address"].count(",") >= 1:
            # t_11f5b2b0: the street matched. When the SAME line continues "street, City[, ST zip]" the city, state and zip must be the canonical ones too
            # (as the structured_address path does): wrong city -> mismatch, city without state/zip -> nap-incomplete.
            # The city / state / zip may also sit on the 1-2 lines UNDER the street ("100 Example Drive\nCity, ST zip", "...\nCity\nST zip", "..., 40000\nCity").
            segs = [x.strip() for x in re.sub(r"\s[\u00b7|\u2022]\s", ", ", got[0]).split(",")][1:]
            segs = [x for x in segs if x]
            _ft = re.sub(r"\s[\u00b7|\u2022]\s", ", ", got[0]).split(",")[0].split()
            _wn = len(want_norm.split())
            _pp = F.parse_street(" ".join(_ft[:_wn])) if len(_ft) > _wn else None
            if len(_ft) > _wn and (F._tok(" ".join(_ft[:_wn])) == want_norm.split() or (_pp and F.street_equal(_pp, cstreet))) and (re.match(r"\d{5}(-\d{4})?\s+[A-Za-z]", " ".join(_ft[_wn:])) or not F.parse_street(" ".join(_ft[_wn:]))):   # "100 Example Dr 40000 Exampleton Kentucky": zip before the city, no commas
                segs = [" ".join(_ft[_wn:])] + segs   # no comma after the street: "100 Example Drive Exampleton, KY 40000"
            zip_only = lambda x: re.fullmatch(r"\d{5}(-\d{4})?", x)
            zfirst = None
            zc = re.fullmatch(r"(\d{5})(?:-\d{4})?\s+([A-Za-z].*)", segs[0]) if segs else None
            if zc: zfirst, segs = zc.group(1), [zc.group(2)] + segs[1:]   # "100 Example Drive,  40000 Exampleton": zip before the city (a live listing shape)
            st_only = lambda x: re.fullmatch(r"[A-Za-z]{2}\.?(\s+\d{5}(-\d{4})?)?", x)
            no_city = lambda ss: not ss or bool(zip_only(ss[0]) or st_only(ss[0]))
            i0 = next((i for i, l in enumerate(block) if l and got[0].startswith(l) and F.parse_street(l)), None)
            if no_city(segs) and i0 is not None:
                j = i0 + 1 + (0 if got[0] == block[i0] else 1)   # a unit on its own line was appended to the shown street
                _sn = re.compile(r"(?i)(?<=[\s,])(" + "|".join(sorted(US_STATES, key=len, reverse=True)) + r")(?=\s+\d{5}\b|\s*$)")
                _own = re.compile(r"(?i)(" + "|".join(sorted(US_STATES, key=len, reverse=True)) + r")(\s+\d{5}(?:-\d{4})?)?")
                _own_ab = lambda x: (lambda m: US_STATES[m.group(1).lower()].upper() + (m.group(2) or "") if m else None)(_own.fullmatch(x.strip()))   # "Ohio 40000" alone on a line -> "OH 40000" (t_936ab977)
                _ab = lambda x: _sn.sub(lambda m: US_STATES[m.group(1).lower()], x) if "," in x else x   # "Exampleton, Ohio 40000" -> "Exampleton, OH 40000"
                n1 = _ab(block[j]) if j < len(block) else ""
                n2 = _ab(block[j + 1]) if j + 1 < len(block) else ""
                n2s = _own_ab(n2) or n2   # only the "ST zip" slot after the city line may hold a bare full state name; never n1 (a city can be New York / Indiana)
                ok_ln = lambda x: bool(x) and len(x) <= 60 and not phones_in([x])
                szr = lambda x: ok_ln(x) and bool(F.STATE_ZIP_RE.search(x)) and not F.parse_street(x)
                alpha = lambda x: ok_ln(x) and bool(re.fullmatch(r"[A-Za-z][A-Za-z .'\-]*", x)) and len(x.split()) <= 4
                n3 = block[j + 2] if j + 2 < len(block) else ""
                st_line = lambda x: ok_ln(x) and (x.lower().strip(" .") in US_STATES or bool(re.fullmatch(r"[A-Z]{2}\.?", x)))
                if zip_only(n1.strip()) and alpha(n2) and st_line(n3) and not segs:   # street / zip / city / state, one per line (a live listing shape)
                    zfirst, segs = n1.strip()[:5], [n2.strip(), n3.strip()]
                elif szr(n1) and not zip_only(n1.strip()): segs = [x.strip() for x in n1.split(",") if x.strip()]   # "City, ST zip"
                elif alpha(n1) and szr(n2s) and not alpha(n2s):
                    s2 = [x.strip() for x in n2s.split(",") if x.strip()]
                    segs = ([n1.strip()] + s2) if no_city(s2) else s2   # "City" / "ST zip"; "Website" / "City, ST zip" (a UI label above the city line is skipped)
                elif alpha(n1) and segs and zip_only(segs[0]): segs = [n1.strip()] + segs   # "street, 40000" / "City" (only the canonical city: another letters-only line may be a UI label)
                elif alpha(n1) and not segs and ccity and city_same(n1, ccity): segs = [n1.strip()]   # canonical city alone under the street: no state / zip
            if no_city(segs):
                gaps.append("address")   # street alone, or street + zip / state with no city anywhere near it
            else:
                cst2 = re.search(r"\b([A-Za-z]{2})\b\s*(\d{5})?\s*$", canonical["address"].strip())
                city_tok = ctok(segs[0])
                tail = " ".join(segs)
                sm = re.search(r"(?<![A-Za-z])([A-Za-z]{2})\.?,?\s+\d{5}\b", tail) or re.search(r"(?<![A-Za-z])([A-Z]{2})\s*$", tail)
                state = sm.group(1) if sm and sm.lastindex else None
                if not state:   # full state name: "Exampleton, Kentucky - 40000"
                    fm = re.search(r"(?i)\b(" + "|".join(sorted(US_STATES, key=len, reverse=True)) + r")\b", " ".join(segs[1:]))
                    state = US_STATES[fm.group(1).lower()] if fm else None
                    if state is None and len(city_tok) > 1 and city_tok[-1] in US_STATES: state = US_STATES[city_tok[-1]]   # "Exampleton Kentucky" with no comma
                if not city_same(city_tok, ccity, tail_ok=True): wrong.append(("city", segs[0]))
                else:
                    if cst2 and state and state.upper() != cst2.group(1).upper(): wrong.append(("state", state))
                    if zfirst and cst2 and cst2.group(2) and zfirst != cst2.group(2): wrong.append(("zip", zfirst))
                    if cst2 and ((not state and not got[2] and not zfirst) or (cst2.group(2) and not got[2] and not zfirst)) and not wrong: gaps.append("address")   # a shown, equal zip stands in for the state ("100 Example Drive, 40000" / "Exampleton")
    elif not got:
        gaps.append("address")
    if got and cstreet and not sa_used and "address" in gaps and html_ and canonical["address"].count(",") >= 1 and not any(f in ("address", "city", "state", "zip") for f, _v in wrong):
        # t_69102cc9: the text shows the canonical street but not (all of) the locality. The SAME business entity's own JSON-LD address (name == canonical name; never an
        # Organization / directory HQ / other entity) may supply what is genuinely missing, only when its street equals the canonical street. What the text DID show
        # (zip, state) must still equal canonical: a visible wrong value is a mismatch and structured data never overrides it. Structured values are checked like the
        # structured path does: wrong city / state / zip -> mismatch; a part still missing -> the gap stays (nap-incomplete).
        ent = structured_address(html_, canonical["name"], same_entity=True)
        esp = F.parse_street(ent["street"]) if ent and ent.get("street") else None
        # Visible locality on the 1-2 lines UNDER the street (and a zip-first third line) is read too: a wrong visible city / state / zip is a mismatch and structured
        # data never overrides it; a letters-only line there that is not the canonical city blocks the supplement (stays nap-incomplete, never match).
        under_blocked = not all(canon_state_zip(canonical["address"]))   # unreadable canonical state / ZIP: unverifiable, never "skip the check" -> no supplement
        if esp and i0 is not None:
            _cp = [x.strip() for x in canonical["address"].split(",")]
            _cs_s, _cs_z = canon_state_zip(canonical["address"])
            if not (_cs_s and _cs_z): under_blocked = True   # canonical state / ZIP unreadable: cannot verify, no supplement
            _cc = ctok(_cp[1], True) if len(_cp) >= 2 else []
            _j = i0 + 1 + (0 if got[0] == block[i0] else 1)
            _sn2 = "|".join(sorted(US_STATES, key=len, reverse=True))
            _un = []
            for _k in range(_j, min(_j + 3, len(block))):
                _l = block[_k]
                _zf = re.match(r"\d{5}(-\d{4})?\s+[A-Za-z]", _l) is not None   # zip-first locality "40000 City[, ST]": parse_street reads it as number+name, but with no street type it is not a street
                _ps = F.parse_street(_l)
                if not _l or len(_l) > 60 or phones_in([_l]) or (_ps and not (_zf and not _ps.get("type"))): break
                _un.append(_l.strip())
                if _k - _j >= 1 and not re.fullmatch(r"\d{5}(-\d{4})?", _un[0]): break   # 2 lines, unless the first is a bare zip (street / zip / city / state)
            for _l in _un:
                _zs = re.findall(r"(?<!\d)(\d{5})(?:-\d{4})?(?!\d)", _l)
                _ab = vis_state(_l)   # t_0227a3ce: a 2-letter state in any case ("Exampleton, tn") or a full name
                if _zs or _ab:
                    if _ab and _cs_s and _ab.upper() != _cs_s: wrong.append(("state", _ab))
                    if _zs and _cs_z and _zs[0] != _cs_z: wrong.append(("zip", _zs[0]))
                    _cityp = strip_locality_tail(_l)   # t_d64aefb4: only a TRAILING state / zip is dropped; St / Mt / El / La stay city words
                    _ct = ctok(re.sub(r"[^A-Za-z .'\-]", " ", _cityp))
                    if _ct and _cc and not city_same(_ct, _cc): wrong.append(("city", _cityp.strip()))
                elif re.fullmatch(r"[A-Za-z][A-Za-z .'\-]*", _l) and len(_l.split()) <= 4 and _cc and not city_same(_l, _cc):
                    under_blocked = True
        if wrong or under_blocked: esp = None
        if esp and F.street_equal(esp, cstreet) and all(ent.get(k) for k in ("city", "state", "zip")):
            cparts = [x.strip() for x in canonical["address"].split(",")]
            cst_s, cst_z = canon_state_zip(canonical["address"])
            if not (cst_s and cst_z): esp = None   # unreadable canonical state / ZIP: unverifiable, no supplement
            vz, vs = zfirst or (got[2] if got else None), None   # fragments the page text showed
            for x in segs:
                m = re.fullmatch(r"([A-Za-z]{2})\.?(?:\s+(\d{5})(?:-\d{4})?)?", x.strip())
                z = re.fullmatch(r"(\d{5})(?:-\d{4})?", x.strip())
                if not m and x.strip().lower() in US_STATES: vs = US_STATES[x.strip().lower()]   # a full state name alone ("Ohio") is read too
                if m: vs, vz = m.group(1), vz or m.group(2)
                elif z: vz = vz or z.group(1)
            n0 = len(wrong)
            if vs and vs.upper() != cst_s: wrong.append(("state", vs))
            if vz and vz[:5] != cst_z: wrong.append(("zip", vz))
            if len(wrong) == n0:
                if len(cparts) >= 2 and not city_same(ent["city"], cparts[1]): wrong.append(("city", ent["city"]))
                est = US_STATES.get(ent["state"].strip().lower(), ent["state"]).upper()
                if est != cst_s: wrong.append(("state", ent["state"]))
                if ent["zip"][:5] != cst_z: wrong.append(("zip", ent["zip"]))
                if len(wrong) == n0:
                    gaps.remove("address"); sa_used = True
                    got = ("%s, %s, %s %s" % (ent["street"], ent["city"], ent["state"], ent["zip"]), got[1], ent["zip"])
    street_txt = got[0] if got else None
    if got and segs and not sa_used and segs[0] not in got[0]:   # t_f2bc28d2: street and city/state/zip on separate lines -> quote both (display only; verdict logic unchanged)
        _zr = r"\b\d{5}(?:-\d{4})?\b"
        _zs = re.search(r"[,\s]+(\d{5}(?:-\d{4})?)$", got[0])
        _z = zfirst or (_zs.group(1) if _zs else None)
        _st = got[0][:_zs.start()] if _zs else got[0]
        _parts = []
        for _s in segs:   # each part once: pull any zip out, re-attach it after the state ("City, ST zip")
            _m = re.search(_zr, _s)
            if _m: _z = _z or _m.group(0)
            _s = re.sub(r"\s+", " ", re.sub(_zr, "", _s)).strip(" ,-")
            if _s: _parts.append(_s)
        if _z and len(_parts) > 1: _parts[-1] += " " + _z
        elif _z: _parts.append(_z)
        street_txt = ", ".join([_st] + _parts)
    nap = " | ".join(x for x in (canonical["name"], street_txt, F.fmt_phone(shown[0]) if shown else masked_txt) if x)
    if ADDR_NOT_LISTED_RE.search("\n".join(block)) and "address" not in gaps and not got: gaps.append("address")
    if UNLISTED_RE.search(text or "") and "listing visibility" not in gaps: gaps.append("listing visibility")   # paused / hidden: not public yet even if the NAP shown matches
    verdict = "not-public" if "listing visibility" in gaps else "mismatch" if wrong else "nap-incomplete" if gaps else "match"   # a hidden/paused banner wins, even on a partial parse (t_3ac43137)
    return {"verdict": verdict, "wrong": wrong, "gaps": gaps, "nap": nap, "masked": masked_ok}


def note_for(cmp_):
    parts = ["%s shows %s" % (f, v) for f, v in cmp_["wrong"]] + [("listing is paused or not public yet" if f == "listing visibility" else "%s not shown on the public page (hidden or missing)" % f) for f in cmp_["gaps"]]
    return "weekly recheck: " + "; ".join(parts)


# ---- queue ------------------------------------------------------------------------------------------------------------
# Pages that are the way INTO a Directory (add / register / claim / thank-you / lookup / the bare homepage), never the listing itself. A row's
# evidence_url often holds one of these (brownbook /add-business, showmelocal /, dnb lookup, discoverourtown thankyou.php) while the real
# listing lives in listing_url. Reading the form page was the "unreadable" of batch 8 (t_560dd259).
ENTRY_RE = re.compile(r"(?i)/(add|add-?business|add-?listing|add_listing|submit|register|signup|sign-up|claim|get-listed|thank-?you[^/]*|lookup|listing\.php|create-listing|payment(\.php)?|checkout|submission|dashboard|account|businesses/new)([/?#.]|$)|thankyou|[?&]flow=lookup")


def _is_entry_page(url):
    from urllib.parse import urlparse
    p = urlparse(url)
    return (not p.path.strip("/") and not p.query) or bool(ENTRY_RE.search(p.path + ("?" + p.query if p.query else "")))


def _permalink(row):
    d = row.get("directory")
    import listing_capture as LC
    for k in ("listing_url", "evidence_url"):   # t_3ac43137: an owner-view URL with a known pattern becomes its PUBLIC url (never read signed in)
        pub = LC.public_url(d, row.get(k))
        if pub and L.is_permalink(d, pub): return pub
    for k in ("evidence_url", "listing_url"):   # evidence first; fix-bing keeps its Bing Maps permalink in listing_url, bingplaces.com is not a listing
        u = row.get(k)
        if u and L.is_permalink(d, u) and not _is_entry_page(u): return u
    return None


def _bbb_search_url(ident, biz="SCC"):
    x = ident["BIZ"][biz]
    return "https://www.bbb.org/search?find_text=%s&find_loc=%s" % (quote(x["name"]), quote("%s, %s" % (x["city"], x["st"])))


def resolve_bbb(page, ident, biz="SCC"):
    """Profile URL from a bbb.org search page: a /profile/ link whose card names the business. None when absent."""
    x = ident["BIZ"][biz]
    url, kind = L.resolve("bbb.org", page.url, page.links, x["name"], x.get("phones") or ())
    return url if (url and kind == "listing" and "/profile/" in url) else None


RECHECK_SEARCH = {
    "localsolution.com": lambda x: "https://www.localsolution.com/businesses?q=%s&geo=%s" % (quote(x["name"]), quote("%s, %s" % (x["city"], x["st"]))),
    "listyourbusiness.us": lambda x: "https://listyourbusiness.us/businesses?q=%s" % quote(x.get("short") or x["name"]),
}


def search_url_for(directory, ident, biz="SCC", cat_rows=None):
    """Name + city search URL on the Directory itself: the create-discovery builder, else the Catalog template ({name},{short},{city},{st}). None when neither exists."""
    from urllib.parse import quote_plus as qp
    x = ident["BIZ"][biz]
    if directory in RECHECK_SEARCH:   # t_3ac43137: Directories whose public search is known but not in the create-discovery table
        return RECHECK_SEARCH[directory](x)
    try:
        import create_discovery as CD
        cfg = CD.CREATE_DIRS.get(directory)
        if cfg and cfg.get("search"): return cfg["search"](x["name"])
    except Exception:
        pass
    if cat_rows is None:
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "db", "directories_seed.json"), encoding="utf-8") as f: cat_rows = {r["domain"]: r for r in json.load(f)}
        except Exception:
            cat_rows = {}
    tpl = (cat_rows.get(directory) or {}).get("search_url_template")
    if not tpl: return None
    return tpl.replace("{name}", qp(x["name"])).replace("{short}", qp(x.get("short") or x["name"])).replace("{city}", qp(x["city"])).replace("{st}", qp(x["st"]))


# Directories whose listing page has NO public source (t_bbc32230). The row is reported, never fetched, never live, never retried by a run.
# foursquare.com: every /v/ URL 302s to /login signed out, and every Places endpoint (api.foursquare.com v2/v3, places-api.foursquare.com) answers
# 400/401 without an API key (an account). A signed-in read is not allowed: the Bing false live came from one.
NO_SEARCH = ("dnb.com", "discoverourtown.com")   # t_8d1865a3: the lookup's no-search rows (job/lookup.py SEARCH has url=None); the report says so


UNREADABLE_PUBLIC = {
    "foursquare.com": "no public source: foursquare.com/v redirects to /login and the Places API needs a key; row is never counted live by recheck",
}


def search_log(search_url, page, how, found):
    """One line for the report: the search URL (no query string value beyond the host/path), HTTP status, how it was read, link count, result. Never page text."""
    p = urlparse(search_url)
    return "searched %s%s via %s: status %s, %d links, %s" % (p.netloc, p.path, how, getattr(page, "status", None), len(getattr(page, "links", None) or []),
                                                               "card found" if found else "no card for the business")


def resolve_by_search(directory, page, ident, biz="SCC"):
    """A listing permalink from a Directory's own search-results page: a same-host link whose card names the business (listing.resolve). None when absent."""
    x = ident["BIZ"][biz]
    url, kind = L.resolve(directory, page.url, page.links, x["name"], x.get("phones") or ())
    host = lambda u: (urlparse(u).netloc or "").lower().replace("www.", "")
    return url if (url and kind == "listing" and host(url) == host(directory if "/" in directory else "https://" + directory) and not _is_entry_page(url)) else None


def candidates(q, include_live=False, only=None, today=None, any_state=False):
    import transitions as T
    out = []
    states = WAITING + (("live",) if include_live else ())
    for _key, kind, rows in T._row_lists(q):
        for r in rows:
            if (any_state or r.get("state") in states) and r.get("directory") and (not only or r["id"] in only):
                if W.is_stopped(r):  # hard-block cap (t_fccbb7ef): a STOPPED row is not touched until Mike resets it
                    print("SKIP %s (%s): hard-block STOPPED, waiting on Mike" % (r.get("directory"), r.get("id"))); continue
                due = Q.not_due(r, today) if today else None   # t_6b1e01ff: foursquare's edit is reviewed by the Directory; t_d2f75685: citylocalpro 24h sender limit. A row NAMED with --row is read anyway.
                if due and not only:
                    print("SKIP %s (%s): recheck due %s" % (r.get("directory"), r.get("id"), due)); continue
                out.append((kind, r))
    return out


def _last_note(row):
    h = row.get("history") or []
    return (h[-1].get("note") if h and isinstance(h[-1], dict) else None)


def recheck(q, ident, *, plain=None, chrome=None, record=None, db=None, queue_path=None, today=None, write=False, include_live=False, only=None, use_chrome=True, proof_live=False, mail=None, backoff_only=False, any_state=False, guard=None, store=None, from_read=None):
    """-> list of per-row results {row, directory, url, before, after, verdict, fields, note, error}. Never raises per row.
    any_state (t_89f4aebf): read the NAMED rows (`only`) in any state, e.g. a needs-human row after a ruling. Refuses backoff / proof.
    With write (t_dca17786) it promotes a NAMED needs-human row to live when the read matches (same writer as every live write); any other verdict, and any row not needs-human, writes nothing."""
    import datetime
    if any_state:
        if backoff_only or proof_live: raise Q.QueueError("--any-state never combines with --backoff-only or --proof-live")
        if not only: raise Q.QueueError("--any-state needs --row ID (it reads named rows only)")
    day = today or datetime.date.today().isoformat()
    canonical = q.get("canonical")
    if not canonical or not all(canonical.get(k) for k in ("name", "address", "phone")):
        raise Q.QueueError("queue has no canonical name/address/phone")
    ident_phone = _digits(ident["BIZ"]["SCC"]["phones"][0])[-10:]
    if _digits(canonical["phone"])[-10:] != ident_phone:
        raise Q.QueueError("queue canonical phone differs from the approved identity; refusing to recheck")
    if record is None:
        import transitions; record = transitions.record_transition
    own_reader = None
    if use_chrome and chrome is None: chrome = own_reader = SignedOutReader(); own_reader.canonical = canonical   # t_3ac43137: a clean signed-out Chrome of its own, never 9333 / the build profile
    elif not use_chrome: chrome = None
    try:
        if guard is not None:   # t_e34fc55c: every Directory read goes through the per-domain guard (the plain and rendered routes; OSM's API is not a Directory)
            plain = guarded(plain or plain_fetch, guard, "plain")
            if chrome is not None: chrome = guarded(chrome, guard, "chrome")
        if store is not None and not store.replay:   # --save-pages: outside the guard, so a refused / quota read is saved as it was returned
            plain = store.saving(plain or plain_fetch, "plain")
            if chrome is not None: chrome = store.saving(chrome, "chrome")
        if from_read is not None:   # t_0c4ebee8: OUTSIDE the guard: a reused page makes no reservation and no load; a stale / mismatched one falls through to the guarded live read
            plain = from_read.reusing(plain or plain_fetch, "plain")
            if chrome is not None: chrome = from_read.reusing(chrome, "chrome")
        return _recheck_rows(q, ident, canonical, plain, chrome, record, db, queue_path, day, write, include_live, only, proof_live, mail, backoff_only, any_state, guard)
    finally:
        if own_reader: own_reader.close()


BACKOFF_DAYS = 2


def final_url(url, page):
    """The URL the read ended on after redirects (t_962161f4: us-info moved the slug). Same host only, http(s) only, no fragment; else the stored url stays."""
    f = (getattr(page, "url", None) or "").split("#")[0]
    try: a, b = urlparse(url), urlparse(f)
    except Exception: return url
    if b.scheme not in ("http", "https") or not b.netloc or "@" in b.netloc: return url
    if b.netloc.lower().removeprefix("www.") != a.netloc.lower().removeprefix("www."): return url
    return url if (a.path.rstrip("/"), a.query) == (b.path.rstrip("/"), b.query) else f


def _limited(page, guard, rid, res, why=None):
    """t_e34fc55c: True (and res filled) when `page` is a quota / wall page or the guard refused the read. One cooldown + one log line per wall; no row change."""
    why = why or getattr(page, "limited", None) or wall_reason(page)
    if not why: return False
    if guard is not None and not getattr(page, "limited", None):   # a guard refusal / quota hit already has its cooldown; a fresh Cloudflare wall starts one
        guard.wall(SG.domain_of(res.get("url") or page.url), why, url=page.url, row=rid)
    res["verdict"] = "rate-limited"; res["note"] = "rate-limited: " + why + " (read stopped, nothing written)"; res["error"] = None
    return True


def _backoff_decision(row, day, no_url):
    """t_baa09af1: the single rule for _backoff. Returns already-parked | not-due | park | backoff (checked in that order)."""
    import transitions as T
    if row.get("state") == "needs-human": return "already-parked"
    cur = row.get("recheck_due")
    if no_url and cur and str(cur) > day: return "not-due"
    if no_url and T.no_url_backoffs(row) >= T.MAX_NO_URL_BACKOFFS: return "park"
    return "backoff"


def _backoff(res, row, write, record, queue_path, day, note=None, no_url=False):
    """t_962161f4: a `not-public` / `unreadable-public` verdict sets recheck_due = today + BACKOFF_DAYS on the row, so a batch does not burn time on it each turn.
    Same-state note refresh on a waiting row only (transitions refuses it elsewhere); a row already live is never touched. Dry run reports the date, writes nothing."""
    import datetime, transitions as T
    due = (datetime.date.fromisoformat(day) + datetime.timedelta(days=BACKOFF_DAYS)).isoformat()
    res["recheck_due_old"] = row.get("recheck_due")   # t_8d1865a3: the report prints `old -> new` for every row it backs off
    res["recheck_due"] = due
    if row.get("state") not in T.NOTE_ONLY_STATES: return
    cur = row.get("recheck_due")
    act = _backoff_decision(row, day, no_url)   # t_baa09af1: ONE decision for the dry run and the write; they differ only in whether record() runs
    if act == "already-parked":   # a needs-human row is a no-op: no record call, no backoff, no second park entry
        res["recheck_due"] = cur; res["already_parked"] = True; res["after"] = row["state"]
        if write: res["written"] = True
        return
    if act == "not-due":   # t_8d1865a3 review: a named row read before it is due adds no counted backoff (at most one per due period); the date stays
        res["recheck_due"] = cur; res["not_due"] = True
        if write: res["written"] = True
        return
    if act == "park":   # t_8d1865a3: 3 backoffs and still no listing URL: park it, never a silent forever-submitted row
        res["after"] = "needs-human"; res["recheck_due"] = None
        if not write: res["would_park"] = "no-public-permalink"; return
        n = "no public permalink after %d backoffs (public search, mail scan); parked for a human: find the listing by hand or reject" % T.MAX_NO_URL_BACKOFFS
        record("SCC", row["id"], "needs-human", None, n, queue_path=queue_path, today=day, park_reason="no-public-permalink", reason_code="no_search")
        res["parked"] = "no-public-permalink"
        return
    if not write: return   # t_bee96b30: a plain backoff writes nothing on a dry run
    n = ((note or res.get("note") or "public read: not public")[:160]) + " (recheck due %s)" % due
    kw = {"backoff": "no-permalink"} if no_url else {}
    record("SCC", row["id"], row["state"], None, n, queue_path=queue_path, today=day, recheck_due=due, **kw)
    res["written"] = _written(queue_path, row["id"], due) if queue_path else None


def _written(queue_path, rid, due):
    """Read the queue file back: did recheck_due land on the row? (batch 21: the worker could not tell.)"""
    import transitions as T
    try: return str(T._find(T._read(queue_path), rid).get("recheck_due")) == str(due)
    except Exception: return False


def _recheck_rows(q, ident, canonical, plain, chrome, record, db, queue_path, day, write, include_live, only, proof_live, mail=None, backoff_only=False, any_state=False, guard=None):
    results = []
    bw = write or backoff_only   # t_2d15878c: a dry-run batch still moves recheck_due (backoff only, never live); t_bee96b30: it may also PARK a row (-> needs-human) after 3 no-URL backoffs
    for kind, row in candidates(q, include_live, only, day, any_state):
        d, rid, before = row["directory"], row["id"], row["state"]
        res = {"row": rid, "directory": d, "url": None, "before": before, "after": before, "verdict": None, "fields": [], "note": None, "error": None}
        results.append(res)
        parked = bool(any_state and before == "needs-human")   # t_dca17786: a NAMED parked row. Only a `match` may change it (-> live); nothing else is ever written to it
        if any_state and write and not parked:   # --any-state --write is for needs-human rows only: any other named row is not read and not touched
            res["note"] = "--any-state --write promotes needs-human rows only; this row is %s: not read, nothing written" % before; res["skipped"] = True; continue
        try:
            url = _permalink(row)
            if url is None and d == "bbb.org":
                sp, _how = get_page(_bbb_search_url(ident), plain, chrome)
                if _limited(sp, guard, rid, res): continue
                url = resolve_bbb(sp, ident)
                if url:
                    note = "weekly recheck: found the BBB profile URL"
                    if write: record("SCC", rid, before, url, note, queue_path=queue_path, today=day) if before in ("submitted", "pending-verify", "found") else None
                    res["note"] = note
            if d in UNREADABLE_PUBLIC:   # t_bbc32230: no public source exists: never fetched, never counted live, never retried
                res["url"] = url; res["verdict"] = "unreadable-public"; res["note"] = UNREADABLE_PUBLIC[d]
                _backoff(res, row, bw, record, queue_path, day); continue
            searched_ok = False
            if url is None and d != "bbb.org":   # t_d7a907d5: payment / submission evidence and no listing_url -> look the business up by name + city
                su = search_url_for(d, ident)
                if su:
                    sp, _how = get_page(su, plain, chrome)
                    if _limited(sp, guard, rid, res): continue
                    url = resolve_by_search(d, sp, ident)
                    searched_ok = not url and not walled(sp) and not sp.err and (sp.status or 0) < 400   # a readable search page with no card for us: not public
                    res["search"] = search_log(su, sp, _how, url)   # t_bbc32230: what search ran and what it got (no page text)
                    if url:
                        res["note"] = "recheck: found the listing URL by name + city search"
                        if write and before in ("submitted", "pending-verify", "found"): record("SCC", rid, before, url, res["note"], queue_path=queue_path, today=day)
            if url is None and mail is not None and d in MS.SCAN_DIRECTORIES:   # t_6b1e01ff: moderated, no account, no permalink: the approval mail carries the listing URL
                hit = mail.find(d)
                if hit:
                    url = hit["url"]
                    res["note"] = "recheck: listing URL from the approval mail at listings@ (%s)" % hit["date"]
                    res["mail"] = hit
                    # t_bbc32230: the mail URL passed the permalink gate in find_approval; transitions stores it as listing_url (not evidence), so the next recheck reads it
                    if write and before in ("submitted", "pending-verify", "found"): record("SCC", rid, before, None, res["note"], queue_path=queue_path, today=day, listing_url=url)
            if url is None:
                res["verdict"] = "not-public" if searched_ok else "no-permalink"
                if searched_ok: res["note"] = "name + city search on the Directory shows no listing for this business (%s)" % res.get("search", "")
                else: res["note"] = res.get("note") or ("no public search for this Directory; no approval mail" if d in NO_SEARCH else "no listing URL found (public search / approval mail)")
                _backoff(res, row, bw, record, queue_path, day, no_url=True)   # t_8d1865a3: EVERY row with no URL gets a date (dnb, discoverourtown had none) and counts toward the cap
                continue
            res["url"] = url
            page, how, cmp_ = read_listing(url, plain, chrome, canonical, confirm=(before != "live"))   # t_03a74bae: the one read + verdict path for dry run and --write
            if cmp_["verdict"] == "rate-limited":   # t_e34fc55c: a quota / wall page. Nothing is written, the row is not demoted, the domain cools down
                _limited(page, guard, rid, res, why=cmp_.get("why")); continue
            res["verdict"] = cmp_["verdict"]; res["fields"] = cmp_["wrong"] or cmp_["gaps"]; res["via"] = how; res["nap"] = cmp_.get("nap"); res["masked"] = bool(cmp_.get("masked"))
            if cmp_["verdict"] == "unreadable":
                why = not_public(page, how)
                if why:   # t_3ac43137: the Directory answered and nothing is published for us at this URL: a real verdict, nothing written
                    res["verdict"] = "not-public"; res["fields"] = []; res["note"] = "signed-out page shows no listing: " + why; _backoff(res, row, bw, record, queue_path, day); continue
                res["error"] = "page not readable (%s)" % (page.err or page.status); continue
            if cmp_["verdict"] == "match":
                final = final_url(url, page)   # t_962161f4: the Directory redirected to a new slug (us-info): the FINAL url is the listing url from here on
                if final != url: res["final_url"] = final
                if before == "live":   # already live: report only, unless --proof-live names the row (t_1c503c7f): Proof only, state stays live
                    if final != url:
                        res["note"] = "listing URL moved: %s -> %s" % (url, final)
                        if write: record("SCC", rid, "live", final, "weekly recheck: the Directory redirected the listing to a new URL", queue_path=queue_path, today=day, refresh_url=True)
                    if proof_live and write and only:
                        _proof_only(row, kind, final, cmp_["nap"], day, db, queue_path)
                        res["note"] = "proof written (row stays live)"
                    elif proof_live and only:
                        res["note"] = "dry run: would write proof (row stays live): %s | %s" % (final, cmp_["nap"])
                    continue
                res["note"] = "weekly recheck: listing live, NAP matches canonical"
                url = final
                if write:
                    _proof_then_live(row, kind, url, cmp_["nap"], day, db, record, queue_path, res["note"])
                res["after"] = "live"
            elif parked:   # t_dca17786: no demotion, no note, no state change: the verdict is printed and the row stays parked
                res["note"] = note_for(cmp_)
            elif before != "live":
                note = note_for(cmp_) + (" (repeat reads disagreed: %s; not counted live)" % ", ".join(cmp_["unstable"]) if cmp_.get("unstable") else ""); res["note"] = note
                if cmp_["verdict"] == "not-public":   # t_962161f4: a hidden / paused banner: back off 2 days (the same one note write carries the date)
                    _backoff(res, row, bw and note != _last_note(row), record, queue_path, day, note=note)
                elif write and note != _last_note(row):
                    record("SCC", rid, before, None, note, queue_path=queue_path, today=day)
        except Exception as e:
            res["error"] = (str(e)[:200] or type(e).__name__)
    # t_f6267312: every live row that was read gets its NAP result stored on the queue row, whatever the verdict (unread = consistent None + a reason).
    for res in results:
        if res["before"] != "live" or res.get("skipped"): continue   # t_dca17786: a row skipped unread is never touched, not even its NAP check
        if res.get("verdict") == "rate-limited": continue   # t_e34fc55c: a quota page says nothing about the NAP; the stored nap_check stays as it was
        res["nap_check"] = nap_check_from_result(res, canonical, day)
        if write and queue_path:
            try:
                import transitions as T
                T.set_nap_check(res["row"], res["nap_check"], queue_path=queue_path)
            except Exception as e:
                res["nap_check_error"] = (str(e)[:200] or type(e).__name__)
    return results


NAP_FIELD_KEY = {"name": "name", "address": "address", "phone": "phone"}


def nap_check_from_result(res, canonical, day):
    """Pure. One recheck result for a LIVE row -> {at, consistent True|False|None, fields, errors, reason}. Only a clean match is True and only a shown wrong value is False;
    everything else (page not readable, not public, a field hidden, no URL, read error) is None with a reason, never False."""
    v = res.get("verdict")
    out = {"at": day, "consistent": None, "fields": [], "errors": [], "reason": None}
    if v == "match":
        out["consistent"] = True
    elif v == "mismatch":
        out["consistent"] = False
        for f in res.get("fields") or []:
            field, shown = (f if isinstance(f, (tuple, list)) and len(f) == 2 else (f, None))
            out["fields"].append("website" if field == "site" else field)
            out["errors"].append({"field": field, "live": shown, "right": (canonical or {}).get(NAP_FIELD_KEY.get(field, field))})
    elif v == "nap-incomplete":
        out["reason"] = "listing page does not show: %s" % ", ".join(str(x) for x in (res.get("fields") or ["the full NAP"]))
    elif v == "not-public":
        out["reason"] = (res.get("note") or "listing page is not public")[:200]
    elif v == "unreadable-public":
        out["reason"] = (res.get("note") or "no public source for this Directory")[:200]
    elif v == "no-permalink":
        out["reason"] = "no listing page URL on the queue row to read"
    elif res.get("error"):
        out["reason"] = (res["error"])[:200]
    else:
        out["reason"] = "listing page could not be read (%s)" % (v or "no verdict")
    return out


def _proof_then_live(row, kind, url, nap, day, db, record, queue_path, note):
    """Proof first (a live row without Proof never counts); if the transition then fails the row stays waiting and the next run retries."""
    import datetime, directories as D, proof as PR
    db = db or D.DirDB()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    action = PR.build_action(kind, row, row.get("claim_status"))
    pf = dict(proof_url=url, proof_nap=nap, proof_at=stamp, proof_nap_match=True, build_action=action)
    out = record("SCC", row["id"], "live", url, note, queue_path=queue_path, today=day, listing_url=url, proof=pf)   # t_d660babc: Proof travels with the one live writer
    if out.get("errors"): raise RuntimeError("; ".join(out["errors"])[:200])


def _proof_only(row, kind, url, nap, day, db, queue_path=None):
    """Proof columns for a row that is already live and whose signed-out read matched on every stable read. No state change."""
    import datetime, directories as D, proof as PR
    db = db or D.DirDB()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    action = PR.build_action(kind, row, row.get("claim_status"))
    import transitions as T
    T.record_proof(row["id"], dict(proof_url=url, proof_nap=nap, proof_at=stamp, proof_nap_match=True, build_action=action), queue_path=queue_path, today=day, db=db)   # t_d660babc: same validation, same writer


def recheck_file(path=None, ident=None, **kw):
    path = path or Q.QUEUE_PATH
    with open(path, encoding="utf-8") as f: q = json.load(f)
    if ident is None:
        from cfg import IDENT as ident
    return recheck(q, ident, queue_path=path, **kw)


def format_report(results):
    lines = []
    for r in results:
        f = "; ".join("%s=%s" % (a, b) if isinstance(a, str) and b else str(a) for a, b in [(x if isinstance(x, tuple) else (x, "")) for x in r["fields"]])
        lines.append("%-26s %-14s -> %-14s %-12s %s%s%s" % (r["row"], r["before"], r["after"], (r["verdict"] or "") + (" (masked)" if r.get("masked") and r["verdict"] == "match" else ""), f, ("  ERR " + r["error"]) if r["error"] else "", ("  NAP[%s]" % r["nap"]) if r.get("nap") else (("  (%s)" % r["note"]) if r.get("note") and r["verdict"] in ("not-public", "rate-limited") else "")))
        if "recheck_due" in r:   # t_8d1865a3: old -> new for every backed-off row, and whether the queue file really holds it
            tag = {True: " (written)", False: " (NOT WRITTEN)", None: " (dry run: not stored)"}[r["written"]] if "written" in r else " (dry run: not stored)"
            if r.get("parked"): lines.append("    parked: %s -> needs-human, reason %s (3 no-URL backoffs used)" % (r["before"], r["parked"]))
            elif r.get("would_park"): lines.extend(["    -> needs-human (would park: %s)" % r["would_park"], "    recheck_due %s -> none (dry run: not stored)" % (r.get("recheck_due_old") or "none")])
            elif r.get("already_parked"): lines.append("    already parked (needs-human): no backoff, nothing written")
            elif r.get("not_due"): lines.append("    recheck_due %s (unchanged, not due; no backoff counted)" % r["recheck_due"])
            else: lines.append("    recheck_due %s -> %s%s" % (r.get("recheck_due_old") or "none", r["recheck_due"], tag))
    return "\n".join(lines)


def _save_osm(store, real):
    fn = store.saving(lambda url, *a, **k: real(url, *a, **k), "osm")
    return fn


def _replay_osm(store):
    return store.replaying("osm")


def main(argv=None, plain=None, chrome=None):
    import argparse
    a = argparse.ArgumentParser(description="Recheck waiting queue rows against their public listing page")
    a.add_argument("--queue", default=None)
    a.add_argument("--write", action="store_true", help="record transitions and notes (default: dry run, nothing written)")
    a.add_argument("--include-live", action="store_true", help="also read live rows (report only)")
    a.add_argument("--row", action="append", default=None)
    a.add_argument("--proof-live", action="store_true", help="with --write --include-live --row ID: write Proof for named rows already live (state unchanged)")
    a.add_argument("--proof-backfill", action="store_true", help="t_d660babc: for named LIVE rows with incomplete Proof: run the signed-out proof read and write Proof + build_action through transitions.record_proof. Needs --row. Dry run unless --write")
    a.add_argument("--backoff-only", action="store_true", help="dry run that still writes recheck_due (+2 days) on not-public / unreadable-public waiting rows; never live. A no-URL row that already has 3 no-URL backoffs is parked (-> needs-human, no-public-permalink, the 3/3 rule); a plain dry run predicts that park and writes nothing")
    a.add_argument("--any-state", action="store_true", help="with --row ID: read the row in ANY state (e.g. needs-human after a ruling). Dry run; with --write only a needs-human row whose read MATCHES goes live (full Proof), anything else is left as it is")
    a.add_argument("--no-chrome", action="store_true")
    a.add_argument("--today", default=None)
    a.add_argument("--live-sweep-ok", action="store_true", help="t_e34fc55c: --include-live over the whole queue (no --row) reads every live row on the Directories; the weekly job only")
    a.add_argument("--save-pages", default=None, metavar="DIR", help="store every page this run reads, for --replay")
    a.add_argument("--replay", default=None, metavar="DIR", help="score pages saved by --save-pages: no network, no mail, dry run only")
    a.add_argument("--from-read", default=None, metavar="DIR", help="t_0c4ebee8: with --write: reuse the pages a dry run saved with --save-pages (younger than 15 min, same URL) instead of reading the Directory again; stale or mismatched = one live read")
    n = a.parse_args(argv)
    if n.from_read and (not n.write or n.replay or n.save_pages):
        print("REFUSED: --from-read DIR reuses a dry run's saved pages for a --write run; never without --write, nor with --replay / --save-pages", file=sys.stderr); return 1
    if n.include_live and not n.row and not n.live_sweep_ok and not n.replay:
        print("REFUSED: --include-live without --row reads every live row on the Directories (that is how we got blocked). Use --row ID, --replay DIR on saved pages, or --live-sweep-ok (weekly job only)", file=sys.stderr); return 1
    if n.replay and (n.write or n.backoff_only or n.proof_live or n.proof_backfill or n.save_pages):
        print("REFUSED: --replay reads saved pages only; never with --write / --backoff-only / --proof-live / --proof-backfill / --save-pages", file=sys.stderr); return 1
    if n.any_state and (n.backoff_only or n.proof_live or not n.row):
        print("REFUSED: --any-state reads NAMED rows only (--row ID); never with --backoff-only / --proof-live. With --write it promotes needs-human rows to live on a match, nothing else", file=sys.stderr); return 1
    if n.proof_backfill:   # t_d660babc: eligible = named LIVE rows whose stored Proof is incomplete; reads via the existing signed-out path, writes via transitions.record_proof
        if not n.row or n.any_state or n.backoff_only:
            print("REFUSED: --proof-backfill needs --row ID and never combines with --any-state / --backoff-only", file=sys.stderr); return 1
        import transitions as T
        qq = json.load(open(n.queue or Q.QUEUE_PATH, encoding="utf-8"))
        need = dict(T.live_rows_missing_proof(qq, T.db_proof_by_directory()))   # DB Proof columns are the truth: a live row with complete Proof in ce_directory_status is not eligible
        bad = [r for r in n.row if r not in need]
        if bad:
            print("REFUSED: --proof-backfill takes live rows with incomplete Proof only; not eligible: %s" % ", ".join(bad), file=sys.stderr); return 1
        n.include_live = True; n.proof_live = True
    from cfg import IDENT
    mail = None if n.replay else MS.MailScanner(name=IDENT["BIZ"]["SCC"]["name"])   # t_d2f75685: lazy; the first no-permalink row reads listings@ (env, else the vault item). An unreadable mailbox is reported, never fatal. Replay: no mail.
    store = PageStore(n.replay, replay=True) if n.replay else (PageStore(n.save_pages) if n.save_pages else None)
    kw = {}
    if n.replay:
        kw = {"plain": store.replaying("plain"), "chrome": store.replaying("chrome"), "use_chrome": True}
        globals()["osm_fetch"] = _replay_osm(store)
    else:
        kw = {"plain": plain, "chrome": chrome, "use_chrome": not n.no_chrome, "guard": SG.SiteGuard()}
        if store: globals()["osm_fetch"] = _save_osm(store, globals()["osm_fetch"])
        if n.from_read:
            reuse = PageStore(n.from_read, replay=True); kw["from_read"] = reuse
            globals()["osm_fetch"] = reuse.reusing(globals()["osm_fetch"], "osm")
    res = recheck_file(n.queue, write=n.write, include_live=n.include_live, only=set(n.row) if n.row else None, today=n.today, proof_live=n.proof_live, mail=mail, backoff_only=n.backoff_only and not n.write, any_state=n.any_state, store=store, **kw)
    if mail is not None and mail.error: print("MAILBOX NOT READ: %s (rows that need the approval mail were left alone)" % mail.error, file=sys.stderr)
    print(format_report(res))
    print("%d rows read; %d to live; mode=%s" % (len(res), sum(1 for r in res if r["after"] == "live" and r["before"] != "live"), "WRITE" if n.write else ("dry run + backoff-only" if n.backoff_only else "dry run")))
    return 1 if any(r["error"] and r["verdict"] != "unreadable" for r in res) else 0


if __name__ == "__main__":
    sys.exit(main())
