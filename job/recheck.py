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

  python job/recheck.py [--queue PATH] [--write] [--include-live] [--row ID ...] [--no-chrome]
Without --write nothing is written (dry run); the report still shows before -> after and any mismatch.
"""
import html, json, os, re, sys, urllib.parse, urllib.request, urllib.error
from urllib.parse import quote, urljoin, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buildqueue as Q
import fixlist as F
import listing as L
import walls as W
import mail_scan as MS

STABLE_READS = 3   # a Chrome-route match must hold on this many fresh signed-out reads (t_ac8b1bdd)
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
    def __init__(self, status, url, text, links=None, err=None, html=None):
        self.status, self.url, self.text, self.links, self.err, self.html = status, url, text or "", links or [], err, html


# ---- fetching (every edge injectable) -----------------------------------------------------------------------------
def walled(page):
    return page.status in (None, 0, 401, 403, 429) or (page.status or 0) >= 500 or bool(WALL_RE.search(page.text[:4000])) or len(page.text.strip()) < 200


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


def read_rendered(pg, url, wait_s=30):
    """Open `url` in page `pg`, wait for the JS page to render (past walls), click any 'Reveal Phone Number' control, then read text/links/html.
    Reads only; the one click is a public page's own reveal control (t_3ac43137). -> (status, text, links, html)"""
    import core
    r = pg.goto(url, timeout=40000, wait_until="domcontentloaded"); status = r.status if r else None
    text = ""
    for _ in range(max(1, wait_s // 2)):
        pg.wait_for_timeout(2000)
        try: text = pg.inner_text("body", timeout=8000)
        except Exception: text = ""
        if not WALL_RE.search(text[:4000]) and len(text.strip()) > 200: break
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


def chrome_fetch(url, cdp=CDP_URL, wait_s=30):
    """Read the rendered page in a FRESH signed-out context of the Chrome on `cdp`. Opens and closes one context; reads only. Walls are waited on, never solved."""
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    try:
        b = p.chromium.connect_over_cdp(cdp)
        ctx = b.new_context()   # fresh, signed out (t_ac8b1bdd): contexts[0] is the signed-in build profile and shows owner-only pending edits
        pg = ctx.new_page()
        try:
            status, text, links, raw = read_rendered(pg, url, wait_s)
            return Page(status, pg.url, text, links, html=raw)
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

    def __call__(self, url):
        try: oc = self._start()
        except Exception as e: return Page(0, url, "", err="signed-out Chrome did not start: %s" % type(e).__name__)
        return self._fetch(url, oc.cdp_url, self.wait_s)

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
    """Plain GET first. The build Chrome only when the plain page is walled or shows no readable listing block for the canonical name."""
    if osm_node_id(url):   # the API tags ARE the public listing; the map page has no text, so no plain/Chrome fallback
        return osm_fetch(url), "osm"
    page = (plain or plain_fetch)(url)
    if not walled(page) and (canonical is None or read_block(page.text, canonical)):
        return page, "plain"
    if chrome is None:
        return page, "plain"
    cp = chrome(url)
    return (cp if not walled(cp) or walled(page) else page), "chrome"


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
    ccity = F._tok(cparts[1])[:1] if len(cparts) > 1 else []
    for l in block:
        for m in PROSE_ADDR_RE.finditer(l):
            street, city, st, zp = m.group(1).strip(" ,"), m.group(2).strip(), m.group(3), m.group(4)
            if cst_zip and (st != cst_zip.group(1) or zp != cst_zip.group(2)): continue
            if ccity and F._tok(city)[:1] != ccity: continue
            p = F.parse_street(street)
            if p and p["num"].lstrip("0") and p["type"]: return street + ", " + city + ", " + st + " " + zp, p, zp
    return None


def compare(text, canonical, html_=None):
    """-> {"verdict": match|mismatch|nap-incomplete|not-public|unreadable, "wrong": [(field, shown)], "gaps": [field], "nap": "name | street | phone"}. Pure.
    nap-incomplete (was `gap`, t_f707b644): the page exists but a field is missing or hidden, or the page says the listing is paused / not public yet. A shown value that is wrong is `mismatch`."""
    block = read_block(text, canonical)
    if not block:
        if UNLISTED_RE.search(text or ""):   # t_3ac43137: "HIDDEN until ACTIVATED" with nothing parseable is a page that exists but is not public: nap-incomplete, not unreadable
            return {"verdict": "not-public", "wrong": [], "gaps": ["listing visibility"], "nap": None}
        return {"verdict": "unreadable", "wrong": [], "gaps": [], "nap": None}
    wrong, gaps = [], []
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
    if got and cstreet:
        czip = re.search(r"\b(\d{5})\b", canonical["address"])
        street_txt_norm = " ".join(F._tok(got[0]))
        want_norm = " ".join(F._tok(canonical["address"].split(",")[0]))
        # exact street: number, name, type (Drive/Dr only) and unit via street_equal; "street + city on one line" must continue with the city, not extra words
        ccity = F._tok(canonical["address"].split(",")[1])[:1] if canonical["address"].count(",") >= 1 else []
        rest = street_txt_norm[len(want_norm):].split() if street_txt_norm.startswith(want_norm + " ") or street_txt_norm == want_norm else None
        same = F.street_equal(got[1], cstreet) or (rest is not None and (not rest or rest[:1] == ccity))   # one line: street + city
        if same and rest is None and cstreet.get("type") and got[1].get("type") != cstreet["type"]: same = False   # exact: Drive == Dr only; a dropped type is a different street
        if not same or (got[2] and czip and got[2] != czip.group(1)):
            wrong.append(("address", got[0] if (got[2] or "") in got[0] else got[0] + ((" " + got[2]) if got[2] else "")))
    elif not got:
        gaps.append("address")
    street_txt = got[0] if got else None
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


def candidates(q, include_live=False, only=None, today=None):
    import transitions as T
    out = []
    states = WAITING + (("live",) if include_live else ())
    for _key, kind, rows in T._row_lists(q):
        for r in rows:
            if r.get("state") in states and r.get("directory") and (not only or r["id"] in only):
                if W.is_stopped(r):  # hard-block cap (t_fccbb7ef): a STOPPED row is not touched until Mike resets it
                    print("SKIP %s (%s): hard-block STOPPED, waiting on Mike" % (r.get("directory"), r.get("id"))); continue
                due = r.get("recheck_due")   # t_6b1e01ff: foursquare's edit is reviewed by the Directory; reading it earlier only repeats the old value. A row NAMED with --row is read anyway.
                if due and today and not only and str(due) > str(today):
                    print("SKIP %s (%s): recheck due %s" % (r.get("directory"), r.get("id"), due)); continue
                out.append((kind, r))
    return out


def _last_note(row):
    h = row.get("history") or []
    return (h[-1].get("note") if h and isinstance(h[-1], dict) else None)


def recheck(q, ident, *, plain=None, chrome=None, record=None, db=None, queue_path=None, today=None, write=False, include_live=False, only=None, use_chrome=True, proof_live=False, mail=None):
    """-> list of per-row results {row, directory, url, before, after, verdict, fields, note, error}. Never raises per row."""
    import datetime
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
    if use_chrome and chrome is None: chrome = own_reader = SignedOutReader()   # t_3ac43137: a clean signed-out Chrome of its own, never 9333 / the build profile
    elif not use_chrome: chrome = None
    try:
        return _recheck_rows(q, ident, canonical, plain, chrome, record, db, queue_path, day, write, include_live, only, proof_live, mail)
    finally:
        if own_reader: own_reader.close()


def _recheck_rows(q, ident, canonical, plain, chrome, record, db, queue_path, day, write, include_live, only, proof_live, mail=None):
    results = []
    for kind, row in candidates(q, include_live, only, day):
        d, rid, before = row["directory"], row["id"], row["state"]
        res = {"row": rid, "directory": d, "url": None, "before": before, "after": before, "verdict": None, "fields": [], "note": None, "error": None}
        results.append(res)
        try:
            url = _permalink(row)
            if url is None and d == "bbb.org":
                sp, _how = get_page(_bbb_search_url(ident), plain, chrome)
                url = resolve_bbb(sp, ident)
                if url:
                    note = "weekly recheck: found the BBB profile URL"
                    if write: record("SCC", rid, before, url, note, queue_path=queue_path, today=day) if before in ("submitted", "pending-verify", "found") else None
                    res["note"] = note
            if d in UNREADABLE_PUBLIC:   # t_bbc32230: no public source exists: never fetched, never counted live, never retried
                res["url"] = url; res["verdict"] = "unreadable-public"; res["note"] = UNREADABLE_PUBLIC[d]; continue
            searched_ok = False
            if url is None and d != "bbb.org":   # t_d7a907d5: payment / submission evidence and no listing_url -> look the business up by name + city
                su = search_url_for(d, ident)
                if su:
                    sp, _how = get_page(su, plain, chrome)
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
                continue
            res["url"] = url
            page, how = get_page(url, plain, chrome, canonical)
            cmp_ = compare(page.text, canonical, getattr(page, "html", None))
            if cmp_["verdict"] == "match" and how in ("chrome", "osm"):   # t_ac8b1bdd: a rendered page (Bing Maps) can serve old and new data to different signed-out reads; a match must repeat
                for _ in range(STABLE_READS - 1):
                    again = osm_fetch(url) if how == "osm" else chrome(url); c2 = compare(again.text, canonical, getattr(again, "html", None))
                    if c2["verdict"] != "match": page, cmp_ = again, c2; break
            res["verdict"] = cmp_["verdict"]; res["fields"] = cmp_["wrong"] or cmp_["gaps"]; res["via"] = how; res["nap"] = cmp_.get("nap"); res["masked"] = bool(cmp_.get("masked"))
            if cmp_["verdict"] == "unreadable":
                why = not_public(page, how)
                if why:   # t_3ac43137: the Directory answered and nothing is published for us at this URL: a real verdict, nothing written
                    res["verdict"] = "not-public"; res["fields"] = []; res["note"] = "signed-out page shows no listing: " + why; continue
                res["error"] = "page not readable (%s)" % (page.err or page.status); continue
            if cmp_["verdict"] == "match":
                if before == "live":   # already live: report only, unless --proof-live names the row (t_1c503c7f): Proof only, state stays live
                    if proof_live and write and only:
                        _proof_only(row, kind, url, cmp_["nap"], day, db)
                        res["note"] = "proof written (row stays live)"
                    continue
                res["note"] = "weekly recheck: listing live, NAP matches canonical"
                if write:
                    _proof_then_live(row, kind, url, cmp_["nap"], day, db, record, queue_path, res["note"])
                res["after"] = "live"
            elif before != "live":
                note = note_for(cmp_); res["note"] = note
                if write and note != _last_note(row):
                    record("SCC", rid, before, None, note, queue_path=queue_path, today=day)
        except Exception as e:
            res["error"] = (str(e)[:200] or type(e).__name__)
    return results


def _proof_then_live(row, kind, url, nap, day, db, record, queue_path, note):
    """Proof first (a live row without Proof never counts); if the transition then fails the row stays waiting and the next run retries."""
    import datetime, directories as D, proof as PR
    db = db or D.DirDB()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    action = PR.build_action(kind, row, row.get("claim_status"))
    D._upsert_status(db, [D._status_row(db, "SCC", row["directory"], day, proof_url=url, proof_nap=nap, proof_at=stamp, proof_nap_match=True, build_action=action)])
    out = record("SCC", row["id"], "live", url, note, queue_path=queue_path, today=day)
    if out.get("errors"): raise RuntimeError("; ".join(out["errors"])[:200])


def _proof_only(row, kind, url, nap, day, db):
    """Proof columns for a row that is already live and whose signed-out read matched on every stable read. No state change."""
    import datetime, directories as D, proof as PR
    db = db or D.DirDB()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    action = PR.build_action(kind, row, row.get("claim_status"))
    D._upsert_status(db, [D._status_row(db, "SCC", row["directory"], day, proof_url=url, proof_nap=nap, proof_at=stamp, proof_nap_match=True, build_action=action)])


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
        lines.append("%-26s %-14s -> %-14s %-12s %s%s%s" % (r["row"], r["before"], r["after"], (r["verdict"] or "") + (" (masked)" if r.get("masked") and r["verdict"] == "match" else ""), f, ("  ERR " + r["error"]) if r["error"] else "", ("  NAP[%s]" % r["nap"]) if r.get("nap") else (("  (%s)" % r["note"]) if r.get("note") and r["verdict"] == "not-public" else "")))
    return "\n".join(lines)


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="Recheck waiting queue rows against their public listing page")
    a.add_argument("--queue", default=None)
    a.add_argument("--write", action="store_true", help="record transitions and notes (default: dry run, nothing written)")
    a.add_argument("--include-live", action="store_true", help="also read live rows (report only)")
    a.add_argument("--row", action="append", default=None)
    a.add_argument("--proof-live", action="store_true", help="with --write --include-live --row ID: write Proof for named rows already live (state unchanged)")
    a.add_argument("--no-chrome", action="store_true")
    a.add_argument("--today", default=None)
    n = a.parse_args(argv)
    res = recheck_file(n.queue, write=n.write, include_live=n.include_live, only=set(n.row) if n.row else None, use_chrome=not n.no_chrome, today=n.today, proof_live=n.proof_live)
    print(format_report(res))
    print("%d rows read; %d to live; mode=%s" % (len(res), sum(1 for r in res if r["after"] == "live" and r["before"] != "live"), "WRITE" if n.write else "dry run"))
    return 1 if any(r["error"] and r["verdict"] != "unreadable" for r in res) else 0


if __name__ == "__main__":
    sys.exit(main())
