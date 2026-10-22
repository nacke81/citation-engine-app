"""job/update.py: fast-forward, fail closed, never destructive. Local bare origin, no network."""
import os, subprocess, sys, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE = os.path.join(HERE, "..", "job", "update.py")
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def g(cwd, *a):
    p = subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True, env=ENV)
    assert p.returncode == 0, (a, p.stderr)
    return p.stdout.strip()


def commit(repo, name, text, msg):
    path = os.path.join(repo, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        f.write(text)
    g(repo, "add", "-A")
    g(repo, "commit", "-m", msg)


def run(clone):
    p = subprocess.run([sys.executable, UPDATE, clone], capture_output=True, text=True)
    assert p.returncode == 0, "must always exit 0"
    return p.stdout


def setup(tmp):
    origin = os.path.join(tmp, "origin.git")
    work = os.path.join(tmp, "work")
    clone = os.path.join(tmp, "clone")
    subprocess.run(["git", "init", "--bare", "-b", "main", origin], check=True, capture_output=True)
    subprocess.run(["git", "clone", origin, work], check=True, capture_output=True)
    g(work, "checkout", "-B", "main")
    commit(work, "job/run.py", "print('v1')\n", "v1")
    g(work, "push", "-u", "origin", "main")
    subprocess.run(["git", "clone", origin, clone], check=True, capture_output=True)
    return origin, work, clone


def case(name, fn):
    tmp = tempfile.mkdtemp()
    try:
        fn(*setup(tmp))
        print("ok", name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def v2(work):
    commit(work, "job/run.py", "print('v2')\n", "v2")
    g(work, "push")


def t_ff(origin, work, clone):
    v2(work)
    out = run(clone)
    want = g(work, "rev-parse", "--short=7", "HEAD")
    assert "UPDATE OK" in out and "RUNNING ON " + want in out, out
    assert g(clone, "rev-parse", "--short=7", "HEAD") == want


def t_noop(origin, work, clone):
    out = run(clone)
    assert "UPDATE NOOP" in out and "UPDATE FAILED" not in out, out


def t_dirty(origin, work, clone):
    v2(work)
    before = g(clone, "rev-parse", "HEAD")
    p = os.path.join(clone, "job", "run.py")
    open(p, "w").write("local edit\n")
    out = run(clone)
    assert "UPDATE FAILED: clone is dirty" in out and "RUNNING ON " + before[:7] in out, out
    assert g(clone, "rev-parse", "HEAD") == before
    assert open(p).read() == "local edit\n"


def t_untracked_dirty(origin, work, clone):
    open(os.path.join(clone, "stray.txt"), "w").write("x")
    assert "UPDATE FAILED" in run(clone)


def t_pycache_ignored(origin, work, clone):
    v2(work)
    d = os.path.join(clone, "job", "__pycache__")
    os.makedirs(d)
    open(os.path.join(d, "x.pyc"), "w").write("x")
    assert "UPDATE OK" in run(clone)


def t_diverged(origin, work, clone):
    v2(work)
    commit(clone, "job/local.py", "x=1\n", "local")
    before = g(clone, "rev-parse", "HEAD")
    out = run(clone)
    assert "UPDATE FAILED: fast-forward refused" in out, out
    assert g(clone, "rev-parse", "HEAD") == before


def t_syntax_error(origin, work, clone):
    commit(work, "job/bad.py", "def (:\n", "bad")
    g(work, "push")
    before = g(clone, "rev-parse", "HEAD")
    out = run(clone)
    assert "UPDATE FAILED: origin/main does not compile" in out and "bad.py" in out, out
    assert g(clone, "rev-parse", "HEAD") == before
    assert not os.path.exists(os.path.join(clone, "job", "bad.py"))


def t_fetch_fail(origin, work, clone):
    g(clone, "remote", "set-url", "origin", os.path.join(origin, "nope"))
    before = g(clone, "rev-parse", "HEAD")
    out = run(clone)
    assert "UPDATE FAILED: git fetch origin" in out, out
    assert g(clone, "rev-parse", "HEAD") == before


def t_not_a_repo(origin, work, clone):
    d = os.path.join(os.path.dirname(clone), "plain")
    os.makedirs(d)
    assert "UPDATE FAILED" in run(d)


def t_cmd_safe(origin, work, clone):
    s = open(os.path.join(HERE, "..", "job", "weekly.cmd")).read().lower()
    for bad in ("reset", "--force", "rmdir", "rd /", "del ", "clean", "checkout", "push"):
        assert bad not in s, bad
    assert "update.py" in s and s.index("update.py") < s.index("run.py")
    u = open(UPDATE).read()
    for bad in ('"reset"', '"clean"', '"checkout"', '"push"', "--force", "os.remove", "rmtree"):
        assert bad not in u, bad


for n, f in list(globals().items()):
    if n.startswith("t_"):
        case(n, f)
print("update tests pass")
