"""Vaultwarden item resolution by registrable domain (t_3ac43137). `SCC - acompio` (the item) vs `SCC - acompio.com` (the spec) used to fail with
not-found. This module picks the ONE item in the SCC org Citations collection whose name or login URI carries the Directory's domain.

resolve_item(domain, items) is pure: items = [{"id", "name", "uris": [...]}] (no secrets ever pass through here). list_items(...) asks
job/vault_resolve.cjs (reads names / ids / uris through the vault helper; never a password) via an injectable runner.
Ranking: exact name 'SCC - <domain>' > name contains the domain > name contains the brand label > a URI on the domain. Two items at the best rank = ambiguous (refuse;
pass --item-id). None = not-found.
"""
import json, os, re, subprocess
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
RESOLVE_JS = os.path.join(HERE, "vault_resolve.cjs")
SECOND_LEVEL = {"co", "com", "org", "net", "gov", "edu", "ac"}


class VaultItemError(Exception):
    pass


def registrable(host):
    """eTLD+1 without a suffix list (same rule as the fill helper): last two labels, three for co.uk-style."""
    h = (host or "").lower().strip(".")
    h = re.sub(r"^https?://", "", h).split("/")[0].split(":")[0]
    p = [x for x in h.split(".") if x]
    if len(p) <= 2: return ".".join(p)
    return ".".join(p[-3:] if len(p[-1]) == 2 and p[-2] in SECOND_LEVEL else p[-2:])


def brand(domain):
    p = registrable(domain).split(".")
    return p[-3] if len(p) >= 3 else p[0] if p else ""


def _uri_domains(item):
    out = set()
    for u in item.get("uris") or []:
        try: out.add(registrable(urlparse(u).netloc or u))
        except Exception: pass
    return out


def resolve_item(domain, items):
    """-> the one matching item dict. VaultItemError('not-found' / 'item-not-unique') otherwise."""
    dom = registrable(domain)
    if not dom: raise VaultItemError("not-found: no domain")
    b = brand(dom)
    ranked = {1: [], 2: [], 3: [], 4: []}
    for it in items or []:
        name = (it.get("name") or "").lower()
        if name == ("scc - " + dom): ranked[1].append(it)
        elif re.search(r"(?<![a-z0-9])" + re.escape(dom) + r"(?![a-z0-9])", name): ranked[2].append(it)   # bounded: 'notevil.com' is not 'evil.com'
        elif dom in _uri_domains(it): ranked[3].append(it)
        elif b and len(b) >= 4 and re.search(r"(?<![a-z0-9])" + re.escape(b) + r"(?![a-z0-9])", name): ranked[4].append(it)
    for rank in (1, 2, 3, 4):
        hit = ranked[rank]
        if len(hit) == 1: return hit[0]
        if len(hit) > 1: raise VaultItemError("item-not-unique: %d items match %s (%s); pass --item-id" % (len(hit), dom, ", ".join(sorted(x.get("name", "?") for x in hit))))
    raise VaultItemError("not-found: no item in the Citations collection names or links %s" % dom)


def list_items(runner=None, node="node", script=None, timeout=180):
    """Item ids / names / uris of the SCC org Citations collection via vault_resolve.cjs. No passwords. Raises VaultItemError on a vault problem."""
    import build_runner as B
    cmd = [node, script or RESOLVE_JS, "--organization", B.ORG, "--collection", B.COLLECTION, "--fill-js", B.FILL_JS]
    r = (runner or subprocess.run)(cmd, capture_output=True, text=True, timeout=timeout)
    out = ((getattr(r, "stdout", "") or "")).strip()
    if getattr(r, "returncode", 1) != 0:
        err = ((getattr(r, "stderr", "") or "") + out).strip()
        raise VaultItemError("vault list failed: %s" % (err.splitlines()[-1] if err else "no output")[:200])
    try: data = json.loads(out)
    except ValueError: raise VaultItemError("vault list returned no JSON")
    return [{"id": x.get("id"), "name": x.get("name"), "uris": x.get("uris") or []} for x in data.get("items", [])]


def resolve_for_domain(domain, runner=None, items=None):
    """-> (item_id, item_name). Name only is safe to print."""
    it = resolve_item(domain, items if items is not None else list_items(runner))
    return it["id"], it["name"]


def main(argv=None, runner=None, items=None, out=print, err=None):
    """CLI (t_d2f75685): `python job/vault_item.py --domain citylocalpro.com` prints the resolved item NAME only (`--print id` prints the id).
    Never a username, password or note: resolve_item sees id / name / uris only. Exit 0 found, 1 not-found / not-unique / vault problem.
    Feed the name to the fill helper (`--name`) or to `build_runner --item-name`, so `SCC - citylocalpro` vs `SCC - citylocalpro.com` never fails."""
    import argparse, sys
    a = argparse.ArgumentParser(description="Print the name of the one Citations vault item for a Directory domain (never the secret)")
    a.add_argument("--domain", required=True)
    a.add_argument("--print", dest="what", choices=("name", "id"), default="name")
    n = a.parse_args(argv)
    err = err or (lambda m: print(m, file=sys.stderr))
    try:
        it = resolve_item(n.domain, items if items is not None else list_items(runner))
    except VaultItemError as e:
        err("REFUSED: %s" % e); return 1
    out(it["name"] if n.what == "name" else it["id"])
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
