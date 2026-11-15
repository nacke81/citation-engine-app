"""Point the hermes gateway's browser tools at one Chrome, or let go (t_c6eee3cb). The submitter agent runs INSIDE the profile's gateway, whose
browser tools read the CDP URL from the profile's live override (browser.manage connect) or its secret scope, never from the oneshot client's
environment. This sets the live override before an agent run and clears it after.

  <hermes venv python> job/gateway_browser.py connect http://127.0.0.1:9334
  <hermes venv python> job/gateway_browser.py disconnect

Run with the hermes venv interpreter (it imports hermes_cli) and the same HERMES_HOME (the profile dir) as the oneshot. Exit 0 = done (connect: the
gateway answered connected=True with exactly the URL asked for), 1 = refused, unreachable or the wrong URL, 2 = bad argument. Prints reason words only."""
import argparse, asyncio, re, sys
from urllib.parse import urlparse

URL_RE = re.compile(r"^http://127\.0\.0\.1:\d{2,5}$")


def same_url(a, b):
    """Two CDP URLs name the same endpoint (scheme, host, port; a trailing slash does not matter)."""
    def key(u):
        p = urlparse(str(u or "").strip())
        return (p.scheme, p.hostname, p.port, p.path.rstrip("/"))
    return bool(a) and bool(b) and key(a) == key(b)


async def manage(action, url=None):
    from gateway_cancel import ensure_hermes_path   # same job/ folder (sys.path[0] when run as a script)
    ensure_hermes_path()
    from hermes_cli.gateway_client import connect_gateway
    async with connect_gateway() as client:
        params = {"action": action}
        if url: params["url"] = url
        return await client.rpc("browser.manage", _timeout=60, **params)


def main(argv=None):
    a = argparse.ArgumentParser()
    sub = a.add_subparsers(dest="verb", required=True)
    c = sub.add_parser("connect"); c.add_argument("url")
    sub.add_parser("disconnect")
    n = a.parse_args(argv)
    if n.verb == "connect" and not URL_RE.match(n.url):
        print("gateway_browser: bad url (only a local http CDP endpoint)", file=sys.stderr); return 2
    try:
        r = asyncio.run(manage(n.verb, n.url if n.verb == "connect" else None)) or {}
    except Exception as e:
        print("gateway_browser: %s failed: %s" % (n.verb, type(e).__name__), file=sys.stderr); return 1
    if n.verb == "connect":
        if r.get("connected") is not True or not same_url(r.get("url"), n.url):
            print("gateway_browser: connect refused or wrong url (connected=%s)" % (r.get("connected"),), file=sys.stderr); return 1
        print("gateway_browser: connected", file=sys.stderr); return 0
    if r.get("connected") is not False:
        print("gateway_browser: disconnect not confirmed", file=sys.stderr); return 1
    print("gateway_browser: disconnected", file=sys.stderr); return 0


if __name__ == "__main__":
    sys.exit(main())
