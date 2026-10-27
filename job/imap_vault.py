"""listings@ IMAP login from the vault when the env has none (t_d2f75685). The citation-submitter env no longer carries LISTINGS_IMAP_PASSWORD: it lives in the
vault item `Listings IMAP (citation-submitter)`. job/imap_vault.cjs wraps the submitter skill's withImap and prints the login as JSON on a pipe; this module
reads it into process memory. The password is never put in argv, a file, a log or an exception message.

fetch(runner=None) -> {"host","port","user","password"}; raises MailboxNotRead("MAILBOX NOT READ: <short reason>") on any failure.
"""
import json, os, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
CJS = os.path.join(HERE, "imap_vault.cjs")
SKILL_JS = os.path.expandvars("%LOCALAPPDATA%/hermes/profiles/citation-submitter/skills/devops/vaultwarden-cli-write/scripts/listings-imap-vault.js")


class MailboxNotRead(Exception):
    """Also a PlaybookError subclass at import time of hotfrog (kept separate here so this module has no imports of the playbooks)."""


def helper_path():
    return os.environ.get("CE_IMAP_VAULT_JS") or SKILL_JS


def fetch(runner=None, node="node", timeout=180):
    js = helper_path()
    if runner is None and not os.path.isfile(js):
        raise MailboxNotRead("MAILBOX NOT READ: IMAP vault helper not found (set CE_IMAP_VAULT_JS); LISTINGS_IMAP_PASSWORD is empty")
    try:
        r = (runner or subprocess.run)([node, CJS, js], capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        raise MailboxNotRead("MAILBOX NOT READ: vault helper could not run (%s)" % type(e).__name__)
    out = (getattr(r, "stdout", "") or "").strip()
    if getattr(r, "returncode", 1) != 0:
        err = (getattr(r, "stderr", "") or "").strip().splitlines()
        raise MailboxNotRead("MAILBOX NOT READ: vault read failed (%s)" % (err[-1][:80] if err else "no output"))
    try:
        data = json.loads(out.splitlines()[-1])
    except (ValueError, IndexError):
        raise MailboxNotRead("MAILBOX NOT READ: vault helper returned no login")
    if not all(data.get(k) for k in ("host", "port", "user", "password")):
        raise MailboxNotRead("MAILBOX NOT READ: vault item is missing host, port, user or password")
    return {k: str(data[k]) for k in ("host", "port", "user", "password")}
