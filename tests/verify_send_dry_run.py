"""Dry run of the Cylex send step against a scripted fake page. No browser, no network, no SMS, no CapSolver. Prints the page actions in order.
Run: python tests/verify_send_dry_run.py"""
import io, os, sys, tempfile, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ["CE_VERIFY_DIRECTORIES"] = os.path.join(HERE, "verify_directories_fixture.json")
os.environ["CE_LOGS"] = os.path.join(TMP, "logs"); os.environ["CE_SITE_GUARD"] = os.path.join(TMP, "guard.json")
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json"); os.environ["CE_RUNS"] = tempfile.mkdtemp()
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "job"))
import verify_fakes as F
import verify_bridge as B
import verify_send as S

FAKE_CODE = "135790"
p = F.StrictPortal(requests=[F.request(status="starting")], verifications=[F.verification()], queued_code=FAKE_CODE)
page = F.FakePage(accepted=FAKE_CODE)
rt = F.FakeRuntime(page)
buf = io.StringIO()
with contextlib.redirect_stderr(buf):
    out = S.run(F.RID, p, B.VerifyRpc(p), rt, F.NOW)
print("DRY RUN (fake page, no live send)")
for a in page.actions:
    print("  page:", " ".join(str(x) for x in a if not (a[0] == "fill" and a[1].startswith("input[autocomplete"))) if a[0] != "fill" else "fill %s <value withheld>" % a[1])
print("  vault fills:", rt.vault_fills, "| browsers:", rt.browsers, "| sitegate reserves:", rt.reserves)
print("  rpc order:", [c[1].replace("rpc/", "") for c in p.calls if c[1].startswith("rpc/")])
print("  mark_code_sent mask:", [c[2]["p_sent_to_masked"] for c in p.calls if c[1] == "rpc/mark_code_sent"])
print("  outcome:", out, "| request:", p.requests[F.RID]["status"], "| verification:", p.verifications[F.VID]["state"])
print("  run log:", buf.getvalue().strip())
sys.exit(0 if out == "verified" and FAKE_CODE not in buf.getvalue() else 1)
