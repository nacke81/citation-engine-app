"""Leak check: no real identity token anywhere in the repo. Tokens are held only as sha256 hashes (tests/denylist.json).
Planted control: a throwaway file holding a real-looking token must be CAUGHT, or this check fails (the check itself is broken).
Also refuses secret-looking strings (JWT-ish, service keys) outside the allowed publishable key in site/config.js."""
import hashlib, json, os, re, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
DENY = set(json.load(open(os.path.join(HERE, "denylist.json"))))
SKIP_DIRS = {".git", "node_modules", "vendor", "__pycache__"}
SKIP_FILES = {"denylist.json", "package-lock.json"}
GOOGLE_KEY = re.compile("AI" + "za[0-9A-Za-z_-]{35}")   # split so this file holds no key-shaped string

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
    if GOOGLE_KEY.search(text): hits.append("google-key-shape")   # whole-repo walk: scan_repo runs scan_text on every file (t_6df6203a)
    return hits

# t_282b646e: twilio/nm-public-line/*.js are byte-for-byte copies of the LIVE Functions (twilio/deploy.py diffs them against Twilio). Their header comments name the
# business and its PUBLISHED public-line number (the Directory listings' own number; the forward-to cell and every other number stay Service env vars). Exactly those
# three hashes are tolerated there and nowhere else: a different denylisted token, any other denylisted phone, or any secret shape in those files still fails.
PUBLIC_LINE_DIR = "twilio/nm-public-line"
PUBLIC_LINE_TOKENS = {"token#4eb743a1", "slug#355a15b3"}
PUBLIC_LINE_PHONE_SHA = "346741b4303804b1d5507df73bb62b2b8bfbd25da8c4fe780265aeb74da6172f"

def public_line_filter(text, hits):
    hits = [h for h in hits if h not in PUBLIC_LINE_TOKENS]
    if "phone" in hits:
        shas = {hashlib.sha256((m.group(1) + m.group(2) + m.group(3)).encode()).hexdigest() for m in re.finditer(r"\(?(\d{3})\)?[\s.\-]*(\d{3})[\s.\-]*(\d{4})", text)}
        if {s for s in shas if s in DENY} <= {PUBLIC_LINE_PHONE_SHA}: hits = [h for h in hits if h != "phone"]
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
            if os.path.relpath(p, ROOT).replace(os.sep, "/").startswith(PUBLIC_LINE_DIR + "/"): h = public_line_filter(t, h)
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
gprobe = "AI" + "za" + "Sy" + "Q" * 33   # planted Google-key control, assembled at runtime; must be caught
gcaught = "google-key-shape" in scan_text('<script src="https://maps.google.com/maps/api/js?key=' + gprobe + '"></script>')
print(("PASS " if gcaught else "FAIL ") + "planted Google-key control is caught")
pl_ok = not public_line_filter("// header\n" + "x" * 3, [])
pl_caught = bool(scan_text(probe)) and public_line_filter(probe, scan_text(probe)) == scan_text(probe)   # the planted control still fails inside the exempt dir
print((("PASS " if pl_ok and pl_caught else "FAIL ")) + "public-line exemption tolerates only its own hashes (planted control still caught there)")
bad = scan_repo()
print(("PASS " if not bad else "FAIL ") + "repo has no real identity token or secret", bad)
sys.exit(0 if (caught and clean and gcaught and pl_ok and pl_caught and not bad) else 1)
