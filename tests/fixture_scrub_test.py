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

# W: the builders' write path scrubs (t_6df6203a round 2). Helper tested directly; builders checked to use only the helper.
wd = tempfile.mkdtemp(prefix="scrub-w-")
for nl in (None, "\n"):
    wp = os.path.join(wd, "w.html")
    ret = S.write_fixture(wp, page, newline=nl)
    got = open(wp, encoding="utf-8", newline="").read()
    check("W1 write_fixture(newline=%r) lands with 0 keys" % nl, S.PATTERN.search(got) is None and "REDACTED_GOOGLE_KEY" in got and ret == got, got)
for b in ("build_fixtures.py", "build_resolver_fixtures.py"):
    src = open(os.path.join(HERE, b), encoding="utf-8").read()
    raw = re.findall(r"open\([^\n]*[\"']w[\"'][^\n]*\)\.write\(", src)
    check("W2 %s imports write_fixture and has no raw open(...,'w').write(" % b, "from fixture_scrub import write_fixture" in src and "write_fixture(" in src and not raw, str(raw))
mut = 'open(os.path.join(OUT, "x.html"), "w", encoding="utf-8").write(t)'
check("W3 mutation: the raw-write detector flags a builder that bypasses the helper", re.findall(r"open\([^\n]*[\"']w[\"'][^\n]*\)\.write\(", mut) != [])

# L: leak_check.py catches the Google-key shape across the whole repo walk, and the planted control can't go dead.
def run_leak(mutate):
    root = tempfile.mkdtemp(prefix="leak-"); td = os.path.join(root, "tests"); os.makedirs(td)
    src = open(os.path.join(HERE, "leak_check.py"), encoding="utf-8").read()
    if mutate: src = src.replace('hits.append("google-key-shape")', "pass"); assert "pass" in src
    open(os.path.join(td, "leak_check.py"), "w", encoding="utf-8").write(src)
    open(os.path.join(td, "denylist.json"), "w").write(open(os.path.join(HERE, "denylist.json")).read())
    return root, td
def leak_rc(root, td):
    r = subprocess.run([sys.executable, os.path.join(td, "leak_check.py")], capture_output=True, text=True); return r.returncode, r.stdout
root, td = run_leak(False)
rc, out = leak_rc(root, td)
check("L1 leak_check passes on a clean tree (planted control caught)", rc == 0 and "PASS planted Google-key control" in out, out)
os.makedirs(os.path.join(root, "docs", "deep")); open(os.path.join(root, "docs", "deep", "n.md"), "w").write("x " + KEY)   # outside tests/fixtures
rc, out = leak_rc(root, td)
check("L2 a key anywhere in the repo (not only tests/fixtures) fails leak_check", rc != 0 and "google-key-shape" in out, out)
root, td = run_leak(True)
rc, out = leak_rc(root, td)
check("L3 mutation: AIza shape removed -> the planted control FAILS", rc != 0 and "FAIL planted Google-key control" in out, out)

print("%d/%d" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
