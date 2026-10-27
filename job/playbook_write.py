"""Write a build playbook into the vault (t_f707b644).

The agent's write_file refuses to overwrite a playbook it has already read. This helper replaces one safely: the text goes to a temp file in the
SAME directory, then os.replace swaps it in (atomic on one volume, so a reader never sees half a file).

Refuses: any path that does not resolve to a *.md file directly inside the playbooks/build directory (no `..`, no other folder, no sub-folder,
no symlink out, no drive switch), and empty text. Needs no network and reads no secret.

Usage:  python job/playbook_write.py <site>.md --from <file with the new markdown>      (name only, or a full path inside playbooks/build)
        python job/playbook_write.py <site>.md --stdin
From code: playbook_write.write_playbook("acompio.com.md", text)
"""
import os, sys, tempfile

PLAYBOOK_DIR = os.environ.get("CE_PLAYBOOK_DIR") or "C:/Obsidian/NackeMedia_v2/Projects/citation-engine/playbooks/build"


class PlaybookWriteRefused(Exception):
    pass


def resolve(name, base=None):
    """-> absolute target path inside the playbooks/build directory, or PlaybookWriteRefused."""
    root = os.path.realpath(base or PLAYBOOK_DIR)
    if not name or "\x00" in name:
        raise PlaybookWriteRefused("empty or invalid playbook name")
    cand = name if os.path.isabs(name) or ":" in name else os.path.join(root, name)
    target = os.path.realpath(cand)
    if os.path.normcase(os.path.dirname(target)) != os.path.normcase(root):
        raise PlaybookWriteRefused("%r is not directly inside %s (only playbooks/build is writable)" % (name, root))
    if not target.lower().endswith(".md") or os.path.basename(target).startswith("."):
        raise PlaybookWriteRefused("a playbook is a *.md file, got %r" % os.path.basename(target))
    if os.path.islink(cand) or (os.path.exists(target) and os.path.isdir(target)):
        raise PlaybookWriteRefused("%r is a link or a directory" % name)
    return target


def write_playbook(name, text, base=None):
    """Atomic replace (or create). Returns the path written."""
    if not isinstance(text, str) or not text.strip():
        raise PlaybookWriteRefused("refusing to write an empty playbook")
    target = resolve(name, base)
    d = os.path.dirname(target)
    if not os.path.isdir(d):
        raise PlaybookWriteRefused("playbooks/build directory does not exist: %s" % d)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".pbw-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text if text.endswith("\n") else text + "\n")
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, target)
    except Exception:
        if os.path.exists(tmp): os.unlink(tmp)
        raise
    return target


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="Atomically replace a playbook in playbooks/build")
    a.add_argument("name", help="<site>.md, or a full path inside playbooks/build")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--from", dest="src", help="file holding the new markdown")
    g.add_argument("--stdin", action="store_true")
    n = a.parse_args(argv)
    try:
        text = sys.stdin.read() if n.stdin else open(n.src, encoding="utf-8").read()
        print("wrote", write_playbook(n.name, text))
        return 0
    except (PlaybookWriteRefused, OSError) as e:
        print("REFUSED: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
