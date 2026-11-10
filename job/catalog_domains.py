"""The Directory domains in the Catalog (db/directories_seed.json). Read-only, local file, no network. t_24ffb698

Two different Catalog entries are two different companies, whatever their first label (yellowpages.com vs yellowpages.net).
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "..", "db", "directories_seed.json")
_CACHE = None


def domains():
    global _CACHE
    if _CACHE is None:
        try:
            with open(PATH, encoding="utf-8") as f:
                got = {(d.get("domain") or "").lower() for d in json.load(f)} - {""}
        except (OSError, ValueError, AttributeError, TypeError):
            return None   # FAIL CLOSED: unreadable Catalog is None, never an empty set, never cached; callers treat different domains as different Directories
        if not got: return None
        _CACHE = got
    return _CACHE
