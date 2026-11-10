"""The Directory domains in the Catalog (db/directories_seed.json). Read-only, local file, no network. t_24ffb698

Two different Catalog entries are two different companies, whatever their first label (yellowpages.com vs yellowpages.net).
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
_CACHE = None


def domains():
    global _CACHE
    if _CACHE is None:
        try:
            with open(os.path.join(HERE, "..", "db", "directories_seed.json"), encoding="utf-8") as f:
                _CACHE = {(d.get("domain") or "").lower() for d in json.load(f)}
        except (OSError, ValueError):
            _CACHE = set()
    return _CACHE
