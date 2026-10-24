"""No test may create anything in the real runs folder.
Source scan: any tests/*.py that imports run.py must assign CE_RUNS earlier in the file.
Planted control: a synthetic bad source must be flagged.
Snapshot: the real runs folder (if present) must not grow while this check runs.
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REAL = os.path.expandvars("%LOCALAPPDATA%/citation-engine/runs")
IMPORTS_RUN = re.compile(r"^[^#\n]*\bimport\b[^#\n]*\brun\b(?!\w)|^\s*from\s+run\s+import", re.M)
SETS_ENV = re.compile(r"""environ\[\s*["']CE_RUNS["']\s*\]\s*=|environ\.setdefault\(\s*["']CE_RUNS["']""")
fails = []


def bad(src):
    """True when src imports run before (or without) setting CE_RUNS."""
    m = IMPORTS_RUN.search(src)
    if not m:
        return False
    s = SETS_ENV.search(src)
    return not (s and s.start() < m.start())


def snap():
    return set(os.listdir(REAL)) if os.path.isdir(REAL) else set()


before = snap()
n = 0
for f in sorted(os.listdir(HERE)):
    if not f.endswith(".py") or f == os.path.basename(__file__):
        continue
    src = open(os.path.join(HERE, f), encoding="utf-8").read()
    if IMPORTS_RUN.search(src):
        n += 1
        if bad(src):
            fails.append(f)
            print("FAIL", f, "imports run before setting CE_RUNS")
        else:
            print("ok  ", f)

control = 'import os, sys\nimport run as jobrun\nos.environ["CE_RUNS"] = "x"\n'
good = 'import os\nos.environ["CE_RUNS"] = "x"\nimport run as jobrun\n'
if not bad(control):
    fails.append("control")
    print("FAIL planted control not flagged")
if bad(good):
    fails.append("good-control")
    print("FAIL good control flagged")
if n < 8:
    fails.append("scan-too-small")
    print("FAIL scan saw only", n, "files that import run")
if snap() - before:
    fails.append("grew")
    print("FAIL real runs folder grew:", sorted(snap() - before))

print("files importing run:", n, "| failures:", len(fails))
sys.exit(1 if fails else 0)
