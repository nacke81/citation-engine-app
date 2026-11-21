"""t_25000cbd: every citation_engine write to the portal `deliverables` table goes through job/portal.py (deliverable_row / write_deliverables),
which always sets approved_at and source=citation_engine. The portal hides a citation_engine row with approved_at NULL, so a path that skips the
helper would silently never reach the client feed. Run: python tests/deliverables_helper_test.py (CI). Pure stdlib, no network.

H*  helper behaviour (run against the real module, then against a mutant that drops approved_at: must FAIL)
G*  guard: no file under job/, db/, site/, nm/, root scripts names the table as a write target outside portal.py (run on the real tree, then on a planted tree: must FAIL)
"""
import ast, os, re, sys, types, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.environ["CE_PORTAL_ENV"] = os.path.join(HERE, "no-such-portal.env")   # t_2ddc7067: fail closed, never the prod portal
sys.path.insert(0, os.path.join(ROOT, "job"))
import portal as P  # noqa: E402

ok = []
def check(name, cond, detail=""):
    ok.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


class Fake:
    def __init__(self): self.calls = []
    def call(self, method, path, body=None, prefer=None): self.calls.append((method, path, body, prefer))


def helper_problems(mod):
    """-> list of what is wrong with a portal module's deliverables helper (empty = fine)."""
    bad = []
    SCC = mod.ALLOWED["SCC"]
    for given in ({}, {"approved_at": None}, {"approved_at": "1999-01-01T00:00:00Z", "source": "someone_else"}):
        r = mod.deliverable_row(dict(client_id=SCC, title="t", source_ref="x", **given), now="2026-11-18T12:00:00Z")
        if r.get("approved_at") != "2026-11-18T12:00:00Z": bad.append("approved_at not forced to created time for %r: %r" % (given, r.get("approved_at")))
        if r.get("source") != "citation_engine": bad.append("source not citation_engine for %r: %r" % (given, r.get("source")))
    r = mod.deliverable_row(dict(client_id=SCC))
    if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", str(r.get("approved_at"))): bad.append("default approved_at is not an ISO UTC time: %r" % (r.get("approved_at"),))
    f = Fake()
    mod.write_deliverables(f, [dict(client_id=SCC, title="a", approved_at=None), dict(client_id=SCC, title="b")])
    if len(f.calls) != 1 or f.calls[0][0] != "POST" or not f.calls[0][1].startswith("deliverables?"): bad.append("write_deliverables did not make one POST to deliverables: %r" % (f.calls,))
    elif not all(x.get("approved_at") and x.get("source") == "citation_engine" for x in f.calls[0][2]): bad.append("a written row lacked approved_at/source")
    f2 = Fake()
    try: mod.write_deliverables(f2, [dict(client_id="not-allowed")]); bad.append("non-allow-listed client was written")
    except mod.PortalWriteError: pass
    if f2.calls: bad.append("a call was made before the client check")
    return bad


# ---- guard ----------------------------------------------------------------------------------------------------------------------------
TABLE = re.compile(r"(?is)(^\s*deliverables\s*($|\?)|/deliverables\b|\b(insert\s+into|update|upsert\s+into|delete\s+from)\s+(public\.)?deliverables\b|\.from\(\s*['\"]deliverables['\"])")
SKIP_DIRS = {".git", "node_modules", "vendor", "tests", "plans", "docs", "__pycache__", ".worktrees", ".github"}
ALLOWED_FILES = {os.path.join("job", "portal.py")}   # the helper's home; nothing else


def guard_hits(root):
    """-> [(relpath, line, text)] for every non-test file that names `deliverables` as a table target outside the helper's file."""
    hits = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for fn in files:
            p = os.path.join(d, fn); rel = os.path.relpath(p, root)
            if rel in ALLOWED_FILES or os.path.splitext(fn)[1].lower() in (".png", ".jpg", ".ico", ".woff", ".woff2", ".gz", ".zip", ".pyc"): continue
            try: txt = open(p, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError): continue
            if fn.endswith(".py"):   # python: string constants only (docstrings that merely say the word "deliverables" are prose, not a write)
                try: tree = ast.parse(txt)
                except SyntaxError: hits.append((rel, 0, "unparseable python")); continue
                for n in ast.walk(tree):
                    if isinstance(n, ast.Constant) and isinstance(n.value, str) and TABLE.search(n.value): hits.append((rel, n.lineno, n.value[:80]))
                    if (isinstance(n, ast.Name) and n.id == "DELIVERABLES_PATH") or (isinstance(n, ast.Attribute) and n.attr == "DELIVERABLES_PATH"):
                        hits.append((rel, n.lineno, "references DELIVERABLES_PATH outside portal.py"))   # t_25000cbd review: the constant makes the table-name string unnecessary
            else:
                for i, line in enumerate(txt.splitlines(), 1):
                    if TABLE.search(line): hits.append((rel, i, line.strip()[:80]))
    return hits


# H: real module passes; mutant that drops approved_at fails
check("H1 real helper has no problems", helper_problems(P) == [], str(helper_problems(P)))
src = open(os.path.join(ROOT, "job", "portal.py"), encoding="utf-8").read()
assert 'row["approved_at"] = ' in src
for label, old, new in (("approved_at line dropped", 'row["approved_at"] = now or', 'row.pop("approved_at", None); _ = now or'),
                        ("source dropped", 'row["source"] = SOURCE', 'pass'),
                        ("caller approved_at kept", 'row["approved_at"] = now or', 'row.setdefault("approved_at", None) if True else now or')):
    m = types.ModuleType("portal_mut"); exec(compile(src.replace(old, new, 1), "portal_mut.py", "exec"), m.__dict__)
    probs = helper_problems(m)
    check("H2 mutation (%s) is caught" % label, len(probs) > 0, probs[0][:70] if probs else "not caught")

# G: the tree is clean; a planted writer is caught (python module, SQL file, JS)
hits = guard_hits(ROOT)
check("G1 no module outside job/portal.py writes deliverables", hits == [], str(hits[:5]))
check("G1b scan really walked job/ (sanity: sees transitions.py)", any(f == "transitions.py" for f in os.listdir(os.path.join(ROOT, "job"))) and os.path.isdir(os.path.join(ROOT, "job")))
check("G1c transitions.py reaches the table only through the helper", "P.write_deliverables(" in open(os.path.join(ROOT, "job", "transitions.py"), encoding="utf-8").read())
tmp = tempfile.mkdtemp(prefix="deliv-guard-")
try:
    os.makedirs(os.path.join(tmp, "job")); os.makedirs(os.path.join(tmp, "db"))
    shutil.copy(os.path.join(ROOT, "job", "portal.py"), os.path.join(tmp, "job", "portal.py"))
    check("G2 clean temp tree passes", guard_hits(tmp) == [])
    for name, rel, body in (("python POST", "job/backfill_x.py", 'db.call("POST", "deliverables?on_conflict=client_id,source_ref", rows)\n'),
                            ("python rest url", "job/retry_x.py", 'URL = base + "/rest/v1/deliverables"\n'),
                            ("sql insert", "db/008_x.sql", "insert into public.deliverables (client_id) values ('x');\n"),
                            ("planted M1 via P.DELIVERABLES_PATH", "job/backfill_y.py", 'import portal as P\nportal.call("POST", P.DELIVERABLES_PATH, [dict(r, approved_at=None) for r in rows])\n'),
                            ("bare DELIVERABLES_PATH import", "job/backfill_z.py", 'from portal import DELIVERABLES_PATH\nx = DELIVERABLES_PATH\n'),
                            ("js supabase", "job/x.mjs", "await sb.from('deliverables').upsert(rows)\n")):
        p = os.path.join(tmp, *rel.split("/")); open(p, "w", encoding="utf-8").write(body)
        got = guard_hits(tmp)
        check("G3 planted %s writer is caught" % name, any(h[0] == os.path.normpath(rel) for h in got), str(got))
        os.remove(p)
    p = os.path.join(tmp, "job", "prose.py"); open(p, "w", encoding="utf-8").write('"""Writes one client-voiced deliverables row via the helper."""\n')
    check("G4 prose mention of the word is not a write", guard_hits(tmp) == [])
finally:
    shutil.rmtree(tmp, ignore_errors=True)


# T: transport invariant in Portal.call (the one choke point), via the injectable opener
import json as _json  # noqa: E402


def transport_problems(mod):
    """-> list of what is wrong with Portal.call's deliverables guard (empty = fine)."""
    bad = []; SCC = mod.ALLOWED["SCC"]
    def mk():
        seen = []
        class R:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def read(s): return b""
        def op(req): seen.append(req); return R()
        return mod.Portal("http://x.invalid", "k", opener=op), seen
    for given in ({"approved_at": None}, {}, {"approved_at": "", "source": "other"}):
        p, seen = mk()
        p.call("POST", mod.DELIVERABLES_PATH, [dict(client_id=SCC, title="t", source_ref="r", **given)], prefer="resolution=merge-duplicates")
        rows = _json.loads(seen[0].data) if seen else []
        if len(seen) != 1 or not rows or not all(r.get("approved_at") and r.get("source") == "citation_engine" for r in rows): bad.append("raw POST body not stamped for %r: %r" % (given, rows))
    for m, path, body in (("PATCH", "deliverables?source=eq.citation_engine", {"approved_at": None}), ("DELETE", "deliverables?client_id=eq.x", None),
                          ("POST", "deliverables?on_conflict=id", [dict(client_id=SCC)]), ("POST", "/deliverables", [dict(client_id=SCC)]), ("POST", "Deliverables?on_conflict=client_id,source_ref", [dict(client_id=SCC)])):
        p, seen = mk()
        try: p.call(m, path, body); bad.append("%s %s was not refused" % (m, path))
        except mod.PortalWriteError: pass
        if seen: bad.append("%s %s reached the opener" % (m, path))
    p, seen = mk()
    try: p.call("POST", mod.DELIVERABLES_PATH, [dict(client_id="not-allowed")]); bad.append("non-allow-listed client written")
    except mod.PortalWriteError: pass
    if seen: bad.append("bad client reached the opener")
    p, seen = mk(); p.call("GET", "deliverables?select=id&limit=1")
    if len(seen) != 1: bad.append("GET on deliverables was blocked")
    p, seen = mk(); p.call("POST", "footprint_snapshot?on_conflict=client_id,source,captured_day", [{"client_id": SCC}])
    if len(seen) != 1 or "approved_at" in _json.loads(seen[0].data)[0]: bad.append("other tables were touched by the guard")
    return bad


check("T1 real Portal.call guard has no problems", transport_problems(P) == [], str(transport_problems(P)))
check("T1b an existing stamp on a row is kept, a None is replaced", P.deliverable_row({"approved_at": "2026-01-02T03:04:05Z"})["approved_at"] == "2026-01-02T03:04:05Z" and P.deliverable_row({"approved_at": None})["approved_at"])
check("T1c dry-run request goes through the portal helper", all(x.get("approved_at") for x in P.deliverables_request([dict(client_id=P.ALLOWED["SCC"], approved_at=None)])["body"]))
for label, old, new in (("guard call removed from Portal.call", "        body = guard_deliverables(method, path, body)", "        pass"),
                        ("guard passes PATCH through", 'if str(method).upper() != "POST" or path != DELIVERABLES_PATH:', "if False:"),
                        ("guard stops stamping rows", "out = uniform_rows([deliverable_row(r) for r in body])\n    for r in out: check_client(r.get(\"client_id\"))\n    return out", "return body")):
    assert src.count(old) == 1 or label.startswith("guard stops"), label
    m = types.ModuleType("portal_mut2")
    mutated = src.replace(old, new, 1) if old in src else src.replace(old.replace("\n", "\r\n"), new.replace("\n", "\r\n"), 1)
    assert mutated != src, label
    exec(compile(mutated, "portal_mut2.py", "exec"), m.__dict__)
    probs = transport_problems(m)
    check("T2 mutation (%s) is caught" % label, len(probs) > 0, probs[0][:70] if probs else "not caught")

# ---- t_e9ea1429: uniform keys + readable portal HTTP errors ----
import io, json, urllib.error
NMC = P.ALLOWED["NM"]
MIXED = [dict(client_id=NMC, title="a", source_ref="r1", evidence_url="https://x.example/1"), dict(client_id=NMC, title="b", source_ref="r2")]

def uniform_problems(mod):
    bad = []
    f = Fake(); mod.write_deliverables(f, MIXED)
    if len({tuple(sorted(r)) for r in f.calls[0][2]}) != 1: bad.append("write_deliverables batch keys differ")
    if f.calls[0][2][1].get("evidence_url", "missing") is not None: bad.append("missing key is not null")
    if len({tuple(sorted(r)) for r in mod.deliverables_request(MIXED)["body"]}) != 1: bad.append("deliverables_request keys differ")
    if len({tuple(sorted(r)) for r in mod.guard_deliverables("POST", mod.DELIVERABLES_PATH, MIXED)}) != 1: bad.append("guard keys differ")
    return bad

check("U1 mixed batch (one with evidence_url, one without) has uniform keys in all three paths", uniform_problems(P) == [], str(uniform_problems(P)))
for label, old, new in (("write_deliverables skips uniform_rows", "out = uniform_rows([deliverable_row(r, now) for r in rows])", "out = [deliverable_row(r, now) for r in rows]"),
                        ("dry run skips uniform_rows", '"body": uniform_rows([deliverable_row(r, now) for r in rows])}', '"body": [deliverable_row(r, now) for r in rows]}'),
                        ("guard skips uniform_rows", "out = uniform_rows([deliverable_row(r) for r in body])", "out = [deliverable_row(r) for r in body]"),
                        ("uniform_rows is a no-op", "return [{k: r.get(k) for k in keys} for r in rows]", "return rows")):
    msrc = src.replace("\r\n", "\n")
    assert msrc.count(old) == 1, label
    m = types.ModuleType("portal_mut3"); exec(compile(msrc.replace(old, new, 1), "portal_mut3.py", "exec"), m.__dict__)
    probs = uniform_problems(m)
    check("U2 mutation (%s) is caught" % label, len(probs) > 0, probs[0][:70] if probs else "not caught")

def http_error(code, body):
    return urllib.error.HTTPError("https://portal.example/rest/v1/deliverables", code, "Bad Request", {}, io.BytesIO(body))
def err_text(body, code=400):
    def opener(req): raise http_error(code, body)
    try: P.Portal("https://portal.example", "SECRETKEY123", opener=opener).call("POST", P.DELIVERABLES_PATH, [dict(client_id=NMC, title="REQBODYMARK")])
    except P.PortalWriteError as e: return str(e)
    return ""
pg = json.dumps({"code": "PGRST102", "message": "All object keys must match", "details": "DETAILSMARK", "hint": "HINTMARK SECRETKEY123"}).encode()
t = err_text(pg)
check("E1 a PGRST102 400 shows the code and message", "PGRST102" in t and "All object keys must match" in t and "HTTP Error 400" in t, t[:160])
check("E2 only code+message: no details/hint/request body/key/headers", not any(x in t for x in ("DETAILSMARK", "HINTMARK", "REQBODYMARK", "SECRETKEY123", "Bearer", "apikey")), t[:160])
t2 = err_text(json.dumps({"code": "X" * 100, "message": "M" * 1000}).encode())
check("E3 code and message are capped", "X" * 40 in t2 and "X" * 41 not in t2 and "M" * 200 in t2 and "M" * 201 not in t2, str(len(t2)))
t3 = err_text(b"<html>not json SECRETKEY123</html>", 502)
check("E4 a non-JSON body adds nothing and leaks nothing", "502" in t3 and "not json" not in t3 and "SECRETKEY123" not in t3, t3[:120])

print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})")
sys.exit(0 if all(ok) else 1)
