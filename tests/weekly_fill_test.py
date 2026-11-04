"""Weekly job calls the fill-only reason_code fill AFTER sync_run (t_c3087efc follow-up). Fake db; no network."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); JOB = os.path.join(os.path.dirname(HERE), "job")
sys.path.insert(0, JOB)
import directories as D, run as R

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

order = []
class Fake:
    owner = "o1"
    def call(self, method, path, body=None, prefer=None):
        order.append((method, path, body))
        return [{"directory": "a.example", "reason_code": None}] if method == "GET" else None

Q = {"fix_queue": [{"id": "a", "directory": "a.example", "state": "needs-human",
                    "history": [{"at": "2026-11-04", "from": "queued", "to": "needs-human", "note": "n", "reason_code": "paid"}]}]}

real_sync = D.sync_run
D.sync_run = lambda *a, **k: (order.append(("SYNC", "", None)), {"checks": 0})[1]
ok_run = R.directories_step([], "2026-11-08", db=Fake(), queue=Q)
D.sync_run = real_sync
kinds = [o[0] for o in order]
patches = [o for o in order if o[0] == "PATCH"]
check("W1 step returns True", ok_run is True)
check("W2 fill PATCH happens after sync_run", "SYNC" in kinds and patches and kinds.index("SYNC") < kinds.index("PATCH"))
check("W3 PATCH is one column reason_code=paid, filtered is.null", len(patches) == 1 and patches[0][2] == {"reason_code": "paid"} and "reason_code=is.null" in patches[0][1])

order.clear()
D.sync_run = lambda *a, **k: {"checks": 0}
class Boom(Fake):
    def call(self, method, path, body=None, prefer=None):
        if method == "GET": raise RuntimeError("down")
        return None
check("W4 fill failure is non-fatal", R.directories_step([], "2026-11-08", db=Boom(), queue=Q) is True)
order.clear()
check("W5 no queue -> no fill calls", R.directories_step([], "2026-11-08", db=Fake(), queue=None) is True and not [o for o in order if o[0] == "PATCH"])
D.sync_run = real_sync

print("%d/%d passed" % (sum(ok), len(ok))); sys.exit(0 if all(ok) else 1)
