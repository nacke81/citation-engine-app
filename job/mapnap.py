"""Session 2 map-platform lookups: type query in the map's own search box, open the place panel, read NAP."""
import re, os, time
from core import *
SHOTS = os.environ.get("CE_SHOTS") or os.path.join(HERE, "shots")
MAPS = {"google.com": "https://www.google.com/maps", "maps.apple.com": "https://maps.apple.com/",
        "bing.com": "https://www.bing.com/maps", "mapquest.com": "https://www.mapquest.com/"}
def fmt(p): return f"({p[:3]}) {p[3:6]}-{p[6:]}"
def queries(b):
    x = S(b); return [("name", f"{x['name']} {x['city']} {x['st']}"), ("phone", fmt(x["phones"][0])), ("name-only", x["name"])]

def clickfirst(pg, rx):
    """click first visible element whose text matches rx"""
    loc = pg.locator("a, li, [role=option], [role=button], div[class*=result], div[class*=card], h3").filter(has_text=rx)
    n = loc.count()
    for i in range(min(n, 8)):
        e = loc.nth(i)
        try:
            if e.is_visible(): e.click(timeout=3000); return True
        except Exception: pass
    return False

def lookup(ctx, rec, d, b, kind, q, caption, tag):
    pg = ctx.new_page(); cdp = rec.attach(ctx, pg) if rec else None
    rx = re.compile(NAME[b].pattern, re.I)
    note = []; results = 0; text = ""; verified = False; panel = False
    def banner(extra=""):
        if rec:
            try: pg.evaluate(BANNER_JS, f"{caption} {d} {b} {kind} {extra}")
            except Exception: pass
    try:
        pg.goto(MAPS[d], timeout=40000, wait_until="domcontentloaded"); pg.wait_for_timeout(5000); banner("open")
        for t in ("Accept all", "I agree", "Accept"):
            try: pg.get_by_role("button", name=t).first.click(timeout=800)
            except Exception: pass
        if d == "google.com": box = pg.locator("input#ucc-1, input[name=q]").first
        elif d == "bing.com": box = pg.locator("#searchBoxInput").first
        elif d == "mapquest.com": box = pg.locator("#main-search-input").first
        else:
            pg.mouse.click(35, 92); pg.wait_for_timeout(1500); box = pg.locator("input[type=search]").first
        box.click(timeout=5000); pg.keyboard.type(q, delay=45); pg.wait_for_timeout(2500); banner("typed")
        body = pg.inner_text("body"); 
        if d in ("bing.com", "maps.apple.com"):
            # suggestions are in the DOM text; count those that look like businesses
            results = len([l for l in body.split("\n") if re.search(r"\d{2,5} .*|, [A-Z]{2}", l)])
            pg.keyboard.press("ArrowDown"); pg.wait_for_timeout(500); pg.keyboard.press("Enter"); note.append("arrow-enter")
        else:
            pg.keyboard.press("Enter")
        pg.wait_for_timeout(7000); banner("results")
        text = pg.inner_text("body")
        if d == "google.com" and "/maps/place/" not in pg.url:
            if clickfirst(pg, rx): pg.wait_for_timeout(6000); text = pg.inner_text("body"); note.append("clicked-result")
        if d == "mapquest.com":
            # results card is rendered under the list; open the place page
            cards = pg.locator("h3").filter(has_text=rx)
            if cards.count():
                results = max(results, pg.locator("h3").count())
                try: cards.first.click(timeout=3000); pg.wait_for_timeout(6000); text = pg.inner_text("body") + "\n" + " ".join(pg.evaluate("[...document.querySelectorAll('h1,h2,h3,span,div,a')].filter(e=>e.children.length==0).map(e=>e.textContent.trim()).filter(t=>t.length>2&&t.length<90&&(/\d{3}[)\s.-]*\d{3}[\s.-]*\d{4}/.test(t)||/\d+ [A-Z][a-z]+/.test(t)))"))
                except Exception as e: note.append("card-click-fail")
            else:
                text += "\n" + "\n".join(pg.evaluate("[...document.querySelectorAll('h3,span,div')].filter(e=>e.children.length==0).map(e=>e.textContent.trim()).filter(t=>t&&t.length<90)"))
                results = pg.locator("h3").count()
        banner("panel")
        if d == "mapquest.com" or d == "google.com":
            pass
        shot = os.path.join(SHOTS, f"{tag}.png"); pg.screenshot(path=shot)
        # visible-panel text from every DOM leaf (apple/bing panels sit in nested containers)
        try:
            leaf = pg.evaluate("[...document.querySelectorAll('*')].filter(e=>e.children.length==0&&e.innerText).map(e=>e.innerText.trim()).filter(t=>t&&t.length<120)")
            text += "\n" + "\n".join(leaf)
        except Exception: pass
        panel = bool(rx.search(text))
        host_ok = {"google.com": "google.com/maps", "maps.apple.com": "maps.apple.com", "bing.com": "bing.com/maps", "mapquest.com": "mapquest.com"}[d] in pg.url
        # real map results page = right host, search box loaded, page not a help/login/consent page
        verified = host_ok and not re.search(r"(?i)before you continue|sign in to continue|help center", text[:600])
        url = pg.url
        try: links = pg.evaluate(LINKS_JS)
        except Exception: links = []
    except Exception as e:
        shot = ""; url = ""; note.append("error " + type(e).__name__ + ": " + str(e)[:80])
    finally:
        if cdp:
            try: cdp.send("Page.stopScreencast")
            except Exception: pass
        try: pg.close()
        except Exception: pass
    return dict(links=locals().get("links") or [], text=text, url=url, shot=shot if 'shot' in dir() else "", verified=verified, panel=panel, results=results, note=";".join(note))

def judge_map(text, b):
    """claim = name + (street+city | exact canonical phone). A map panel often has no city string, so exact phone is the anchor."""
    ev = evidence(text, b); rx = ev["name"]
    strong = ev["phones"] or (ev["street"] and ev["city"])
    if HN.search(text) and not ev["phones"] and not ev["street"]: return False, ev, "hardneg-markers"
    return bool(rx and strong), ev, ("name+" + ("phone" if ev["phones"] else "street+city")) if rx and strong else f"name={rx} street={ev['street']} phones={ev['phones']} stale={ev['stale_phone']} old={ev['old_street']}"
if __name__ == "__main__":
    import sys
    from playwright.sync_api import sync_playwright
    d, b, k = sys.argv[1:4]
    with sync_playwright() as pw:
        ctx = pw.chromium.connect_over_cdp("http://127.0.0.1:9344").contexts[0]
        q = dict(queries(b))[k]
        r = lookup(ctx, None, d, b, k, q, "", f"dbg-{d}-{b}-{k}")
        print(r["url"][:120], r["verified"], r["panel"], r["results"], r["note"]); print(judge_map(r["text"], b))
