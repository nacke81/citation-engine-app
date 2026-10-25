"""Build Chrome tests. Run: python tests/build_chrome_test.py (CI). No browser is started, no network."""
import os, sys, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job"))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

if sys.platform != "win32":
    print("SKIP: owned_chrome is Windows-only (Job Objects)"); sys.exit(0)
import owned_chrome as OC
import build_chrome as B
import build_proof as BP

tmp = tempfile.mkdtemp()
prof = os.path.join(tmp, "build-profile")
oc = B.build_chrome(prof, 9333)
check("B1 build chrome uses the given persistent profile and fixed port", oc._persist and oc._want == prof and oc.port == 9333)
check("B2 default build profile is under citation-engine/build-profile", B.PROFILE.replace("\\", "/").endswith("citation-engine/build-profile") and B.PORT == 9333)
t = OC.OwnedChrome()
check("B3 default OwnedChrome is still throwaway (finder unchanged)", not t._persist and t.port is None)
# close() on a persistent profile never deletes it (no process started: close is safe)
os.makedirs(prof); open(os.path.join(prof, "Cookies"), "w").write("x")
oc.profile = prof; oc.close()
check("B4 close keeps the persistent profile (logins survive)", os.path.exists(os.path.join(prof, "Cookies")))
tp = os.path.join(tmp, "throw"); os.makedirs(tp); t.profile = tp; t.close()
check("B5 close deletes a throwaway profile", not os.path.exists(tp))
# proof classifier
check("B6 challenge text -> challenge", BP.classify(200, "Human Verification drag and drop challenge " * 10, "") == "challenge")
check("B7 403 with a blank body -> 403", BP.classify(403, "Forbidden", "") == "403")
check("B8 real page -> loads", BP.classify(200, "Senior Care results " * 30, "<html>") == "loads")
check("B9 DataDome page -> challenge", BP.classify(403, "x", "<script src=captcha-delivery.com>") == "challenge")
src = open(os.path.join(HERE, "..", "job", "build_chrome.py"), encoding="utf-8").read()
check("B10 build_chrome.py has no portal, transitions or form code", not any(w in src for w in ("import portal", "transitions", "fill(", ".click(", "submit_row")))
psrc = open(os.path.join(HERE, "..", "job", "build_proof.py"), encoding="utf-8").read()
check("B11 build_proof.py never clicks, fills or submits", not any(w in psrc for w in (".click(", ".fill(", ".type(", "keyboard", "portal", "transitions")))
shutil.rmtree(tmp, ignore_errors=True)
print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
