"""twilio/deploy.py tests (t_282b646e). A fake Serverless API built from the repo's own files; no network, no credentials.
Covers: the dry run reports 0 diff when the repo equals live; one changed byte / a missing file / an extra file / a changed manifest is a diff (exit 1);
numbers are masked in a printed diff; unreadable live = exit 2; --export writes only local files; the script has no write verb toward Twilio; the repo
sources keep FORWARD_TO and the Sync service id as Service env vars. Run: python tests/twilio_functions_test.py   exit 1 on any failure."""
import json, os, re, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "twilio"))
import deploy as D

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ((" [%s]" % (d,)) if d != "" else ""), flush=True)

REPO = D.read_repo()
check("the repo holds the 5 live Functions + manifest", sorted(REPO) == ["after-dial.js", "manifest.json", "sms.js", "vm-done.js", "voice.js", "voicemail.js"], sorted(REPO))
MAN = json.loads(REPO["manifest.json"])
SVC, ENV, BUILD = "ZSfake", "ZEfake", "ZBfake"


def fake_get(files, manifest, build_sid=BUILD, envs=None):
    """A Serverless API that serves `files` ({name: bytes}) and `manifest`. Records every URL it was asked (GET only by construction)."""
    urls = []
    fvs = [{"path": f["path"], "visibility": f["visibility"], "sid": "ZN" + str(i), "function_sid": "ZH" + str(i)} for i, f in enumerate(manifest["functions"])]
    def get(url):
        urls.append(url)
        if url == D.BASE + "/Services": return {"services": [{"sid": SVC, "unique_name": "nm-public-line"}, {"sid": "ZSother", "unique_name": "other"}]}
        if url.endswith("/Environments"): return {"environments": envs if envs is not None else [{"unique_name": "production", "build_sid": build_sid}]}
        if url.endswith("/Builds/" + BUILD):
            return {"runtime": manifest["runtime"], "dependencies": manifest["dependencies"], "function_versions": fvs}
        m = re.search(r"/Versions/(ZN\d+)/Content$", url)
        if m:
            fv = [f for f in fvs if f["sid"] == m.group(1)][0]
            return {"content": files[D.fname(fv["path"])].decode("utf-8")}
        raise AssertionError("unexpected GET " + url)
    get.urls = urls
    return get

LIVE = {k: v for k, v in REPO.items() if k != "manifest.json"}
out = []
rc = D.main([], get=fake_get(LIVE, MAN), out=out.append)
check("dry run (default) against a live build equal to the repo: rc 0, '0 diff'", rc == 0 and "0 diff" in out[0] and "5 Functions" in out[0], out)
rc = D.main(["--dry-run"], get=fake_get(LIVE, MAN), out=out.append)
check("--dry-run is the same as the default", rc == 0)
g = fake_get(LIVE, MAN); D.main([], get=g, out=out.append)
check("only the production environment's live build is read (never another build)", any(u.endswith("/Builds/" + BUILD) for u in g.urls) and all("/Builds" not in u or u.endswith(BUILD) for u in g.urls), g.urls)

# one changed byte
tweak = dict(LIVE); tweak["voice.js"] = LIVE["voice.js"].replace(b"maxLength: 180", b"maxLength: 181")
assert tweak["voice.js"] != LIVE["voice.js"]
out = []; rc = D.main([], get=fake_get(tweak, MAN), out=out.append)
check("one changed byte in live voice.js: rc 1, names the file and shows the line", rc == 1 and any(l.startswith("DIFFERS: voice.js") for l in out) and any("maxLength: 18" in l for l in out), out[:4])
# CRLF vs LF is a diff (byte for byte)
crlf = dict(LIVE); crlf["sms.js"] = LIVE["sms.js"].replace(b"\n", b"\r\n")
out = []; rc = D.main([], get=fake_get(crlf, MAN), out=out.append)
check("line-ending differences count as a diff (byte for byte)", rc == 1 and any(l.startswith("DIFFERS: sms.js") for l in out), out[:3])
# a new live Function not in the repo, and a repo file not live
more = dict(LIVE); more["extra.js"] = b"exports.handler = () => {};\n"
man2 = json.loads(json.dumps(MAN)); man2["functions"].append({"path": "/extra", "visibility": "protected"})
out = []; rc = D.main([], get=fake_get(more, man2), out=out.append)
check("a live Function missing from the repo is reported", rc == 1 and "MISSING in repo: extra.js" in out and any(l.startswith("DIFFERS: manifest.json") for l in out), out[:4])
fewer = {k: v for k, v in LIVE.items() if k != "vm-done.js"}
man3 = json.loads(json.dumps(MAN)); man3["functions"] = [f for f in man3["functions"] if f["path"] != "/vm-done"]
out = []; rc = D.main([], get=fake_get(fewer, man3), out=out.append)
check("a repo file that is not live is reported as EXTRA", rc == 1 and "EXTRA in repo (not live): vm-done.js" in out, out[:4])
man4 = json.loads(json.dumps(MAN)); man4["functions"][0]["visibility"] = "public"
out = []; rc = D.main([], get=fake_get(LIVE, man4), out=out.append)
check("a visibility change in live shows in the manifest diff", rc == 1 and any(l.startswith("DIFFERS: manifest.json") for l in out), out[:3])
man5 = json.loads(json.dumps(MAN)); man5["dependencies"][0]["version"] = "9.9.9"
out = []; rc = D.main([], get=fake_get(LIVE, man5), out=out.append)
check("a dependency version change in live shows in the manifest diff", rc == 1, out[:3])

# numbers are masked when a diff prints them
numfile = dict(LIVE); numfile["voice.js"] = b"// line (555) 010-0199 and +15550100199 here\n"
out = []; rc = D.main([], get=fake_get(numfile, MAN), out=out.append)
txt = "\n".join(out)
check("a printed diff masks phone numbers", rc == 1 and "<number>" in txt and "0100199" not in txt and "010-0199" not in txt, txt[:300])

# unreadable live
def dead(url): raise OSError("secret-token-leak")
out = []; rc = D.main([], get=dead, out=out.append)
check("live unreadable: rc 2, type only, no exception text", rc == 2 and "OSError" in out[0] and "secret-token-leak" not in out[0], out)
out = []; rc = D.main([], get=fake_get(LIVE, MAN, envs=[]), out=out.append)
check("no production environment: rc 2", rc == 2, out)
out = []; rc = D.main([], get=fake_get(LIVE, MAN, build_sid=None), out=out.append)
check("production environment without a live build: rc 2", rc == 2, out)

# export writes only local files, round-trips to a 0 diff
with tempfile.TemporaryDirectory() as d:
    g = fake_get(LIVE, MAN); out = []
    rc = D.main(["--export"], get=g, src_dir=d, out=out.append)
    check("--export writes the live files + manifest into the target dir", rc == 0 and sorted(os.listdir(d)) == sorted(REPO), os.listdir(d))
    check("--export is byte for byte (no newline rewrite)", all(open(os.path.join(d, n), "rb").read() == REPO[n] for n in REPO))
    out = []; rc = D.main([], get=fake_get(LIVE, MAN), src_dir=d, out=out.append)
    check("export then dry run: 0 diff", rc == 0, out)
    check("--export asked Twilio only for GETs of the Serverless API", all(u.startswith(D.BASE + "/Services") for u in g.urls))
    os.remove(os.path.join(d, "voice.js"))
    out = []; rc = D.main([], get=fake_get(LIVE, MAN), src_dir=d, out=out.append)
    check("a deleted repo file shows as MISSING", rc == 1 and "MISSING in repo: voice.js" in out, out)
try:
    D.main(["--deploy"], get=fake_get(LIVE, MAN), out=out.append); has_deploy = True
except SystemExit:
    has_deploy = False
check("there is no deploy mode", has_deploy is False)

# source scans
dsrc = open(os.path.join(ROOT, "twilio", "deploy.py"), encoding="utf8").read()
check("deploy.py has no write verb toward Twilio (GET only)", 'method="GET"' in dsrc and not re.search(r'method\s*=\s*"(POST|PUT|DELETE|PATCH)"', dsrc) and "data=" not in dsrc)
check("deploy.py only talks to serverless.twilio.com", re.findall(r"https://[a-z.]+", dsrc) == ["https://serverless.twilio.com"], re.findall(r"https://[a-z.]+", dsrc))
vs = REPO["voice.js"].decode("utf-8")
check("voice.js reads FORWARD_TO and the Sync service id from the Service environment, no literal", "context.FORWARD_TO" in vs and "context.ARM_SYNC_SID" in vs and not re.search(r"\bIS[0-9a-f]{32}\b", vs) and "+1" not in vs.replace("// ", "//"))
check("voice.js carries the armed branch (document verify_armed, 15 minute cap)", "verify_armed" in vs and "MAX_ARM_MS = 15 * 60 * 1000" in vs)
allsrc = "\n".join(v.decode("utf-8") for k, v in REPO.items() if k.endswith(".js"))
check("no E.164 number and no account/auth literal in any Function source", not re.search(r"\+\d{10,15}", allsrc) and not re.search(r"\bAC[0-9a-f]{32}\b", allsrc) and "auth_token" not in allsrc.lower())
ga = open(os.path.join(ROOT, ".gitattributes"), encoding="utf8").read()
check(".gitattributes keeps twilio/** bytes (-text)", "twilio/** -text" in ga)

print("twilio_functions_test: %d checks, %d failed" % (len(ok), ok.count(False)))
sys.exit(0 if all(ok) else 1)
