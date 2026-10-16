"""Leak check: no real identity token anywhere in the repo. Tokens are held only as sha256 hashes (tests/denylist.json).
Planted control: a throwaway file holding a real-looking token must be CAUGHT, or this check fails (the check itself is broken).
Also refuses secret-looking strings (JWT-ish, service keys) outside the allowed publishable key in site/config.js."""
import hashlib, json, os, re, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
DENY = set(json.load(open(os.path.join(HERE, "denylist.json"))))
SKIP_DIRS = {".git", "node_modules", "vendor", "__pycache__"}
SKIP_FILES = {"denylist.json", "package-lock.json"}

def scan_text(text):
    hits = []
    for w in set(re.findall(r"[A-Za-z0-9]+", text.lower())):
        if len(w) >= 4 and hashlib.sha256(w.encode()).hexdigest() in DENY: hits.append("token#" + hashlib.sha256(w.encode()).hexdigest()[:8])
    # slugs and joined digits
    for w in set(re.findall(r"[a-z0-9\-]{8,}", text.lower())):
        if hashlib.sha256(w.encode()).hexdigest() in DENY: hits.append("slug#" + hashlib.sha256(w.encode()).hexdigest()[:8])
    for m in re.finditer(r"\(?(\d{3})\)?[\s.\-]*(\d{3})[\s.\-]*(\d{4})", text):
        if hashlib.sha256((m.group(1) + m.group(2) + m.group(3)).encode()).hexdigest() in DENY: hits.append("phone")
    if re.search(r"sb_" + r"secret_|service" + r"_role|e" + r"yJ[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{30,}\.", text): hits.append("secret-shape")
    return hits

def scan_repo():
    bad = []
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            if f in SKIP_FILES: continue
            p = os.path.join(dp, f)
            try: t = open(p, encoding="utf-8").read()
            except Exception: continue
            h = scan_text(t)
            if h: bad.append((os.path.relpath(p, ROOT), sorted(set(h))))
    return bad

# planted control: pick any denylisted token we can reproduce? We cannot (hashes only) so plant via the real-looking path:
# The planted control is a token whose hash build_fixtures.py adds to the denylist.
probe = "ce" + "-leak-" + "control"   # assembled so this file does not contain the planted token
assert hashlib.sha256(probe.encode()).hexdigest() in DENY, "denylist missing the planted-control hash"
caught = scan_text("harmless line then " + probe)
print(("PASS " if caught else "FAIL ") + "planted control is caught", caught)
clean = not scan_text("a clean sentence about nothing")
print(("PASS " if clean else "FAIL ") + "clean text is not flagged")
bad = scan_repo()
print(("PASS " if not bad else "FAIL ") + "repo has no real identity token or secret", bad)
sys.exit(0 if (caught and clean and not bad) else 1)
