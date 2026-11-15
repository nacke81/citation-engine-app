"""Cancel one hermes gateway session (t_c6eee3cb). `hermes chat --oneshot` is only a client of the profile's gateway: killing the client
leaves the turn running there. This stops the turn itself: session.resume (attach), session.interrupt, session.close.

  <hermes venv python> job/gateway_cancel.py <stored session id>

Run with the hermes venv interpreter (it imports hermes_cli) and the same HERMES_HOME (the profile dir) as the oneshot. Exit 0 = interrupted and closed,
1 = the gateway could not be reached or refused. Prints reason words only; never a prompt, a message or a code."""
import argparse, asyncio, re, sys

SESSION_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,200}$")


async def cancel(session_id):
    from hermes_cli.gateway_client import connect_gateway
    async with connect_gateway() as client:
        snap = await client.rpc("session.resume", session_id=session_id)
        sid = (snap or {}).get("session_id") or session_id
        await client.rpc("session.interrupt", session_id=sid)
        await client.rpc("session.close", session_id=sid)


def main(argv=None):
    a = argparse.ArgumentParser()
    a.add_argument("session_id")
    n = a.parse_args(argv)
    if not SESSION_RE.match(n.session_id):
        print("gateway_cancel: bad session id", file=sys.stderr); return 2
    try:
        asyncio.run(cancel(n.session_id))
    except Exception as e:
        print("gateway_cancel: failed: %s" % type(e).__name__, file=sys.stderr); return 1
    print("gateway_cancel: session interrupted and closed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
