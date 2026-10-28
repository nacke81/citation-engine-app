"""channel_label tests (t_ef2b05e9). Run: python tests/channel_label_test.py (CI). No network.

Every activity row carries channel_label "SEO & Local SEO" for live, submitted, pending-verify, rejected,
and the label travels in the on_conflict=client_id,source_ref merge-duplicates upsert body.
"""
import os, sys, copy, json, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ.pop("CE_ACTIVITIES_WRITE", None)
os.environ["CE_DIRECTORIES_WRITE"] = "0"  # Directory sink OFF: this test must never make a Directory call
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import portal as P  # noqa: E402
import transitions as T  # noqa: E402

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

LABEL = "SEO & Local SEO"
SCC = P.ALLOWED["SCC"]
ROW = {"id": "r1", "directory": "us-info.com"}

for st in ("live", "submitted", "pending-verify", "rejected"):
    rec = T.build_activity_record(SCC, ROW, st, "https://us-info.com/x", "2026-10-28")
    check("CL %s carries channel_label" % st, rec.get("channel_label") == LABEL, repr(rec.get("channel_label")))
    check("CL %s keeps in_scope/type/source_ref" % st, rec["in_scope"] is True and rec["deliverable_type"] == "citation" and rec["source_ref"] == "citation-transition:r1:%s" % st)
    held = T.build_activity_record(SCC, ROW, st, None, "2026-10-28", hold=True)
    check("CL %s held row still labelled" % st, held.get("channel_label") == LABEL and held["approved_at"] is None)

check("CL constant is exactly the shared contract value", T.ACTIVITY_CHANNEL_LABEL == "SEO & Local SEO")

# Upsert body: drive record_transition with fakes on a temp copy of the test queue.
SRC = os.path.join(HERE, "fixtures", "test_queue.json")
TMP = tempfile.mkdtemp()
class FakePortal:
    def __init__(self): self.calls = []
    def latest_snapshot(self, cid): return {"payload": {"directories": []}}
    def upsert_snapshot(self, cid, day, payload): self.calls.append(("SNAP", cid))
    def call(self, method, path, body=None, prefer=None): self.calls.append((method, path, body, prefer))
try:
    q = json.load(open(SRC, encoding="utf-8"))
    rows = [r for k, v in q.items() if isinstance(v, list) for r in v if isinstance(r, dict) and r.get("state") == "queued"]
    check("CL fixture has a queued row", bool(rows))
    if rows:
        qp = os.path.join(TMP, "q.json"); shutil.copy(SRC, qp)
        fp = FakePortal()
        r = T.record_transition("SCC", rows[0]["id"], "submitted", "https://example.com/x", queue_path=qp, today="2026-10-28", portal=fp, activities=fp, activities_flag="1", directories=None)
        posts = [c for c in fp.calls if c[0] == "POST" and "deliverables" in c[1]]
        check("CL upsert path is on_conflict=client_id,source_ref", posts and posts[0][1] == "deliverables?on_conflict=client_id,source_ref", str(posts[:1])[:120])
        check("CL upsert body carries the label", posts and posts[0][2][0].get("channel_label") == LABEL)
        check("CL upsert prefers merge-duplicates", posts and "merge-duplicates" in (posts[0][3] or ""))
        check("CL transition had no errors", r.get("errors") == [], str(r.get("errors")))
        check("CL Directory sink was off", os.environ.get("CE_DIRECTORIES_WRITE") == "0" and not any("ce_directory_status" in str(c) for c in fp.calls))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

bad = ok.count(False)
print("%d checks, %d failed" % (len(ok), bad))
sys.exit(1 if bad else 0)
