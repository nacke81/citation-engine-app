"""Permanent guard (t_be2150cd): no test may reach the prod Directory DB (ce_directory_status / ce_directories).

Why: directories.DirDB() reads its creds from %LOCALAPPDATA%/hermes/.env, not from the process env, so a LOCAL run of a test that
reaches the sink with CE_DIRECTORIES_WRITE unset writes PROD (CI has no creds, so it never showed). Fixture rows a.example/b.example
and stale dnb.com/discoverourtown.com states landed in prod that way.

Static scan of every tests/*.py (ast, no imports, no network):
 1. a file that imports transitions / directories / recheck / buildrows / nm_transitions must set os.environ["CE_DIRECTORIES_WRITE"] = "0"
    on a line BEFORE the first such import, and must never set it to anything else;
 2. exception list ON_PURPOSE (sink on = "1" to exercise the writer): the file must set the flag before that import, and every call to
    record_transition / record_existing / record_proof / create_row / mirror_proof_quiet / sync_* made while the flag is not "0" must pass
    directories= or db= with a real expression (not None).
Run: python tests/no_prod_directory_sink_test.py (CI). Pure stdlib.
"""
import ast, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
FLAG = "CE_DIRECTORIES_WRITE"
SINK_MODULES = {"transitions", "directories", "recheck", "buildrows", "nm_transitions"}
ON_PURPOSE = {"mirror_proof_test.py", "recheck_promote_test.py", "directories_test.py"}
WRITERS = {"record_transition", "record_existing", "record_proof", "create_row", "mirror_proof_quiet"}
SELF = os.path.basename(__file__)


def is_writer(name):
    return name in WRITERS or name.startswith("sync_")


def imported_sink_lines(tree):
    lines = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            mods = [n.module or ""] + [a.name for a in n.names]
        else:
            continue
        if any(m.split(".")[-1] in SINK_MODULES or m.split(".")[0] in SINK_MODULES for m in mods):
            lines.append(n.lineno)
    return sorted(lines)


def _is_environ(node):
    return isinstance(node, ast.Attribute) and node.attr == "environ" and isinstance(node.value, ast.Name) and node.value.id == "os"


def flag_events(tree):
    """[(lineno, value)] for every os.environ[FLAG] = "x" (value str) and os.environ.pop(FLAG) (value None) / del."""
    ev = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Subscript) and _is_environ(t.value) and isinstance(t.slice, ast.Constant) and t.slice.value == FLAG:
                    v = n.value.value if isinstance(n.value, ast.Constant) else "<dynamic>"
                    ev.append((n.lineno, v))
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and _is_environ(n.func.value) and n.func.attr in ("pop", "setdefault") \
                and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == FLAG:
            ev.append((n.lineno, None if n.func.attr == "pop" else "<setdefault>"))
        elif isinstance(n, ast.Delete):
            for t in n.targets:
                if isinstance(t, ast.Subscript) and _is_environ(t.value) and isinstance(t.slice, ast.Constant) and t.slice.value == FLAG:
                    ev.append((n.lineno, None))
    return sorted(ev, key=lambda e: e[0])


def state_at(events, line):
    s = "unset"
    for ln, v in events:
        if ln < line:
            s = "unset" if v is None else v
    return s


def scan_source(name, src):
    """Return a list of problem strings for one test file's source."""
    tree = ast.parse(src)
    imports = imported_sink_lines(tree)
    if not imports:
        return []
    ev = flag_events(tree)
    first = imports[0]
    problems = []
    before = [e for e in ev if e[0] < first]
    want = {"0", "1"} if name in ON_PURPOSE else {"0"}
    if not before or before[0][1] not in want:
        problems.append("%s: imports a sink module at L%d without setting %s=\"0\" first (a local run reaches PROD)" % (name, first, FLAG))
    if name not in ON_PURPOSE:
        bad = [e for e in ev if e[1] != "0"]
        if bad:
            problems.append("%s: sets %s to %r at L%d (only allowed on the on-purpose list)" % (name, FLAG, bad[0][1], bad[0][0]))
    else:
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func.attr if isinstance(n.func, ast.Attribute) else (n.func.id if isinstance(n.func, ast.Name) else "")
            if not is_writer(fn) or state_at(ev, n.lineno) == "0":
                continue
            kws = {k.arg: k.value for k in n.keywords}
            fake = [kws[k] for k in ("directories", "db") if k in kws and getattr(kws[k], "value", 0) is not None]
            if not fake:
                problems.append("%s: L%d %s() runs with the sink on and no directories=/db= fake (writes PROD)" % (name, n.lineno, fn))
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


# --- the scanner itself, on synthetic sources (negative paths) ---
check("G1 no flag + imports transitions -> flagged", scan_source("x_test.py", "import transitions as T\n"))
check("G2 flag after the import -> flagged", scan_source("x_test.py", "import os\nimport recheck\nos.environ['CE_DIRECTORIES_WRITE']='0'\n"))
check("G3 flag '0' before import -> clean", scan_source("x_test.py", "import os\nos.environ['CE_DIRECTORIES_WRITE']='0'\nimport buildrows\n") == [])
check("G4 flag '1' off the allowlist -> flagged", scan_source("x_test.py", "import os\nos.environ['CE_DIRECTORIES_WRITE']='1'\nimport directories\n"))
check("G5 on-purpose file, writer with directories=None -> flagged",
      scan_source("mirror_proof_test.py", "import os\nos.environ['CE_DIRECTORIES_WRITE']='1'\nimport transitions as T\nT.record_transition('a', directories=None)\n"))
check("G6 on-purpose file, writer with a fake -> clean",
      scan_source("mirror_proof_test.py", "import os\nos.environ['CE_DIRECTORIES_WRITE']='1'\nimport transitions as T\nT.record_transition('a', directories=FDB)\n") == [])
check("G7 on-purpose file, bare writer while flag is 0 -> clean; after pop -> flagged",
      scan_source("directories_test.py", "import os\nos.environ['CE_DIRECTORIES_WRITE']='1'\nimport transitions as T\nos.environ['CE_DIRECTORIES_WRITE']='0'\nT.record_transition('a')\n") == []
      and scan_source("directories_test.py", "import os\nos.environ['CE_DIRECTORIES_WRITE']='1'\nimport transitions as T\nos.environ.pop('CE_DIRECTORIES_WRITE')\nT.record_transition('a')\n"))
check("G8 file importing no sink module is skipped", scan_source("x_test.py", "import json\n") == [])

# --- the real tests/ tree ---
real = scan_dir(HERE)
for p in real:
    print("  OFFENDER " + p)
check("G9 every tests/*.py that reaches the Directory sink switches it off (or fakes it) before the import", not real, "%d offender(s)" % len(real))

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
