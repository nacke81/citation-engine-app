"""GET-only claim-status re-read of the found SCC listings, then an idempotent merge into the SCC queue file.

  python job/claim_reread.py [--chrome] --checks CHECKS.json [--pages RUN_DIR] [--queue QUEUE.json] [--write-queue] [--out REPORT.json]

CHECKS.json = a list of ce_checks-shaped rows (biz, directory, result, url). Only SCC rows with result 'found' are read.
For each one the record permalink is resolved from the saved matched page's links (same resolver the engine uses), then ONE GET is made.
No login, no signup, no claim, no submit. A wall (403) or a page that does not load gives unknown. Evidence holds page text and URL, no NAP.
The queue is only rewritten with --write-queue; state and mike_approval are never touched.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import claim, listing  # noqa: E402


def chrome_reader():
    """-> (getter, close). The engine's own Chrome (throwaway profile, killed on exit): rendered text, one page load per url. Read only.
    The getter returns (status, text); the text is already rendered, so read_all passes it through without html_to_text."""
    import core
    from owned_chrome import OwnedChrome
    from playwright.sync_api import sync_playwright
    oc = OwnedChrome()
    oc.__enter__(); p = sync_playwright().start()
    f = core.ChromeFetcher(p.chromium.connect_over_cdp(oc.cdp_url).contexts[0]); f.caption = "[CE claim read]"

    def getter(url):
        r = f.fetch(url)
        return (r.status or 0), (r.text or "")

    def close():
        try:
            p.stop()
        finally:
            oc.__exit__(None, None, None)
    return getter, close


def read_all(checks, pages, ident, getter=None, day=None, biz="SCC", rendered=False):
    """-> {directory: {url, http, claim_status, claim_evidence}} for the found rows of one business."""
    links = {(p["biz"], p["directory"]): (p["url"], p.get("links") or []) for p in pages or [] if not p.get("hardneg")}
    name = ident["BIZ"][biz]["name"]
    phones = ident["BIZ"][biz].get("phones") or ()
    out = {}
    for c in checks:
        if c.get("biz") != biz or c.get("result") != "found":
            continue
        d = c["directory"]
        pu, lk = links.get((biz, d), (c.get("url"), []))
        url, _k = listing.resolve(d, c.get("url") or pu, lk, name, phones)
        target = url or c.get("url")          # no permalink: the matched page itself (only Directories whose rule allows a results page read it)
        seen = {}

        def g(u, _g=getter or claim.http_get):
            code, html = _g(u)
            seen["http"] = code
            return code, html
        res = claim.read_claim(d, target, ident, biz, g, day, rendered=rendered)
        out[d] = dict(url=target, http=seen.get("http"), **res)
    return out


def main(argv):
    arg = lambda k, dflt=None: argv[argv.index(k) + 1] if k in argv else dflt
    from cfg import IDENT
    checks = json.load(open(arg("--checks"), encoding="utf-8"))
    pages = []
    if arg("--pages"):
        pages = json.load(open(os.path.join(arg("--pages"), "pages.local.json"), encoding="utf-8"))
    if "--chrome" in argv:     # the engine's own Chrome, rendered text: needed for the 403 and JS Directories
        getter, close = chrome_reader()
        try:
            res = read_all(checks, pages, IDENT, getter=getter, rendered=True)
        finally:
            close()
    else:
        res = read_all(checks, pages, IDENT)
    if arg("--out"):
        json.dump(res, open(arg("--out"), "w", encoding="utf-8"), indent=1)
    for d, r in sorted(res.items()):
        ev = r["claim_evidence"]
        print("%-22s http=%-4s %-9s %s" % (d, r["http"], r["claim_status"], ("| " + ev["text"]) if ev else ""))
    if "--write-queue" in argv:
        import buildqueue
        qp = arg("--queue") or buildqueue.QUEUE_PATH
        q = json.load(open(qp, encoding="utf-8"))
        claim.merge_into_queue(q, res)
        tmp = qp + ".tmp"
        json.dump(q, open(tmp, "w", encoding="utf-8"), indent=1)
        os.replace(tmp, qp)
        print("queue updated:", qp)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
