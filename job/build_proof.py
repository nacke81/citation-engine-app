"""Proof that the build Chrome gets past the bot walls the headless agent browser hit. READ ONLY.
Loads homepage + search page of 6 Directories through build_chrome. No click, no form fill, no signup, no submit. SCC identity only
for the search URL. Writes <out>/proof.json and one screenshot per page. Classification: loads | challenge | 403 | error.
  python job/build_proof.py <out_dir>
"""
import os, sys, json, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_chrome import build_chrome
from owned_chrome import window_count
import cfg

SITES = ["yelp.com", "manta.com", "hotfrog.com", "bizapedia.com", "showmelocal.com", "chamberofcommerce.com"]
CHALLENGE = re.compile(r"captcha-delivery|datadome|just a moment|checking your browser|verify you are (a )?human|are you a robot|press (&|and) hold|"
                       r"human verification|drag and drop challenge|slide to|attention required|cf-chl|access denied|unusual traffic|security check", re.I)


def classify(status, text, html):
    if CHALLENGE.search(text or "") or CHALLENGE.search((html or "")[:20000]): return "challenge"
    if status in (401, 403, 429) and len((text or "").strip()) <= 200: return "403" if status == 403 else "challenge"
    if status in (401, 403, 429): return "loads (first response %d, page rendered)" % status
    if status and status >= 400: return "error"
    return "loads" if len((text or "").strip()) > 200 else "error"


def main(out):
    from playwright.sync_api import sync_playwright
    os.makedirs(out, exist_ok=True)
    res = []; before = window_count()
    with build_chrome() as oc, sync_playwright() as pw:
        ctx = pw.chromium.connect_over_cdp(oc.cdp_url).contexts[0]
        pg = ctx.new_page()
        ua = pg.evaluate("navigator.userAgent"); wd = pg.evaluate("navigator.webdriver")
        for d in SITES:
            for kind, url in (("home", "https://www.%s/" % d), ("search", cfg.search_url(d, "SCC"))):
                status = None; err = None
                try:
                    r = pg.goto(url, timeout=40000, wait_until="domcontentloaded"); status = r.status if r else None
                    pg.wait_for_timeout(6000)
                    text = pg.inner_text("body", timeout=8000); html = pg.content()
                except Exception as e:
                    text, html, err = "", "", type(e).__name__
                shot = os.path.join(out, "%s-%s.png" % (d.split(".")[0], kind))
                try: pg.screenshot(path=shot)
                except Exception: shot = None
                row = dict(site=d, page=kind, url=url, final_url=pg.url, status=status, result="error" if err else classify(status, text, html),
                           error=err, title=(pg.title() if not err else None), text_len=len(text), screenshot=shot)
                res.append(row); print(row["site"], row["page"], row["status"], row["result"], flush=True)
        pg.close()
    time.sleep(1)
    after = window_count()
    out_doc = dict(user_agent=ua, webdriver=wd, windows_before=before, windows_after=after, rows=res)
    json.dump(out_doc, open(os.path.join(out, "proof.json"), "w"), indent=1)
    print("UA=%s webdriver=%s windows %d -> %d" % (ua, wd, before, after))
    return 0 if before == after else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
