"""Register the Verify Now bridge in Task Scheduler (t_c814f7b5).

schtasks /create /xml rejects the repo's UTF-8 job/verify_bridge_task.xml ("unable to switch the encoding"); it wants UTF-16.
This reads the UTF-8 file, writes a UTF-16 LE (BOM) temp copy with a matching declaration, runs schtasks /create, removes the copy.

  python job\\register_verify_bridge.py                      register CitationEngineVerifyBridge (refuses if it exists)
  python job\\register_verify_bridge.py --dry-run            print the schtasks command, run nothing
  python job\\register_verify_bridge.py --name N --start-boundary 2030-01-01T00:00:00   throwaway test task
  python job\\register_verify_bridge.py --force              overwrite an existing task of that name (/f)
"""
import argparse, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
XML = os.path.join(HERE, "verify_bridge_task.xml")
DEFAULT_NAME = "CitationEngineVerifyBridge"


def to_utf16_xml(text, start_boundary=None):
    """UTF-8 task XML text -> bytes schtasks accepts (UTF-16 LE with BOM, declaration says UTF-16)."""
    out, n = re.subn(r'(<\?xml[^>]*encoding=)"[^"]*"', r'\1"UTF-16"', text, count=1)
    if n != 1:
        raise ValueError("task XML has no encoding declaration")
    if start_boundary:
        if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", start_boundary):
            raise ValueError("start boundary must look like 2030-01-01T00:00:00")
        out, n = re.subn(r"<StartBoundary>[^<]*</StartBoundary>", "<StartBoundary>%s</StartBoundary>" % start_boundary, out)
        if n < 1:
            raise ValueError("task XML has no StartBoundary")
    return b"\xff\xfe" + out.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-16-le")


def schtasks_cmd(name, xml_path, force=False):
    return ["schtasks", "/create", "/tn", name, "/xml", xml_path] + (["/f"] if force else [])


def register(name=DEFAULT_NAME, start_boundary=None, force=False, dry_run=False, xml_path=XML, runner=subprocess.run):
    with open(xml_path, encoding="utf-8") as f:
        data = to_utf16_xml(f.read(), start_boundary)
    if dry_run:
        print(" ".join(schtasks_cmd(name, "<utf16 temp copy>", force)))
        return 0
    fd, tmp = tempfile.mkstemp(suffix=".xml", prefix="ce-verify-bridge-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        r = runner(schtasks_cmd(name, tmp, force))
        return r.returncode
    finally:
        try: os.remove(tmp)
        except OSError: pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--name", default=DEFAULT_NAME)
    ap.add_argument("--start-boundary", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    return register(a.name, a.start_boundary, a.force, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
