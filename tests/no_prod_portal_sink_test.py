"""Permanent guard (t_2ddc7067): no test may reach the PROD portal (platform supabase: citation_code_request, citation_verification, rpc/claim_code_request ...).

Why: portal.load_portal_env() reads its creds from CE_PORTAL_ENV, else the pointer file %LOCALAPPDATA%/citation-engine/portal_env_path.txt -> the prod
.env.prod.local, never from the process env. So a LOCAL run of a test that builds the real client (B.main(...) does P.Portal(*P.load_portal_env()))
sends real requests, including POST rpc/claim_code_request, which claims the oldest REAL 'requested' code request. CI has no creds, so it never showed.

The sink set is the TRANSITIVE closure over job/*.py imports: portal / verify_bridge / verify_now plus every job module that imports one of them,
directly or through another job module (transitions.py, run.py, ... build a real prod Portal when no fake is passed: portal or P.Portal(*P.load_portal_env())).

Static scan of every tests/*.py (ast, no imports, no network): a file that imports any module in that closure must set
os.environ["CE_PORTAL_ENV"] to an expression containing a string constant with "no-such" (a path that does not exist, so the real client fails
closed at open() before any request) on a line BEFORE the first such import, and must never pop / del / setdefault it afterwards.
Run: python tests/no_prod_portal_sink_test.py (CI). Pure stdlib.
"""
import ast, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
VAR = "CE_PORTAL_ENV"
DIRECT_SINKS = {"portal", "verify_bridge", "verify_now"}
JOB_DIR = os.path.join(os.path.dirname(HERE), "job")
SELF = os.path.basename(__file__)


def _imported_names(tree):
    """Every module name a tree imports anywhere (top level or inside a function): import a.b -> a, a.b ; from a import b -> a, b."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                out |= {a.name.split(".")[0], a.name.split(".")[-1]}
        elif isinstance(n, ast.ImportFrom):
            out |= {(n.module or "").split(".")[0], (n.module or "").split(".")[-1]} | {a.name for a in n.names}
    return out


def sink_closure(job_dir=None):
    """Direct sinks + every module in job_dir that imports a sink, directly or via another job module (fixpoint)."""
    job_dir = job_dir or JOB_DIR
    graph = {}
    for fn in os.listdir(job_dir):
        if fn.endswith(".py"):
            with open(os.path.join(job_dir, fn), encoding="utf-8") as f:
                graph[fn[:-3]] = _imported_names(ast.parse(f.read()))
    sinks, grew = set(DIRECT_SINKS), True
    while grew:
        grew = False
        for mod, imps in graph.items():
            if mod not in sinks and imps & sinks:
                sinks.add(mod); grew = True
    return sinks


def imported_sink_lines(tree, sinks=None):
    sinks = DIRECT_SINKS if sinks is None else sinks
    lines = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            mods = [n.module or ""] + [a.name for a in n.names]
        else:
            continue
        if any(m.split(".")[0] in sinks or m.split(".")[-1] in sinks for m in mods):
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


def scan_source(name, src, sinks=None):
    tree = ast.parse(src)
    imports = imported_sink_lines(tree, SINKS if sinks is None else sinks)
    if not imports:
        return []
    first, ev, problems = imports[0], events(tree), []
    before = [e for e in ev if e[0] < first]
    if not before or before[0][1] != "fence":
        problems.append("%s: imports a module that reaches the prod portal (portal / verify_bridge / verify_now or a job module importing them) at L%d without first setting %s to a 'no-such' path (a local run reaches the PROD portal)" % (name, first, VAR))
    bad = [e for e in ev if e[1] in ("bad_set", "unset")]
    if bad:
        problems.append("%s: L%d re-points or removes %s (%s)" % (name, bad[0][0], VAR, bad[0][1]))
    return problems


SINKS = sink_closure()


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
check("P8 file importing none of them is skipped", scan_source("x_test.py", "import json, sys\n") == [])
check("P9 import inside a function, fence at top -> clean", scan_source("x_test.py", FENCE + "def f():\n    import portal\n") == [])

# --- transitive closure (t_2ddc7067 round 2): job modules that reach the portal through another job module ---
check("P11 `import transitions` unfenced -> flagged (transitions builds P.Portal(*P.load_portal_env()) when no fake is passed)", scan_source("x_test.py", "import sys\nsys.path.insert(0, 'job')\nimport transitions\n"))
check("P12 importing the run module (plain and from-form) unfenced -> flagged", scan_source("x_test.py", "imp" "ort ru" "n\n") and scan_source("x_test.py", "from ru" "n imp" "ort main\n"))   # split literals: runs_dir_check.py greps this file for a bare run import
check("P13 `import transitions` after a fence -> clean", scan_source("x_test.py", FENCE + "import transitions\n") == [])
check("P14 the closure holds the direct sinks and the known transitive importers", {"portal", "verify_bridge", "verify_now", "transitions", "run"} <= SINKS, "%d modules" % len(SINKS))
check("P15 a job module that touches no sink stays out of the closure", "cfg" not in SINKS and "core" not in SINKS)
_tmp = tempfile.mkdtemp()
for _n, _src in (("portal", "X = 1\n"), ("b", "import portal\n"), ("a", "import b\n"), ("c", "from a import thing\n"), ("d", "import json\n")):
    with open(os.path.join(_tmp, _n + ".py"), "w") as _f:
        _f.write(_src)
_syn = sink_closure(_tmp)
check("P16 synthetic chain c -> a -> b -> portal: c, a, b in the closure, d not", {"a", "b", "c"} <= _syn and "d" not in _syn, str(sorted(_syn)))
check("P17 a test importing the chain head `a` unfenced -> flagged; fenced -> clean", scan_source("x_test.py", "import a\n", _syn) and scan_source("x_test.py", FENCE + "import a\n", _syn) == [])
shutil.rmtree(_tmp, ignore_errors=True)
# mutation: a direct-only scan (the round-1 guard) must MISS what the closure catches; if it did not, P11 would prove nothing
check("P18 mutation: direct-only sink set misses `import transitions` (so P11 depends on the closure)", scan_source("x_test.py", "import transitions\n", DIRECT_SINKS) == [] and scan_source("x_test.py", "import transitions\n"))

# --- the real tests/ tree ---
real = scan_dir(HERE)
for p in real:
    print("  OFFENDER " + p)
check("P10 every tests/*.py that imports portal / verify_bridge / verify_now or a job module reaching them fences CE_PORTAL_ENV before the import", not real, "%d offender(s)" % len(real))

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
