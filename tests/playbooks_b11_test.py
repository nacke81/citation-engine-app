"""manta / citysquares / openstreetmap playbook tests (t_1c503c7f). No network, no browser, no real mailbox: fake page, fake mailbox, fake http, fake clock."""
import os, sys, io, contextlib, re, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job", "playbooks"))
import manta as M
import citysquares as CS
import openstreetmap as O
import hotfrog as H

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)
def raises(fn, *a, **k):
    try: fn(*a, **k); return None
    except BaseException as e: return e

class Loc:
    def __init__(s, page, label): s.page, s.label = page, label
    def count(s): return 0 if s.label in s.page.missing else 1
    @property
    def first(s): return s
    def fill(s, v): s.page.log.append(("fill", s.label, v))
    def click(s): s.page.log.append(("click", s.label))
class Page:
    def __init__(s, body="Welcome", missing=(), walled_for=0):
        s.log, s.missing, s.body, s.walled_for, s.reads = [], set(missing), body, walled_for, 0
    def goto(s, u, wait_until=None): s.log.append(("goto", u))
    def wait_for_timeout(s, ms): s.log.append(("wait", ms))
    def inner_text(s, sel):
        s.reads += 1
        return "Just a moment..." if s.reads <= s.walled_for else s.body
    def get_by_label(s, label, exact=False): return Loc(s, label)
    def get_by_role(s, role, name=None): return Loc(s, "role:" + role)
    def evaluate(s, js): return True
    def frame_locator(s, q): return s
    def locator(s, q): return s   # no reCAPTCHA widget on the fake page
    def count(s): return 0
class MB:
    def __init__(s, found=("7", "https://www.manta.com/verify?t=abc")): s.found, s.polls = found, 0
    def max_uid(s): return 5
    def newest_verify_link(s, since_uid=0): s.polls += 1; return s.found

NAP = dict(name="Alder Care Consulting & Solutions", street="100 Example", city="Exampleton", zip_code="40000", phone="(502) 555-0101", website="alder.example")

# ---- manta
check("M1 dry run lists the steps, refuses nothing", M.main(["--dry-run"]) == 0)
check("M2 --live refused here", isinstance(raises(M.main, ["--live"]), SystemExit))
p = Page(); r = M.run(p, MB(), email_addr="listings@x.example", get_password=lambda: "pw-not-printed", **NAP)
check("M3 full run steps in order", r["steps"] == ["open_home", "wait_cloudflare", "sign_up", "read_verify_mail", "open_verify_link", "add_company", "recaptcha"], str(r["steps"]))
check("M4 website typed with https:// once", ("fill", "Website", "https://alder.example") in p.log)
check("M5 verify link opened", ("goto", "https://www.manta.com/verify?t=abc") in p.log)
check("M6 password never in the result", "pw-not-printed" not in json.dumps(r))
p = Page(walled_for=3); r = M.run(p, MB(), email_addr="a@x.example", get_password=lambda: "pw", **NAP)
check("M7 a Cloudflare check that clears by itself is waited out", "wait_cloudflare" in r["steps"] and ("wait", 2000) in p.log)
e = raises(M.run, Page(walled_for=10 ** 6), MB(), email_addr="a@x.example", get_password=lambda: "pw", **NAP)
check("M8 check that never clears -> WALL:cloudflare-click, no solver", isinstance(e, M.PlaybookError) and "WALL:cloudflare-click" in str(e), str(e))
e = raises(M.run, Page(missing={"Business name"}), MB(), email_addr="a@x.example", get_password=lambda: "pw", **NAP)
check("M9 missing form label stops with 'form changed'", isinstance(e, M.PlaybookError) and "form changed" in str(e), str(e))
t = [0]; clock = lambda: t[0]
def slp(s): t[0] += s
mb = MB(found=None)
e = raises(M.run, Page(), mb, email_addr="a@x.example", get_password=lambda: "pw", poll_seconds=30, poll_every=10, sleep=slp, now=clock, **NAP)
check("M10 no mail in time -> clear error mentioning Resend", isinstance(e, M.PlaybookError) and "Resend" in str(e) and mb.polls >= 3, str(e))
e = raises(M.run, Page(), MB(), email_addr="a@x.example", get_password=None, **NAP)
check("M11 password callable required", isinstance(e, M.PlaybookError))
e = raises(M.run, Page(), MB(), email_addr="a@x.example", get_password=lambda: "x" * 200, **NAP)
check("M12 over-long password refused before any click", isinstance(e, M.PlaybookError))
e = raises(M.run, Page(), MB(), email_addr="a@x.example", get_password=lambda: "pw", **dict(NAP, phone=""))
check("M13 empty NAP value refused (never defaulted)", isinstance(e, M.PlaybookError) and "phone" in str(e))
MAIL = b"From: Manta <noreply@manta.com>\r\nSubject: Verify\r\nContent-Type: text/html\r\n\r\n<a href=\"https://www.manta.com/verify-email?token=ab12&amp;u=9\">Verify</a>"
check("M14 verify link extracted, &amp; decoded", M.extract_verify_link(MAIL) == "https://www.manta.com/verify-email?token=ab12&u=9", str(M.extract_verify_link(MAIL)))
check("M15 lookalike domain not matched", M.extract_verify_link(b"From: a@b.c\r\nContent-Type: text/plain\r\n\r\nhttps://www.manta.com.evil.example/verify?x=1") is None)
check("M16 hotfrog pattern restored after use", H.VERIFY_RE.pattern.startswith("https://www\\.hotfrog"))
check("M17 public URL shape", M.PUBLIC_RE.match("https://www.manta.com/c/m0example/alder-care-consulting-solutions") and not M.PUBLIC_RE.match("https://www.manta.com/search?x=1"))
pub = M.check_public_page(Page(body="Alder Care Consulting & Solutions\nClaimed\n(502) 555-0101"), "https://www.manta.com/c/m0example/alder", phone_digits="5025550101", name="Alder Care Consulting & Solutions")
check("M18 public page check: claimed + phone + name", pub == {"claimed": True, "phone": True, "name": True}, str(pub))
check("M19 non-listing URL refused", isinstance(raises(M.check_public_page, Page(), "https://www.manta.com/search?q=x", phone_digits="1", name="x"), M.PlaybookError))
src = open(str(M.__file__), encoding="utf-8").read()
check("M20 manta has no import of the CapSolver client or a proxy setting", not re.search(r"^\s*(import|from)\s+\w*(capsolver|proxy)", src, re.I | re.M) and "proxy=" not in src)
check("M21 recaptcha_click returns None when no widget", M.recaptcha_click(type("P", (), {"frame_locator": lambda s, q: type("F", (), {"locator": lambda s2, q2: type("L", (), {"count": lambda s3: 0})()})()})()) is None)

# ---- citysquares
URL = "https://citysquares.com/b/alder-care-consulting-solutions-10000001"
check("C1 dry run ok, --live refused", CS.main(["--dry-run"]) == 0 and isinstance(raises(CS.main, ["--live"]), SystemExit))
p = Page(); r = CS.run(p, url=URL, email_addr="a@x.example", get_password=lambda: "pw")
check("C2 claim steps in order", r["steps"] == ["open_listing", "wait_cloudflare", "claim", "account"], str(r["steps"]))
check("C3 opened the listing URL", p.log[0] == ("goto", URL))
for bad in ("https://citysquares.com/add_business", "https://citysquares.com.evil.example/b/x-1", "http://citysquares.com/b/x-1", "https://citysquares.com/search?q=x"):
    check("C4 only a listing URL is accepted: %s" % bad, isinstance(raises(CS.run, Page(), url=bad, email_addr="a@x", get_password=lambda: "pw"), CS.PlaybookError))
e = raises(CS.run, Page(walled_for=10 ** 6), url=URL, email_addr="a@x.example", get_password=lambda: "pw")
check("C5 stuck Cloudflare -> WALL:cloudflare-click", isinstance(e, CS.PlaybookError) and "WALL:cloudflare-click" in str(e))
e = raises(CS.run, Page(missing={"role:link", "role:button"}), url=URL, email_addr="a@x.example", get_password=lambda: "pw")
check("C6 no Claim control -> clear error", isinstance(e, CS.PlaybookError) and "Claim" in str(e), str(e))
e = raises(CS.run, Page(missing={"Password"}), url=URL, email_addr="a@x.example", get_password=lambda: "pw")
check("C7 missing field -> form changed", isinstance(e, CS.PlaybookError) and "form changed" in str(e))
check("C8 password never in the result", "pw" not in json.dumps(CS.run(Page(), url=URL, email_addr="a@x.example", get_password=lambda: "pw-secret")))
pub = CS.check_public_page(Page(body="Alder Care Consulting & Solutions\n100 Example\n(502) 555-0101"), URL, phone_digits="5025550101", name="Alder Care Consulting & Solutions", street="100 Example")
check("C9 public page check", pub == {"name": True, "street": True, "phone": True}, str(pub))

# ---- openstreetmap
OK = dict(lat=38.1234567, lng=-85.1234567, name="Alder Care Consulting & Solutions", housenumber="100", street="Example", city="Exampleton", state="KY", postcode="40000", phone="+1 502 555 0101", website="https://alder.example")
for k in ("lat", "lng"):
    for bad in (None, "", "  ", "abc", 0, "0", 91 if k == "lat" else 181, float("nan"), True):
        check("O1 %s=%r refused" % (k, bad), isinstance(raises(O.plan, **dict(OK, **{k: bad})), O.PlaybookError))
p = O.plan(**OK)
check("O2 node xml carries the exact pin", 'lat="38.1234567" lon="-85.1234567"' in p["node"], p["node"])
check("O3 tags are NAP only (9 keys, fixed order)", tuple(p["tags"]) == O.TAG_ORDER and len(p["tags"]) == 9)
check("O4 '&' escaped in xml", "Consulting &amp; Solutions" in p["node"] and "Consulting & Solutions" not in p["node"].replace("&amp;", ""))
check("O5 changeset comment survey/owner", 'v="survey/owner"' in p["changeset"])
for k in ("name", "housenumber", "street", "city", "state", "postcode", "phone", "website"):
    check("O6 empty %s refused" % k, isinstance(raises(O.plan, **dict(OK, **{k: " "})), O.PlaybookError))
check("O7 website needs https://", isinstance(raises(O.plan, **dict(OK, website="alder.example")), O.PlaybookError))
check("O8 phone must be +1 international", isinstance(raises(O.plan, **dict(OK, phone="(502) 555-0101")), O.PlaybookError))

calls = []
def http_ok(method, url, body, headers):
    calls.append((method, url, body, headers))
    if url.endswith("/changeset/create"): return 200, "991"
    if url.endswith("/node/create"): return 200, "5550001112"
    return 200, ""
r = O.run(http_ok, env={"OSM_ACCESS_TOKEN": "tok-secret"}, **OK)
check("O9 run: changeset -> node -> close, in order", [c[1].split("/api/0.6/")[1] for c in calls] == ["changeset/create", "node/create", "changeset/991/close"], str([c[1] for c in calls]))
check("O10 result url + ids", r["url"] == "https://www.openstreetmap.org/node/5550001112" and r["changeset"] == 991 and r["node_id"] == 5550001112)
check("O11 every request goes to api.openstreetmap.org only", all(c[1].startswith("https://api.openstreetmap.org/") for c in calls))
check("O12 token only in the Authorization header, not in result or bodies", "tok-secret" not in json.dumps(r) and not any("tok-secret" in (c[2] or "") for c in calls) and all(c[3]["Authorization"] == "Bearer tok-secret" for c in calls))
check("O13 node body has changeset id 991", 'changeset="991"' in calls[1][2])
calls.clear()
e = raises(O.run, http_ok, env={}, **OK)
check("O14 no token -> refused before any request", isinstance(e, O.PlaybookError) and not calls)
calls.clear()
e = raises(O.run, http_ok, env={"OSM_ACCESS_TOKEN": "t"}, **dict(OK, lat=None))
check("O15 missing lat -> refused before any request (never guessed)", isinstance(e, O.PlaybookError) and not calls)
calls.clear()
def http_node_fail(method, url, body, headers):
    calls.append(url)
    if url.endswith("/changeset/create"): return 200, "55"
    if url.endswith("/node/create"): return 400, "bad"
    return 200, ""
e = raises(O.run, http_node_fail, env={"OSM_ACCESS_TOKEN": "t"}, **OK)
check("O16 node failure still closes the changeset", isinstance(e, O.PlaybookError) and calls[-1].endswith("/changeset/55/close"), str(calls))
e = raises(O.run, lambda *a: (500, ""), env={"OSM_ACCESS_TOKEN": "t"}, **OK)
check("O17 changeset failure -> error", isinstance(e, O.PlaybookError))
tags = O.read_back(lambda m, u, b, h: (200, json.dumps({"elements": [{"tags": {"name": "x"}}]})), 5550001112)
check("O18 read_back returns tags", tags == {"name": "x"})
check("O19 no default coordinate in the source", not re.search(r"37\.3150934|87\.4966459", open(O.__file__, encoding="utf-8").read().split('"""', 2)[2]))
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = O.main(["--dry-run", "--lat", "38.1234567", "--lng", "-85.1234567", "--name", OK["name"], "--housenumber", "100", "--street", "Example", "--city", "Exampleton", "--state", "KY", "--postcode", "40000", "--phone", OK["phone"], "--website", OK["website"]])
check("O20 CLI dry-run prints the pin and node, exits 0, no token read", rc == 0 and "pin: 38.1234567" in buf.getvalue())
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = O.main(["--dry-run", "--name", "x"])
check("O21 CLI dry-run without a pin is REFUSED (exit 2)", rc == 2 and "REFUSED" in buf.getvalue())
check("O22 --live refused", isinstance(raises(O.main, ["--live"]), SystemExit))

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
