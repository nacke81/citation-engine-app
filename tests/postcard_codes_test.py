"""Postcard code read-and-clear tests (no network). Run: python tests/postcard_codes_test.py  (CI). Exit 1 on any failure."""
import os, sys, io, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import postcard_codes as PC

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (("  [%s]" % d) if d else ""), flush=True)

class FakePortal:
    """Mimics consume_postcard_code: returns the stored code once, then null."""
    def __init__(self, store): self.store, self.calls = dict(store), []
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path, body))
        return self.store.pop(body["p_verification_id"], None)

VID = "11111111-1111-1111-1111-111111111111"

p = FakePortal({VID: "AB12CD34"})
buf = io.StringIO()
with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
    first = PC.consume(p, VID)
    second = PC.consume(p, VID)
check("first read returns the code", first == "AB12CD34")
check("second read returns None (cleared)", second is None)
check("calls the service RPC by POST", p.calls[0] == ("POST", "rpc/consume_postcard_code", {"p_verification_id": VID}))
check("nothing printed or logged", buf.getvalue() == "")

class Boom:
    def call(self, *a, **k): raise RuntimeError("boom AB12CD34")
try:
    PC.consume(Boom(), VID); err = ""
except PC.PostcardCodeError as e:
    err = str(e)
check("error names the id and the exception type only", VID in err and "RuntimeError" in err and "boom" not in err)

class Odd:
    def call(self, *a, **k): return "<script>"
try:
    PC.consume(Odd(), VID); odd = False
except PC.PostcardCodeError:
    odd = True
check("malformed value from the portal is refused", odd)
try:
    PC.consume(p, ""); empty = False
except PC.PostcardCodeError:
    empty = True
check("empty id refused with no call", empty and len(p.calls) == 2)

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
