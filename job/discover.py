"""Weekly discovery (ported from Spike s3 run_s3.py, same methods). Session 3 run: one fresh pass, owned Chrome only. Writes rows_s3.jsonl, recording-s3.mp4, windows-s3.json.
Methods: plain-HTTP search/pattern/phone; real-Chrome ladder (search/pattern/phone); map own-search; Directory own-search boxes
(hotfrog, n49 via city dropdown pick, brownbook); hard negatives; made-up business; YP blocked on purpose. No s1/s2 rows used."""
import sys, json, os, time, re
from datetime import datetime
from core import *
import mapnap
from owned_chrome import OwnedChrome, window_count, chrome_windows
from playwright.sync_api import sync_playwright

OUT = os.environ.get("CE_ROWS") or os.path.join(HERE, "rows.jsonl")
now = lambda: datetime.now().isoformat(timespec="seconds")
def emit(row):
    row.setdefault("t", now())
    open(OUT, "a", encoding="utf-8").write(json.dumps(row) + "\n")
    print(row["kind"], row.get("method"), row.get("biz"), row.get("dir"), row.get("status"), (row.get("url") or "")[:80], flush=True)
def nap_compare(text, b):
    ev = evidence(text, b)
    return dict(name_match=ev["name"], street_match=ev["street"], city_match=ev["city"], phone_match=bool(ev["phones"]))
class _NullCdp:
    def send(self, *a, **k): pass
class NullRec:
    def attach(self, ctx, pg): return _NullCdp()
    def render(self, out): return None
BIZS = ["SCC", "NM", "FAKE"]
def blocked(b, d): return "yellowpages.com" if (b == "FAKE" and d == "yellowpages.com") else None

def ladder(F, method_tag, methods, rec_label):
    for b in BIZS:
        for d in DIRS:
            for method in methods:
                if b == "FAKE" and method != "search": continue
                F.block = blocked(b, d); F.caption = f"[CE weekly | {rec_label} | {b} | {method}]"
                plan = plan_for(method, d, b); log = []
                if not plan:
                    emit(dict(kind="dir", method=f"{method_tag}-{method}", biz=b, dir=d, status="couldnt", url="", note="no plan", blocked_on_purpose=False)); continue
                try: r = discover(F, d, b, plan, log)
                except Exception as e: r = {"status": "couldnt", "url": "", "ev": None, "note": "error " + type(e).__name__}
                emit(dict(kind="dir", method=f"{method_tag}-{method}", biz=b, dir=d, status=r["status"], url=r["url"], ev=r["ev"], note=r["note"],
                          log=" | ".join(log), blocked_on_purpose=bool(F.block), verified=False, results=0))

def own_search_box(ctx, rec, d, b, tag):
    """hotfrog / brownbook / n49 homepage search box, typed like a person. n49: pick 'Nashville, Tennessee' from the dropdown."""
    x = S(b); pg = ctx.new_page(); cdp = rec.attach(ctx, pg); note = []; text = ""; links = []; u = ""; shot = ""
    try:
        home = {"hotfrog.com": "https://www.hotfrog.com/", "brownbook.net": "https://www.brownbook.net/", "n49.com": "https://www.n49.com/"}[d]
        pg.goto(home, timeout=40000, wait_until="domcontentloaded"); pg.wait_for_timeout(5000)
        for t in ("Accept all", "I agree", "Accept", "Close", "Got it", "OK"):
            try: pg.get_by_role("button", name=t).first.click(timeout=700)
            except Exception: pass
        q = x["name"] if d != "n49.com" else x["short"]
        if d == "hotfrog.com":
            pg.locator("input[name=what]:visible").first.click(timeout=6000); pg.keyboard.type(q, delay=45)
            pg.locator("input[name=where]:visible").first.click(timeout=6000); pg.keyboard.type(f"{x['city']}, {x['st']}", delay=45); pg.wait_for_timeout(2000)
            pg.locator("button:has-text('FIND'):visible, input[type=submit]:visible").first.click(timeout=6000)
        elif d == "brownbook.net":
            pg.locator("input[placeholder^='Business type']:visible").first.click(timeout=6000); pg.keyboard.type(q, delay=45)
            pg.locator("input[placeholder^='Select city']:visible").first.click(timeout=6000); pg.keyboard.type(x["city"], delay=45); pg.wait_for_timeout(2000)
            pg.keyboard.press("ArrowDown"); pg.keyboard.press("Enter"); note.append("city-pick")
            try: pg.get_by_role("button", name="Search").first.click(timeout=4000)
            except Exception: pg.keyboard.press("Enter")
        else:
            pg.locator("input[placeholder^='E.g.']:visible").first.click(timeout=6000); pg.keyboard.type(q, delay=45)
            city = pg.locator("input[placeholder^='Address']:visible").first
            city.click(timeout=6000)
            # the city dropdown only opens once something is typed; a short prefix opens it, then the Tennessee entry is PICKED, not typed in full
            pg.keyboard.type(f"{x['city']}, Ten" if x['st'] == 'TN' else x['city'], delay=80); pg.wait_for_timeout(2500)
            item = pg.locator(".n49-suggest-item", has_text=f"{x['city']}, {'Tennessee' if x['st']=='TN' else 'Kentucky'}").first
            if item.count() == 0: note.append("no-dropdown-entry")
            else: item.click(timeout=4000); note.append("dropdown-pick"); pg.wait_for_timeout(800)
            pg.locator("input[placeholder^='E.g.']:visible").first.press("Enter")
        pg.wait_for_timeout(8000)
        try: pg.evaluate(BANNER_JS, f"[CE weekly | chrome | {d} own search | {b}]")
        except Exception: pass
        text = pg.inner_text("body"); u = pg.url
        try: links = pg.evaluate(LINKS_JS)
        except Exception: pass
        shot = os.path.join(os.environ.get("CE_SHOTS") or os.path.join(HERE, "shots"), f"{tag}.png"); pg.screenshot(path=shot)
    except Exception as e:
        note.append("error " + type(e).__name__ + ":" + str(e)[:80])
    finally:
        try: cdp.send("Page.stopScreencast")
        except Exception: pass
        try: pg.close()
        except Exception: pass
    return Result(200 if text else None, u, text, links, None if text else "no-text"), shot, ";".join(note)

def discover_all(on_chrome=lambda oc: None, on_complete=lambda fetcher: None):
    os.makedirs(os.environ.get('CE_SHOTS') or os.path.join(HERE, 'shots'), exist_ok=True)
    open(OUT, 'w').close()
    rec = NullRec()
    if True:
        # A. plain HTTP
        H = HttpFetcher()
        for method in ("search", "pattern", "phone"):
            for b in BIZS:
                for d in DIRS:
                    if b == "FAKE" and method != "search": continue
                    H.block = blocked(b, d); plan = plan_for(method, d, b); log = []
                    if not plan: emit(dict(kind="dir", method=f"http-{method}", biz=b, dir=d, status="couldnt", url="", note="no plan", blocked_on_purpose=False)); continue
                    r = discover(H, d, b, plan, log)
                    emit(dict(kind="dir", method=f"http-{method}", biz=b, dir=d, status=r["status"], url=r["url"], ev=r["ev"], note=r["note"],
                              log=" | ".join(log), blocked_on_purpose=bool(H.block), verified=False, results=0))
        # B. owned Chrome: ladder + own-search methods
        with OwnedChrome() as oc, sync_playwright() as pw:
            on_chrome(oc)
            ctx = pw.chromium.connect_over_cdp(oc.cdp_url).contexts[0]
            F = ChromeFetcher(ctx, human=True, rec=rec)
            ladder(F, "chrome", ["search", "pattern", "phone"], "chrome ladder")
            for b in BIZS:
                for d in ("google.com", "maps.apple.com", "bing.com", "mapquest.com"):
                    for kind, q in mapnap.queries(b):
                        if b == "FAKE" and kind == "phone": continue
                        tag = f"s3-{d}-{b}-{kind}".replace(".", "_")
                        r = mapnap.lookup(ctx, rec, d, b, kind, q, f"[CE weekly | chrome | map own search | {kind}]", tag)
                        ok, ev, why = mapnap.judge_map(r["text"], b)
                        st = "found" if ok else ("noresult" if (r["verified"] and r["results"] >= 1) else "couldnt")
                        emit(dict(kind="map", method="chrome-mapsearch", biz=b, dir=d, query_kind=kind, status=st, url=r["url"], ev=ev, why=why,
                                  verified=r["verified"], results=r["results"], shot=r["shot"], note=r["note"]))
                        if st == "found": break
                for d in ("hotfrog.com", "n49.com", "brownbook.net"):
                    F.caption = f"[CE weekly | chrome | {d} own search]"
                    r, shot, n = own_search_box(ctx, rec, d, b, f"s3-{d.split('.')[0]}-{b}")
                    status, url, ev = "couldnt", "", None
                    if classify(r, b) == "ok":
                        # judge the results page itself (card carries NAP) and any listing linked from it
                        ok, ev0, why = judge_listing(r.text, b)
                        if ok and not (HN.search(r.text) and not ev0["phones"] and not ev0["street"]) and NAME[b].search(r.text):
                            status, url, ev = "found", r.url, ev0
                        else:
                            for h in candidates(r, b, d):
                                r2 = F.fetch(h, f"{d} {b} listing"); ok2, ev2, _ = judge_listing(r2.text, b)
                                if ok2: status, url, ev = "found", r2.url, ev2; break
                            else:
                                m = re.search(r"(\d+)\s+results?\b", r.text, re.I); nres = int(m.group(1)) if m else 0
                                verified = d in r.url
                                status = "noresult" if (verified and nres >= 1) else "couldnt"
                    m = re.search(r"(\d+)\s+results?\b", r.text or "", re.I)
                    emit(dict(kind="dir", method="chrome-ownbox", biz=b, dir=d, status=status, url=url, ev=ev, verified=d in (r.url or ""),
                              results=int(m.group(1)) if m else 0, shot=shot, note=n, blocked_on_purpose=False))
            # C. hard negatives
            for u in IDENT["HARDNEG"]:
                F.caption = "[CE weekly | hard negative candidate]"; F.block = None
                r = F.fetch(u, "hard-negative candidate"); ok, ev, why = judge_listing(r.text, "SCC"); c = classify(r, "SCC")
                emit(dict(kind="hardneg", method="chrome", biz="SCC", dir=urlparse(u).netloc.replace("www.", ""),
                          status="claimed" if ok else ("rejected" if c == "ok" else "couldnt"), url=r.url, http=r.status, ev=ev, nap=nap_compare(r.text, "SCC"),
                          louisville_on_page=bool(re.search(r"(?i)louisville", r.text)), why=why,
                          snippet=" | ".join(l for l in r.text.split("\n") if re.search(r"(?i)don allen|905[\s.\-)]*2290|louisville", l))[:300]))

            # The weekly claim read must use this fetcher while its owned context is alive.
            F.block = None
            F.caption = "[CE weekly | claim read-only]"
            on_complete(F)
