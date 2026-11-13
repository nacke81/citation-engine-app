"""register_verify_bridge tests (t_c814f7b5). No schtasks is ever run. Run: python tests/register_verify_bridge_test.py (CI). Exit 1 on any failure."""
import os, re, sys, types
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import register_verify_bridge as R

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ((" [%s]" % (d,)) if d != "" else ""), flush=True)

raw = open(R.XML, "rb").read()
text = raw.decode("utf-8")
check("repo XML is UTF-8 with no BOM (the reason the script exists)", not raw.startswith((b"\xff\xfe", b"\xef\xbb\xbf")))
check("Description names the script", "register_verify_bridge.py" in text)

b = R.to_utf16_xml(text)
check("output starts with UTF-16 LE BOM", b[:2] == b"\xff\xfe")
dec = b.decode("utf-16")
check("declaration says UTF-16", re.match(r'<\?xml[^>]*encoding="UTF-16"', dec) is not None)
check("body otherwise unchanged", dec.replace("\r\n", "\n").split("?>", 1)[1] == text.replace("\r\n", "\n").split("?>", 1)[1])
check("default leaves StartBoundary alone", "<StartBoundary>2026-11-12T00:00:00</StartBoundary>" in dec)
d2 = R.to_utf16_xml(text, "2030-01-01T00:00:00").decode("utf-16")
check("start override applied", "<StartBoundary>2030-01-01T00:00:00</StartBoundary>" in d2 and "2026-11-12T00:00:00" not in d2)
for bad in ("tomorrow", "2030-01-01"):
    try: R.to_utf16_xml(text, bad); check("bad start refused " + bad, False)
    except ValueError: check("bad start refused " + bad, True)
try: R.to_utf16_xml("<Task/>"); check("no declaration refused", False)
except ValueError: check("no declaration refused", True)

check("no /f by default", "/f" not in R.schtasks_cmd("X", "p"))
check("/f only with force", R.schtasks_cmd("X", "p", True)[-1] == "/f")

seen = {}
def fake(cmd):
    seen["cmd"] = cmd; seen["bytes"] = open(cmd[cmd.index("/xml") + 1], "rb").read(); seen["path"] = cmd[cmd.index("/xml") + 1]
    return types.SimpleNamespace(returncode=0)
rc = R.register("CEVerifyBridgeRegTest", "2030-01-01T00:00:00", runner=fake)
check("register runs schtasks create with the given name", rc == 0 and seen["cmd"][:4] == ["schtasks", "/create", "/tn", "CEVerifyBridgeRegTest"])
check("schtasks was handed UTF-16 bytes", seen["bytes"][:2] == b"\xff\xfe" and "2030-01-01T00:00:00" in seen["bytes"].decode("utf-16"))
check("temp copy removed after success", not os.path.exists(seen["path"]))

def boom(cmd):
    seen["path"] = cmd[cmd.index("/xml") + 1]; raise OSError("schtasks missing")
try: R.register(runner=boom)
except OSError: pass
check("temp copy removed when schtasks fails", not os.path.exists(seen["path"]))

def fail(cmd): return types.SimpleNamespace(returncode=1)
check("schtasks failure code is passed through", R.register(runner=fail) == 1)
def never(cmd): raise AssertionError("ran")
check("dry run runs nothing", R.register(dry_run=True, runner=never) == 0)

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
