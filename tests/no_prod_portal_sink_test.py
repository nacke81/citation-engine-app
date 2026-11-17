"""Permanent guard (t_2ddc7067): no test may reach the PROD portal (platform supabase: citation_code_request, citation_verification, rpc/claim_code_request ...).

Why: portal.load_portal_env() reads its creds from CE_PORTAL_ENV, else the pointer file %LOCALAPPDATA%/citation-engine/portal_env_path.txt -> the prod
.env.prod.local, never from the process env. So a LOCAL run of a test that builds the real client (B.main(...) does P.Portal(*P.load_portal_env()))
sends real requests, including POST rpc/claim_code_request, which claims the oldest REAL 'requested' code request. CI has no creds, so it never showed.

Static scan of every tests/*.py (ast, no imports, no network): a file that imports portal / verify_bridge / verify_now must set
os.environ["CE_PORTAL_ENV"] to an expression containing a string constant with "no-such" (a path that does not exist, so the real client fails
closed at open() before any request) on a line BEFORE the first such import, and must never pop / del / setdefault it afterwards.
Run: python tests/no_prod_portal_sink_test.py (CI). Pure stdlib.
"""
import ast, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAR = "CE_PORTAL_ENV"
SINK_MODULES = {"portal", "verify_bridge", "verify_now"}
SELF = os.path.basename(__file__)


def imported_sink_lines(tree):
    lines = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            mods = [n.module or ""] + [a.name for a in n.names]
        else:
            continue
        if any(m.split(".")[0] in SINK_MODULES or m.split(".")[-1] in SINK_MODULES for m in mods):
            lines.append(n.lineno)
    return sorted(lines)


def _is_environ(node):
    return isinstance(node, ast.Attribute) and node.attr == "environ" and isinstance(node.value, ast.Name)   # os, or an alias (the fence line imports os as _fo)


def _fenced_value(v):
    """True when the assigned expression holds a string constant naming a non-existent file ('no-such...')."""
    return any(isinstance(c, ast.Constant) and isinstance(c.value, str) and "no-such" in c.value for c in ast.walk(v))


def events(tree):
    """[(lineno, kind)] kind in {'fence', 'bad_set', 'unset'} for every touch of os.environ[VAR]."""
    ev = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Subscript) and _is_environ(t.value) and isinstance(t.slice, ast.Constant) and t.slice.value == VAR:
                    ev.append((n.lineno, "fence" if _fenced_value(n.value) else "bad_set"))
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and _is_environ(n.func.value) and n.func.attr in ("pop", "setdefault", "update") \
                and ((n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == VAR) or n.func.attr == "update"):
            ev.append((n.lineno, "unset"))
        elif isinstance(n, ast.Delete):
            for t in n.targets:
                if isinstance(t, ast.Subscript) and _is_environ(t.value) and isinstance(t.slice, ast.Constant) and t.slice.value == VAR:
                    ev.append((n.lineno, "unset"))
    return sorted(ev)


def scan_source(name, src):
    tree = ast.parse(src)
    imports = imported_sink_lines(tree)
    if not imports:
        return []
    first, ev, problems = imports[0], events(tree), []
    before = [e for e in ev if e[0] < first]
    if not before or before[0][1] != "fence":
        problems.append("%s: imports portal/verify_bridge/verify_now at L%d without first setting %s to a 'no-such' path (a local run reaches the PROD portal)" % (name, first, VAR))
    bad = [e for e in ev if e[1] in ("bad_set", "unset")]
    if bad:
        problems.append("%s: L%d re-points or removes %s (%s)" % (name, bad[0][0], VAR, bad[0][1]))
    return problems


def scan_dir(directory):
    out = []
    for fn in sorted(os.listdir(directory)):
        if fn.endswith(".py") and fn != SELF:
            with open(os.path.join(directory, fn), encoding="utf-8") as f:
                out += scan_source(fn, f.read())
    return out


ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (("  [" + d + "]") if d else ""), flush=True)


FENCE = "import os\nos.environ['CE_PORTAL_ENV'] = os.path.join(HERE, 'no-such.env')\n"
# --- the scanner itself, on synthetic sources (negative paths) ---
check("P1 imports portal, no fence -> flagged", scan_source("x_test.py", "import portal as P\n"))
check("P2 fence AFTER the import -> flagged", scan_source("x_test.py", "import os\nimport verify_bridge as B\nos.environ['CE_PORTAL_ENV'] = '/no-such.env'\n"))
check("P3 fence before the import -> clean", scan_source("x_test.py", FENCE + "import verify_bridge as B\n") == [])
check("P4 from-import of verify_now without a fence -> flagged", scan_source("x_test.py", "from verify_now import go\n"))
check("P5 CE_PORTAL_ENV set to a real-looking path -> flagged", scan_source("x_test.py", "import os\nos.environ['CE_PORTAL_ENV'] = '/real/.env.prod.local'\nimport portal\n"))
check("P6 fence then popped -> flagged", scan_source("x_test.py", FENCE + "import portal\nos.environ.pop('CE_PORTAL_ENV')\n"))
check("P7 fence then re-pointed -> flagged", scan_source("x_test.py", FENCE + "import portal\nos.environ['CE_PORTAL_ENV'] = 'C:/prod.env'\n"))
check("P8 file importing none of them is skipped", scan_source("x_test.py", "import json, transitions\n") == [])
check("P9 import inside a function, fence at top -> clean", scan_source("x_test.py", FENCE + "def f():\n    import portal\n") == [])

# --- the real tests/ tree ---
real = scan_dir(HERE)
for p in real:
    print("  OFFENDER " + p)
check("P10 every tests/*.py that imports portal / verify_bridge / verify_now fences CE_PORTAL_ENV before the import", not real, "%d offender(s)" % len(real))

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
