"""Spike core: truth parser, judge, fetchers, discover loop. Throwaway."""
import re, os, json, time, html as H, base64, subprocess, random
from urllib.parse import urlparse, urljoin, unquote
from cfg import *

HERE = os.path.dirname(os.path.abspath(__file__))
FFMPEG = os.path.expandvars(r"%LOCALAPPDATA%/hermes/tools/ffmpeg-9.0.1-win32-x64/bin/ffmpeg.exe")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

_RX = IDENT["RX"]
NAME = {k: re.compile(v, re.I) for k, v in _RX["name"].items()}
STREET = {k: re.compile(v, re.I) for k, v in _RX["street"].items()}
OLD_STREET = {k: re.compile(v, re.I) for k, v in _RX["old_street"].items()}
HN = re.compile(_RX["hn"], re.I)
CHALLENGE = re.compile(r"(?i)just a moment|verify you are (a )?human|attention required|access denied|unusual traffic|press (&|and) hold|"
                       r"captcha|are you a robot|checking your browser|request blocked|error 1020|you have been blocked|security verification|"
                       r"quick security check|complete this quick check|performing a quick|norobots|log in|sign in to continue")
PHONE_RE = re.compile(r"\(?(\d{3})\)?[\s.\-]*(\d{3})[\s.\-]*(\d{4})")
MASK_RE = re.compile(r"\+?1?\s*\(?(\d{3})\)?\W{0,3}\*{2,}(\d{4})|\+1(\d{2})\*{3,}(\d{4})")
SEARCHY = re.compile(r"(?i)/search|[?&](q|query|search|search_terms|find_desc|find_text|what)=|/explore|/maps/search")
BAD_LINK = re.compile(r"(?i)login|signup|/auth|privacy|terms|#|javascript:|/reviews|/add-|/claim|advertis|\.(png|jpg|css|js|svg)(\?|$)")

def html_to_text(src):
    src = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", src)
    src = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d|td|span|a)>", "\n", src)
    t = H.unescape(re.sub(r"<[^>]+>", " ", src))
    return "\n".join(re.sub(r"[ \t]+", " ", x).strip() for x in t.split("\n") if x.strip())

def evidence(text, b):
    ph = set(m.group(1) + m.group(2) + m.group(3) for m in PHONE_RE.finditer(text))
    mk = set()
    for m in MASK_RE.finditer(text):
        mk.add((m.group(1) or "") + "*" + (m.group(2) or m.group(4)))
    last4 = {p[-4:] for p in S(b)["phones"]}
    partial = any(x.split("*")[-1] in last4 for x in mk)
    return {"name": bool(NAME[b].search(text)),
            "street": bool(STREET[b].search(text)),
            "old_street": bool(b in OLD_STREET and OLD_STREET[b].search(text)),
            "city": S(b)["city"].lower() in text.lower(),
            "phones": sorted(p for p in ph if p in S(b)["phones"]),
            "phone_partial": partial and not (ph & set(S(b)["phones"])),
            "stale_phone": bool(ph & set(S(b)["stale_phones"]))}

def judge_listing(text, b):
    """Return (claim, ev, why). Claim needs name + city + one NAP anchor (street / old street / canonical phone / stale phone)."""
    ev = evidence(text, b)
    if HN.search(text) and not ev["phones"] and not ev["street"]:
        return False, ev, "hardneg-markers"
    nap = ev["street"] or ev["old_street"] or ev["phones"] or ev["phone_partial"] or ev["stale_phone"]
    if ev["name"] and nap and ev["city"]:
        return True, ev, "name+nap+city"
    return False, ev, "name=%s nap=%s city=%s" % (ev["name"], bool(nap), ev["city"])

class Result:
    def __init__(s, status, url, text, links, err=None): s.status, s.url, s.text, s.links, s.err = status, url, text, links, err

class HttpFetcher:
    name = "http"
    def __init__(self, block=None):
        import httpx
        self.c = httpx.Client(headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"},
                              follow_redirects=True, timeout=20)
        self.block = block
    def fetch(self, url, label=""):
        if self.block and self.block in url:
            return Result(None, url, "", [], "blocked-on-purpose")
        try:
            r = self.c.get(url)
        except Exception as e:
            return Result(None, url, "", [], type(e).__name__)
        src = r.text; links = []
        for m in re.finditer(r'(?is)<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', src):
            ctx = html_to_text(src[max(0, m.start() - 500):m.end() + 300])
            links.append({"href": urljoin(str(r.url), H.unescape(m.group(1))), "card": ctx[-500:]})
        return Result(r.status_code, str(r.url), html_to_text(src), links)

LINKS_JS = r"""() => [...document.querySelectorAll('a[href]')].map(a => {
  let n = a, txt = '';
  for (let i = 0; i < 8 && n; i++, n = n.parentElement) { txt = (n.innerText || ''); if (txt.length > 150) break; }
  return {href: a.href, card: txt.slice(0, 500)};
})"""
BANNER_JS = r"""(msg) => { let b = document.getElementById('__ce_banner');
  if (!b) { b = document.createElement('div'); b.id='__ce_banner';
    b.style.cssText='position:fixed;top:0;left:0;right:0;z-index:2147483647;background:#111;color:#0f0;font:600 15px monospace;padding:6px 10px;pointer-events:none';
    (document.body||document.documentElement).appendChild(b); }
  b.textContent = msg; }"""
CONSENT = re.compile(r"^\s*(i agree|agree|accept|accept all|accept cookies|continue|i understand|ok|got it|close|allow all)\s*$", re.I)

class Recorder:
    def __init__(s, d):
        s.d = os.path.join(d, "frames"); os.makedirs(s.d, exist_ok=True); s.n = 0; s.t = []
    def attach(s, ctx, pg):
        cdp = ctx.new_cdp_session(pg)
        def on(ev):
            s.n += 1
            open(os.path.join(s.d, f"{s.n:06d}.jpg"), "wb").write(base64.b64decode(ev["data"])); s.t.append(time.time())
            try: cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
            except Exception: pass
        cdp.on("Page.screencastFrame", on)
        cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 45, "maxWidth": 1100, "maxHeight": 700})
        return cdp
    def render(s, out, cap=0.45):
        if s.n < 2: return None
        lst = os.path.join(s.d, "list.txt")
        with open(lst, "w") as f:
            for i in range(1, s.n + 1):
                dur = min(max(s.t[i] - s.t[i - 1], 0.05), cap) if i < s.n else 1.0
                f.write(f"file '{i:06d}.jpg'\nduration {dur:.3f}\n")
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                        "-vf", "scale=1100:-2,format=yuv420p", "-r", "10", out], check=True, cwd=s.d)
        return out

class ChromeFetcher:
    name = "chrome"
    def __init__(self, ctx, human=False, rec=None, block=None):
        self.ctx, self.human, self.rec, self.block, self.caption = ctx, human, rec, block, ""
    def fetch(self, url, label=""):
        if self.block and self.block in url:
            return Result(None, url, "", [], "blocked-on-purpose")
        pg = self.ctx.new_page(); cdp = None
        try:
            if self.rec: cdp = self.rec.attach(self.ctx, pg)
            try:
                r = pg.goto(url, timeout=40000, wait_until="domcontentloaded"); status = r.status if r else None
            except Exception as e:
                return Result(None, url, "", [], type(e).__name__)
            pg.wait_for_timeout(random.randint(6000, 9000) if self.human else 4500)
            if self.rec:
                try: pg.evaluate(BANNER_JS, f"{self.caption} {label}")
                except Exception: pass
            for _ in range(2):
                clicked = False
                for bt in pg.query_selector_all("button, a[role=button], input[type=button], input[type=submit]"):
                    try:
                        t = (bt.inner_text() or bt.get_attribute("value") or "").strip()
                        if CONSENT.match(t) and bt.is_visible():
                            bt.click(timeout=2500); pg.wait_for_timeout(2500); clicked = True; break
                    except Exception: pass
                if not clicked: break
            if self.human:
                for _ in range(3):
                    pg.mouse.wheel(0, random.randint(300, 700)); pg.wait_for_timeout(random.randint(500, 1200))
            try: text = pg.inner_text("body", timeout=8000)
            except Exception: text = ""
            text = text.replace(f"{self.caption} {label}", "")
            try: links = pg.evaluate(LINKS_JS)
            except Exception: links = []
            if cdp:
                pg.wait_for_timeout(500)
                try: cdp.send("Page.stopScreencast")
                except Exception: pass
            return Result(status, pg.url, text, links)
        finally:
            try: pg.close()
            except Exception: pass

def classify(r, b):
    """blocked | noresult | ok."""
    if r.err or r.status is None: return "blocked"
    if r.status in (401, 403, 429) or r.status >= 500: return "blocked"
    if CHALLENGE.search(r.text[:3000]) and not NAME[b].search(r.text) and len(r.text) < 4000: return "blocked"
    if r.status == 404: return "noresult"
    if len(r.text) < 600: return "blocked"
    return "ok"

def candidates(res, b, d):
    host = urlparse(res.url).netloc.replace("www.", "")
    base = res.url.split("#")[0].rstrip("/")
    out = []
    for l in res.links:
        h = l["href"]
        if not h.startswith("http") or BAD_LINK.search(h) or h.split("#")[0].rstrip("/") == base: continue
        if host.split(".")[-2:] != urlparse(h).netloc.replace("www.", "").split(".")[-2:]: continue
        if SEARCHY.search(h): continue
        card = l.get("card", "")
        path = unquote(urlparse(h).path).lower().replace("-", " ").replace("_", " ")
        if NAME[b].search(card) or NAME[b].search(path):
            if h not in out: out.append(h)
    return out[:5]

MAPDIRS = ("google.com", "maps.apple.com", "bing.com")

def discover(fetcher, d, b, plan, log):
    """plan = [(kind,url)]. -> dict(status found|noresult|couldnt, url, ev, note)."""
    saw_ok = False; rejected = 0
    for kind, url in plan:
        r = fetcher.fetch(url, f"{d} {b} {kind}")
        c = classify(r, b)
        log.append(f"{kind}:{c}:{r.status or r.err}:{url[:110]}")
        if c == "blocked": continue
        saw_ok = True
        if c == "noresult": continue
        is_search = kind in ("search", "phone")
        if is_search and d in MAPDIRS:
            ev = evidence(r.text, b)
            if ev["name"] and (ev["street"] or ev["old_street"]) and ev["city"]:
                return {"status": "found", "url": url, "ev": ev, "note": "map page text"}
        if not is_search:
            ok, ev, why = judge_listing(r.text, b)
            log.append(f"  direct-judge:{why}")
            if ok: return {"status": "found", "url": r.url, "ev": ev, "note": "pattern page"}
            if ev["name"]: rejected += 1
            continue
        for h in candidates(r, b, d):
            r2 = fetcher.fetch(h, f"{d} {b} listing")
            c2 = classify(r2, b)
            if c2 != "ok":
                log.append(f"  cand:{c2}:{r2.status or r2.err}:{h[:100]}"); continue
            ok, ev, why = judge_listing(r2.text, b)
            log.append(f"  cand:{'CLAIM' if ok else 'reject'}:{why}:{r2.url[:100]}")
            if ok: return {"status": "found", "url": r2.url, "ev": ev, "note": "search->listing"}
            rejected += 1
    return {"status": "noresult" if saw_ok else "couldnt", "url": "", "ev": None, "note": "rejected=%d" % rejected}

def plan_for(method, d, b):
    x = S(b)
    if method == "search": return [("search", search_url(d, b))]
    if method == "pattern": return [("pattern", u) for u in pattern_urls(d, b)]
    if method == "phone":
        return [("phone", u) for u in (phone_urls(d, b, p) for p in x["phones"]) if u]
    raise ValueError(method)
