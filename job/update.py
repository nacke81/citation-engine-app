"""Fast-forward the runtime clone to origin/main before the weekly run.

Fails closed: on any problem it prints `UPDATE FAILED: <reason>` and leaves the
clone exactly as it was, so the run proceeds on the current commit. Never resets,
forces, checks out, or deletes anything. Always exits 0.

usage: python update.py [repo_dir]
"""
import os
import subprocess
import sys


def git(repo, *args):
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True)
    return (p.returncode, p.stdout.decode("utf-8", "replace").strip(),
            p.stderr.decode("utf-8", "replace").strip())


def _short(s):
    return " ".join(s.split())[:300]


def head(repo):
    rc, out, _ = git(repo, "rev-parse", "--short=7", "HEAD")
    return out if rc == 0 else "unknown"


def dirty_lines(repo):
    rc, out, err = git(repo, "status", "--porcelain")
    if rc != 0:
        return None, err
    return [l for l in out.splitlines() if l.strip() and "__pycache__" not in l], ""


def check_origin_compiles(repo):
    """Compile every job/*.py on origin/main in memory. Returns an error string or ''."""
    rc, out, err = git(repo, "ls-tree", "--name-only", "origin/main", "job/")
    if rc != 0:
        return "ls-tree origin/main: " + _short(err)
    names = [n for n in out.splitlines() if n.endswith(".py")]
    if not names:
        return "no job/*.py on origin/main"
    for n in names:
        p = subprocess.run(["git", "-C", repo, "show", "origin/main:" + n], capture_output=True)
        if p.returncode != 0:
            return "git show %s failed" % n
        try:
            compile(p.stdout, n, "exec")
        except SyntaxError as e:
            return "py_compile %s line %s: %s" % (n, e.lineno, e.msg)
    return ""


def update(repo):
    """Returns (status, message). status in OK, NOOP, FAILED."""
    lines, err = dirty_lines(repo)
    if lines is None:
        return "FAILED", "git status: " + _short(err)
    if lines:
        return "FAILED", "clone is dirty (%d change(s), first: %s)" % (len(lines), lines[0].strip())
    before = head(repo)
    rc, _, err = git(repo, "fetch", "origin")
    if rc != 0:
        return "FAILED", "git fetch origin: " + _short(err)
    bad = check_origin_compiles(repo)
    if bad:
        return "FAILED", "origin/main does not compile: " + bad
    rc, _, err = git(repo, "merge", "--ff-only", "origin/main")
    if rc != 0:
        return "FAILED", "fast-forward refused: " + _short(err)
    after = head(repo)
    if after == before:
        return "NOOP", "already at origin/main"
    return "OK", "%s -> %s" % (before, after)


def main(argv):
    repo = argv[1] if len(argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        status, msg = update(repo)
    except Exception as e:  # never block the weekly run
        status, msg = "FAILED", "unexpected %s: %s" % (type(e).__name__, _short(str(e)))
    if status == "FAILED":
        print("UPDATE FAILED: " + msg)
    else:
        print("UPDATE %s: %s" % (status, msg))
    print("RUNNING ON " + head(repo))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
