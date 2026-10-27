"""Screenshot of the BUILD Chrome (CDP 9333) saved to a path (kanban t_6b1e01ff). The `browser_*` tools look at a different browser; this is the way to
see what the build Chrome shows. Reads only: connects over CDP, runs Page.captureScreenshot on one tab, writes a PNG. Loopback only.
Does not navigate, click or type, and never closes the Chrome or the tab.

  python job/build_shot.py OUT.png [--url-contains foursquare] [--port 9333] [--full]
  python job/build_shot.py --list                  (tab titles + URLs without query strings)

Tab choice: the first page whose URL contains --url-contains, else the last real page (not about:blank / devtools / chrome://).
"""
import base64, json, os, sys, urllib.request

PORT = 9333
SKIP = ("about:blank", "devtools://", "chrome://", "chrome-extension://")


def targets(port=PORT, getter=None):
    """-> the page targets of the Chrome on 127.0.0.1:port (loopback only)."""
    get = getter or (lambda u: urllib.request.urlopen(u, timeout=5).read())
    return [t for t in json.loads(get("http://127.0.0.1:%d/json/list" % int(port))) if t.get("type") == "page"]


def pick(tabs, url_contains=None):
    real = [t for t in tabs if not (t.get("url") or "").startswith(SKIP)]
    if url_contains:
        hit = [t for t in real if url_contains.lower() in (t.get("url") or "").lower()]
        if not hit: raise LookupError("no build Chrome tab has a URL containing %r" % url_contains)
        return hit[0]
    if not real: raise LookupError("the build Chrome has no real page open")
    return real[-1]


def capture_png(port, tab_url, full=False):
    """PNG bytes of the tab whose URL is tab_url, via Playwright's CDP session (the engine's own CDP client). The tab is left open."""
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    try:
        b = p.chromium.connect_over_cdp("http://127.0.0.1:%d" % int(port))
        pg = next((pg for c in b.contexts for pg in c.pages if pg.url == tab_url), None)
        if pg is None: raise LookupError("the tab moved while connecting: %s" % tab_url.split("?")[0][:80])
        s = pg.context.new_cdp_session(pg)
        r = s.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": bool(full)})
        return base64.b64decode(r["data"])
    except LookupError:
        raise
    except Exception as e:
        raise RuntimeError("could not capture (%s): is the build Chrome up on %d?" % (type(e).__name__, int(port)))
    finally:
        try: p.stop()
        except Exception: pass


def shot(out, port=PORT, url_contains=None, full=False, tabs=None, capture=None):
    """Save a PNG of one build Chrome tab to `out`. -> (path, tab url without query, bytes). LookupError / RuntimeError / ValueError carry a plain reason."""
    if not str(out).lower().endswith(".png"): raise ValueError("output path must end in .png")
    t = pick(tabs if tabs is not None else targets(port), url_contains)
    data = (capture or capture_png)(port, t["url"], full)
    if not data or data[:8] != b"\x89PNG\r\n\x1a\n": raise RuntimeError("the capture is not a PNG")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "wb") as f: f.write(data)
    return out, (t.get("url") or "").split("?")[0], len(data)


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="Save a screenshot of the build Chrome (CDP 9333) to a PNG path")
    a.add_argument("out", nargs="?")
    a.add_argument("--url-contains", default=None)
    a.add_argument("--port", type=int, default=PORT)
    a.add_argument("--full", action="store_true", help="capture beyond the viewport")
    a.add_argument("--list", action="store_true")
    n = a.parse_args(argv)
    try:
        if n.list:
            for t in targets(n.port): print("%-60s %s" % ((t.get("title") or "")[:60], (t.get("url") or "").split("?")[0][:90]))
            return 0
        if not n.out: a.error("OUT.png is required (or --list)")
        p, url, size = shot(n.out, n.port, n.url_contains, n.full)
    except (LookupError, RuntimeError, ValueError, OSError) as e:
        print("build_shot: %s" % str(e)[:200]); return 1
    print("saved %s (%d bytes) of %s" % (p, size, url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
