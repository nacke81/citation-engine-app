"""mail_scan --verify-link reads the Sortlist and Clutch verify mails (t_9a722352). Offline: relay-shaped fixtures from real 2026-11-13 mail, sanitized.
Run: python tests/verify_mail_agency_test.py (CI). Mutations at the end undo one fix and require the old failure."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job"))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
import mail_scan as M

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ((" [%s]" % (d,)) if d != "" else ""), flush=True)

def load(name):
    r = json.load(open(os.path.join(HERE, "fixtures", "verify-mail", name), encoding="utf-8"))
    return {"uid": r["id"], "folder": "INBOX", "from": r["from"], "subject": r["subject"], "date": r["received"][:16], "to": r["to"],
            "body": "\n".join(["code: %s" % c for c in r["codes"]] + r["links"])}
SORT, CLUTCH = load("sortlist-verify.relay.json"), load("clutch-verify.relay.json")
ADMIN = dict(SORT, uid="fx-sortlist-2", subject="You have been added as admin of Acme Agency", date="2026-11-13T22:25", body="https://sortli.st/t56jzn?utm_source=sendgrid.com")

h = M.find_verify("sortlist.com", [SORT, CLUTCH])
check("1 Sortlist: the verify link is the sortli.st button, not a tracker or footer link", h and h["url"].startswith("https://sortli.st/g42azd"), h)
check("1 Sortlist: unsubscribe-group (/asm/) and /contact links are never chosen", not any("/asm/" in u or "/contact" in u for u in M.verify_urls(SORT["body"], "sortlist.com")))
h = M.find_verify("clutch.co", [SORT, CLUTCH])
check("2 Clutch: code 652556 and the HubSpot link are both found", h and h["code"] == "652556" and "hubspotlinks.com" in (h["url"] or ""), h)
check("2 Clutch: the HubSpot link ranks first (the verify button), the placeholder 000000 is not the code", h and h["code"] != "000000")
check("3 a later non-verify Sortlist mail (admin added) does not hide the verify mail", (M.find_verify("sortlist.com", [SORT, ADMIN]) or {}).get("uid") == "fx-sortlist-1")
out = []
rc = M.verify_main(["sortlist.com", "clutch.co"], 30, messages=[SORT, CLUTCH, ADMIN], out=out.append)
check("4 verify_main prints both, exit 0", rc == 0 and "sortli.st/g42azd" in out[0] and "652556" in out[1], out)
check("5 aliases are per Directory: a sortli.st link in Clutch-matched mail is not taken", M.verify_urls("https://sortli.st/zzz", "clutch.co") == [])
check("5 a sortli.st link in a mail NOT from Sortlist is not matched to Sortlist", M.find_verify("sortlist.com", [dict(SORT, **{"from": "Other <x@other-agency.example>", "body": "https://sortli.st/zzz"})]) is None)
check("5 the older same-domain behaviour holds: own-domain verify path still found", M.verify_urls("https://www.cylex.us.com/verify?t=abc", "cylex.us.com") == ["https://www.cylex.us.com/verify?t=abc"])

# ---- mutation: no alias hosts -> Sortlist falls back to the wrong (tracker) link and Clutch loses its link
saved = dict(M.VERIFY_LINK_HOSTS); M.VERIFY_LINK_HOSTS.clear()
hs, hc = M.find_verify("sortlist.com", [SORT]), M.find_verify("clutch.co", [CLUTCH])
check("M1 mutation (no alias hosts): Sortlist is no longer the sortli.st link, Clutch has no link (the old bug returns)", not (hs and "sortli.st" in (hs["url"] or "")) and not (hc and hc["url"]))
M.VERIFY_LINK_HOSTS.update(saved)
print("%d checks, %d failed" % (len(ok), ok.count(False)))
sys.exit(1 if False in ok else 0)
