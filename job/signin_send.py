"""t_79c39f75: a one-time Vaultwarden Send so the CLIENT can sign in to a Directory herself (id-check / document upload, e.g. Nextdoor).

make_signin_send(client, directory, verify_type, ...) -> {"signin_send_url", "signin_send_expires_at"} or None.
  * Gate: only SEND_TYPES (id-check, document-upload). Phone/SMS/postcard/client-email rows never reach the vault (Mike drives those).
  * Fail closed: no BW creds, item "SCC - <directory>" missing, or any vault error -> ONE log line, return None, nothing is written.
  * The Send holds the login: text, max 1 access, 7 days to expire and delete, not hidden, no Send password. Built in job/vault_send.cjs;
    the secret goes to bw on stdin only. This module never sees the password; it sees the Send URL (a capability) and writes it to the row
    only. The URL is never logged or printed except by the reissue CLI's explicit --show-url flag (not used by default).
  * Row write: PATCH citation_verification (two columns). Off unless write=True AND CE_SIGNIN_SEND_WRITE=1 (flag stays off until the portal
    migration of t_02193c0e is deployed). Dry run uses a stub table object, never the portal. No portal seed, no Directory action.
Reissue: `python job/signin_send.py --reissue --directory nextdoor.com --verify-type document-upload [--write]` mints a fresh Send.
"""
import json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SEND_TYPES = ("id-check", "document-upload")
FLAG = "CE_SIGNIN_SEND_WRITE"
HERE = os.path.dirname(os.path.abspath(__file__))
SEND_JS = os.path.join(HERE, "vault_send.cjs")
REASONS = ("item-missing", "send-no-url", "missing-options", "operation-failed")   # the only vault error text ever logged
CRED_KEYS = ("BW_CLIENTID", "BW_CLIENTSECRET", "BW_PASSWORD")


def _log(msg, log=None):
    (log or (lambda m: print(m, file=sys.stderr)))("signin_send: " + msg)


def creds_available(env=None):
    """True when the runtime env holds the three BW_* names, or BW_ENV_FILE / HERMES_HOME/.env names them. Values are never returned."""
    env = os.environ if env is None else env
    if all(env.get(k) for k in CRED_KEYS): return True
    f = env.get("BW_ENV_FILE") or (env.get("HERMES_HOME") and os.path.join(env["HERMES_HOME"], ".env"))
    try: text = open(f, encoding="utf-8").read() if f else ""
    except OSError: return False
    return all(re.search(r"^\s*%s=\S" % k, text, re.M) for k in CRED_KEYS)


def _run_node(directory, runner=None, env=None, timeout=240):
    import build_runner as B
    cmd = ["node", SEND_JS, "--organization", B.ORG, "--collection", B.COLLECTION, "--fill-js", B.FILL_JS, "--directory", directory]
    return (runner or subprocess.run)(cmd, capture_output=True, text=True, timeout=timeout, env=env)


class StubTable:
    """Dry-run / test sink standing in for citation_verification. Records PATCHes only."""
    def __init__(self, rows=1): self.calls, self.rows = [], rows
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path, body))
        return [{"client_id": "x"}] * self.rows if method in ("GET", "PATCH") else None


def make_signin_send(client, directory, verify_type, *, runner=None, env=None, log=None):
    """-> {"signin_send_url", "signin_send_expires_at"} or None (skipped / failed closed; one log line, no write)."""
    if client != "SCC":
        _log("skip %s: SCC only" % directory, log); return None
    if verify_type not in SEND_TYPES:
        return None   # phone / sms / postcard / client-email: no Send, no vault call, no log noise
    if not directory or not re.fullmatch(r"[A-Za-z0-9.\-]{3,80}", directory):
        _log("skip: bad directory name", log); return None
    if not creds_available(env):
        _log("skip %s: Vaultwarden credentials unavailable in this runtime" % directory, log); return None
    try:
        r = _run_node(directory, runner, env)
    except Exception as e:
        _log("skip %s: vault command did not run (%s)" % (directory, type(e).__name__), log); return None
    rc = getattr(r, "returncode", 1)
    if rc == 3:
        _log("skip %s: item 'SCC - %s' missing or not unique; no Send made" % (directory, directory), log); return None
    if rc != 0:
        m = re.search(r"reason=([a-z-]+)", getattr(r, "stderr", "") or "")
        reason = m.group(1) if m and m.group(1) in REASONS else "operation-failed"   # allowlist: raw stderr can quote secret text
        _log("skip %s: vault error (%s)" % (directory, reason), log); return None
    try:
        out = json.loads((getattr(r, "stdout", "") or "").strip().splitlines()[-1])
        url, exp = out["url"], out["expires_at"]
        assert str(url).startswith(SEND_URL_PREFIX) and exp
    except Exception:
        _log("skip %s: vault returned no usable Send" % directory, log); return None
    return {"signin_send_url": url, "signin_send_expires_at": exp}


SEND_URL_PREFIX = "https://bitwardenrs.mikenacke.com/"   # portal DB check accepts only this prefix


def row_exists(client_id, directory, table):
    path = "citation_verification?select=directory&client_id=eq.%s&directory=eq.%s&state=eq.requires_verification&limit=1" % (client_id, directory)
    rows = table.call("GET", path)
    return isinstance(rows, list) and len(rows) > 0


def write_send(client_id, directory, fields, table, write=False, flag=None):
    """PATCH three columns (url, expires_at, signin_viewed_at=null so a re-issued link on a viewed row can be opened). Returns (method, path, body, status): written | dry-run | no-row (0 rows matched). Live only when write AND CE_SIGNIN_SEND_WRITE=1."""
    path = "citation_verification?client_id=eq.%s&directory=eq.%s&state=eq.requires_verification" % (client_id, directory)
    live = bool(write) and (flag if flag is not None else os.environ.get(FLAG)) in ("1", 1, True)
    status = "dry-run"
    body = dict(fields)
    body["signin_viewed_at"] = None
    if live:
        rows = table.call("PATCH", path, body, prefer="return=representation")
        status = "written" if isinstance(rows, list) and len(rows) > 0 else "no-row"
    return ("PATCH", path, body, status)


def issue(client, directory, verify_type, *, write=False, table=None, runner=None, env=None, log=None, flag=None):
    """Make a Send and attach it to the row. -> status string (never the URL). 'no-row' when no requires_verification row holds it."""
    import portal as P
    live = bool(write) and (flag if flag is not None else os.environ.get(FLAG)) in ("1", 1, True)
    if not live and runner is None:   # real dry run: a Send in the vault with no row to carry it would be an orphan, so make none
        return "dry-run: would mint a Send" if verify_type in SEND_TYPES else "no-send"
    if verify_type not in SEND_TYPES: return "no-send"
    client_id = P.client_for(client)
    tbl = table if table is not None else (P.Portal(*P.load_portal_env()) if live else StubTable())
    if live and not row_exists(client_id, directory, tbl):   # check before minting so no Send is made that nothing holds
        _log("skip %s: no requires_verification row; no Send made" % directory, log); return "no-row"
    fields = make_signin_send(client, directory, verify_type, runner=runner, env=env, log=log)
    if not fields: return "no-send"
    res = write_send(client_id, directory, fields, tbl, write=write, flag=flag)
    if res[3] == "no-row":
        _log("row vanished for %s before the link was saved" % directory, log); return "no-row"
    return "%s expires=%s" % (res[3], fields["signin_send_expires_at"])


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="Mint a fresh one-time sign-in Send for a client-facing verification row (re-issue)")
    a.add_argument("--reissue", action="store_true", required=True)
    a.add_argument("--client", default="SCC")
    a.add_argument("--directory", required=True)
    a.add_argument("--verify-type", required=True, choices=SEND_TYPES)
    a.add_argument("--write", action="store_true", help="PATCH the row; also needs CE_SIGNIN_SEND_WRITE=1 (off until the portal migration is deployed)")
    n = a.parse_args(argv)
    st = issue(n.client, n.directory, n.verify_type, write=n.write)
    print("%s %s" % (n.directory, st))
    return 0 if st not in ("no-send", "no-row") else 1


if __name__ == "__main__":
    sys.exit(main())
