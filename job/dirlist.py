"""Directory list for the weekly finder: ce_directories at run start, db/directories_seed.json only as an offline fallback.

GET only. The seed is generated (db/gen_directories_seed.py), not a hand-kept list. A fallback is loud, never silent.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SEED_PATH = os.path.join(HERE, "..", "db", "directories_seed.json")


def _clean(domains):
    out, seen = [], set()
    for d in domains:
        d = (d or "").strip().lower()
        if d and d not in seen:
            seen.add(d); out.append(d)
    return out


def seed_domains(seed_path=None):
    return _clean(r.get("domain") for r in json.load(open(seed_path or SEED_PATH, encoding="utf-8")))


def load_directories(db=None, seed_path=None, log=None):
    """-> (domains, source) where source is 'ce_directories' or 'seed'. db: object with .call(method, path, body, prefer); None = real DirDB."""
    log = log or (lambda m: print(m, file=sys.stderr, flush=True))
    try:
        if db is None:
            import directories as D
            db = D.DirDB()
        rows = db.call("GET", "ce_directories?select=domain&order=priority.asc,domain.asc", None, "return=representation") or []
        doms = _clean(r.get("domain") for r in rows)
        if not doms: raise ValueError("ce_directories returned no rows")
        return doms, "ce_directories"
    except Exception as e:
        log("DIRLIST FALLBACK to db/directories_seed.json: " + (str(e)[:150] or type(e).__name__))
        return seed_domains(seed_path), "seed"
