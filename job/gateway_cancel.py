"""Cancel one hermes gateway session (t_c6eee3cb). `hermes chat --oneshot` is only a client of the profile's gateway: killing the client
leaves the turn running there. This stops the turn itself: session.resume (attach, read the snapshot), session.interrupt with the snapshot's
execution_generation (the gateway refuses it as stale_generation without it), then a re-read until the gateway reports the session no longer running.

  <hermes venv python> job/gateway_cancel.py <stored session id>

Run with the hermes venv interpreter (it imports hermes_cli) and the same HERMES_HOME (the profile dir) as the oneshot. Exit 0 = the gateway reports
the session is not running (it was idle, or the interrupt landed and the re-read confirmed it), 1 = the gateway could not be reached, refused, or the
session is still running after the interrupt, 2 = bad argument. Prints reason words only; never a prompt, a message or a code."""
import argparse, asyncio, os, re, sys

SESSION_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,200}$")
CONFIRM_TRIES = 20          # re-reads of the snapshot after the interrupt
CONFIRM_EVERY_S = 0.5


def ensure_hermes_path():
    """hermes' editable install maps its packages but not its top-level modules (hermes_dir_acl.py ...), which `hermes.exe` finds because it runs from the
    checkout. From the venv interpreter (<root>/venv/Scripts/python.exe) put <root> on sys.path. No-op when it is not that layout."""
    exe = os.path.abspath(sys.executable)
    root = os.path.dirname(os.path.dirname(os.path.dirname(exe)))
    if os.path.basename(os.path.dirname(os.path.dirname(exe))) == "venv" and os.path.exists(os.path.join(root, "hermes_dir_acl.py")) and root not in sys.path:
        sys.path.insert(0, root)


async def cancel(session_id):
    """-> 'idle' (nothing was running) or 'stopped' (interrupted and confirmed). Raises RuntimeError('still_running')."""
    ensure_hermes_path()
    from hermes_cli.gateway_client import connect_gateway
    async with connect_gateway() as client:
        snap = await client.rpc("session.resume", session_id=session_id)
        sid = (snap or {}).get("session_id") or session_id
        if (snap or {}).get("running") is False:
            return "idle"
        got = await client.rpc("session.interrupt", session_id=sid, execution_generation=(snap or {}).get("execution_generation"))
        # The reply's own status is NOT trusted either way (live: an interrupt that stopped the running tool still answered something other than
        # `interrupted`); the proof is the gateway's snapshot below. The status word is printed for the operator's log.
        print("gateway_cancel: interrupt reply status=%s" % str((got or {}).get("status"))[:40], file=sys.stderr)
        for _ in range(CONFIRM_TRIES):
            await asyncio.sleep(CONFIRM_EVERY_S)
            now = await client.rpc("session.resume", session_id=sid)
            if (now or {}).get("running") is False:
                return "stopped"
        raise RuntimeError("still_running")


def main(argv=None):
    a = argparse.ArgumentParser()
    a.add_argument("session_id")
    n = a.parse_args(argv)
    if not SESSION_RE.match(n.session_id):
        print("gateway_cancel: bad session id", file=sys.stderr); return 2
    try:
        how = asyncio.run(cancel(n.session_id))
    except Exception as e:
        print("gateway_cancel: failed: %s %s" % (type(e).__name__, str(e)[:80] if type(e).__name__ in ("RuntimeError", "GatewayRPCError") else ""), file=sys.stderr); return 1
    print("gateway_cancel: session %s" % how, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
