"""Saved-page fixtures must never carry a Google API key (t_6df6203a). Run: python tests/fixture_scrub_test.py (CI). No network."""
import os, re, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fixture_scrub as S

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

KEY = "AIza" + "Sy" + "A" * 33            # synthetic, 39 chars
KEY2 = "AIza" + "-_" + "b9" * 16 + "Z"    # synthetic, 39 chars, uses - and _
assert len(KEY) == 39 and len(KEY2) == 39 and S.PATTERN.fullmatch(KEY) and S.PATTERN.fullmatch(KEY2)

page = '<script src="https://maps.google.com/maps/api/js?sensor=false&amp;libraries=places&key=%s"></script>' % KEY
out = S.scrub(page)
check("S1 key in a maps script url is replaced by the placeholder", KEY not in out and "key=REDACTED_GOOGLE_KEY\"" in out, out)
check("S2 surrounding markup is untouched", out.replace("REDACTED_GOOGLE_KEY", KEY) == page)
two = S.scrub("a %s b %s c" % (KEY, KEY2))
check("S3 two keys on one line are both removed", "AIza" not in two and two.count("REDACTED_GOOGLE_KEY") == 2, two)
check("S4 scrub is idempotent", S.scrub(out) == out)
short = "AIza" + "x" * 34
check("S5 a 34-char AIza lookalike is not a key and is left alone", S.scrub(short) == short)
check("S6 text with no key is returned unchanged", S.scrub("<p>hello</p>") == "<p>hello</p>")

d = tempfile.mkdtemp(prefix="scrub-")
p = os.path.join(d, "page.html"); open(p, "w", encoding="utf-8", newline="\n").write(page)
r = subprocess.run([sys.executable, os.path.join(HERE, "fixture_scrub.py"), p], capture_output=True, text=True)
after = open(p, encoding="utf-8").read()
check("S7 CLI rewrites the saved file in place", r.returncode == 0 and KEY not in after and "REDACTED_GOOGLE_KEY" in after, r.stdout + r.stderr)
check("S8 CLI output never echoes the key", KEY not in r.stdout + r.stderr)

# Guard: every committed fixture is clean. Walks the tree itself (no list to forget to update).
def leaks(root):
    bad = []
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            fp = os.path.join(dp, f)
            if S.PATTERN.search(open(fp, encoding="utf-8", errors="ignore").read()): bad.append(os.path.relpath(fp, root))
    return bad
FX = os.path.join(HERE, "fixtures")
check("G1 no file under tests/fixtures carries an AIza key", leaks(FX) == [], str(leaks(FX)))
dirty = tempfile.mkdtemp(prefix="scrub-g-"); open(os.path.join(dirty, "x.html"), "w").write(page)
check("G2 mutation: the guard does catch a fixture that has a key", leaks(dirty) == ["x.html"])

print("%d/%d" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
