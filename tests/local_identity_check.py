"""Runs on the job PC only (skips in CI: identity.json is not in the repo). Proves the REAL stale-phone list carries the ruled old phone,
by sha256 so no number is written here. Owner ruling 2026-10-16: the old number is tagged 'old phone'."""
import hashlib, json, os, sys
p = os.path.expandvars("%LOCALAPPDATA%/citation-engine/identity.json")
if not os.path.exists(p):
    print("SKIP no local identity.json"); sys.exit(0)
d = json.load(open(p, encoding="utf-8"))
h = {hashlib.sha256(x.encode()).hexdigest() for x in d["BIZ"]["NM"].get("stale_phones", [])}
ok = "a6e97356bfc9543700362ebefa1aecdee4cad27c7f9691e3e7199c4964809222" in h
print(("PASS" if ok else "FAIL"), "NM stale_phones carries the ruled old phone")
sys.exit(0 if ok else 1)
