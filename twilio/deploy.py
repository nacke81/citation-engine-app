"""Twilio Functions: the repo copy of the NM public line, diffed against what is live (t_282b646e).

  python twilio/deploy.py                 # same as --dry-run: diff the repo against the live production build; exit 0 = no diff, 1 = diff, 2 = error
  python twilio/deploy.py --export        # write the LIVE sources into twilio/nm-public-line/ (a local write; one-time pull / re-sync after a console edit)

There is NO deploy mode here. This script only reads Twilio (Serverless API, GET). A Function change is a reviewable PR to twilio/nm-public-line/;
the deploy itself is a separate, human-gated step.

Layout: twilio/nm-public-line/<path>.js for every Function of the live build (path "/after-dial" -> after-dial.js) and manifest.json (path,
visibility, runtime, dependencies). Every number, FORWARD_TO and the Sync service id the Function reads are Service ENVIRONMENT VARIABLES, never in
these files; the dry run does not read or print them. Files are compared byte for byte (twilio/** is `-text` in .gitattributes: no CRLF rewrite).

Credentials: the same file the NM inbox cron and call_code.py read (CE_TWILIO_CREDENTIALS, default C:/Credentials/twilio-api.json). Never printed.
"""
import argparse, base64, difflib, json, os, re, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(HERE, "nm-public-line")
SERVICE_NAME = "nm-public-line"
ENV_NAME = "production"
CRED_PATH = os.environ.get("CE_TWILIO_CREDENTIALS", "C:/Credentials/twilio-api.json")
BASE = "https://serverless.twilio.com/v1"
NUM_RE = re.compile(r"\+\d{10,15}|\+?\(?\d{3}\)?[\s.\-]*\d{3}[\s.\-]*\d{4}")


class DeployError(Exception):
    pass


def make_get(cred_path=None):
    """-> get(url) -> parsed JSON. GET only, 30 s timeout, Basic auth from the creds file."""
    with open(cred_path or CRED_PATH, encoding="utf8") as f:
        c = json.load(f)
    sid = c.get("account_sid") or c.get("accountSid")
    tok = c.get("auth_token") or c.get("authToken")
    if not sid or not tok:
        raise DeployError("credential file incomplete")
    auth = "Basic " + base64.b64encode(("%s:%s" % (sid, tok)).encode()).decode()

    def get(url):
        req = urllib.request.Request(url, headers={"Authorization": auth}, method="GET")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    return get


def fname(path):
    return path.strip("/") + ".js"


def fetch_live(get):
    """-> (files {filename: bytes}, manifest dict) of the live production build."""
    svcs = [s for s in get(BASE + "/Services").get("services", []) if s.get("unique_name") == SERVICE_NAME]
    if len(svcs) != 1:
        raise DeployError("service %s not found exactly once" % SERVICE_NAME)
    ssid = svcs[0]["sid"]
    envs = [e for e in get("%s/Services/%s/Environments" % (BASE, ssid)).get("environments", []) if e.get("unique_name") == ENV_NAME]
    if len(envs) != 1 or not envs[0].get("build_sid"):
        raise DeployError("environment %s has no live build" % ENV_NAME)
    build = get("%s/Services/%s/Builds/%s" % (BASE, ssid, envs[0]["build_sid"]))
    files, fns = {}, []
    for fv in build.get("function_versions", []):
        d = get("%s/Services/%s/Functions/%s/Versions/%s/Content" % (BASE, ssid, fv["function_sid"], fv["sid"]))
        files[fname(fv["path"])] = d["content"].encode("utf-8")
        fns.append({"path": fv["path"], "visibility": fv["visibility"]})
    manifest = {"service": SERVICE_NAME, "environment": ENV_NAME, "runtime": build.get("runtime"),
                "dependencies": sorted(({"name": x["name"], "version": x["version"]} for x in build.get("dependencies", [])), key=lambda x: x["name"]),
                "functions": sorted(fns, key=lambda x: x["path"])}
    return files, manifest


def manifest_bytes(m):
    return (json.dumps(m, indent=2, sort_keys=True) + "\n").encode("utf-8")


def read_repo(src_dir=None):
    """-> {filename: bytes} of the repo copy (every file in the directory, manifest.json included)."""
    d = src_dir or SRC_DIR
    out = {}
    if os.path.isdir(d):
        for n in sorted(os.listdir(d)):
            p = os.path.join(d, n)
            if os.path.isfile(p):
                with open(p, "rb") as f:
                    out[n] = f.read()
    return out


def _mask(s):
    return NUM_RE.sub("<number>", s)


def diff(live_files, live_manifest, repo_files):
    """-> list of report lines; empty = the repo equals live byte for byte (manifest included). Numbers in a diff are masked."""
    want = dict(live_files); want["manifest.json"] = manifest_bytes(live_manifest)
    rep = []
    for n in sorted(set(want) | set(repo_files)):
        if n not in repo_files:
            rep.append("MISSING in repo: " + n)
        elif n not in want:
            rep.append("EXTRA in repo (not live): " + n)
        elif want[n] != repo_files[n]:
            rep.append("DIFFERS: %s (repo %d bytes, live %d bytes)" % (n, len(repo_files[n]), len(want[n])))
            a = repo_files[n].decode("utf-8", "replace").splitlines(True)
            b = want[n].decode("utf-8", "replace").splitlines(True)
            rep.extend(_mask(l.rstrip("\n")) for l in difflib.unified_diff(a, b, "repo/" + n, "live/" + n, n=1))
    return rep


def export(live_files, live_manifest, src_dir=None):
    d = src_dir or SRC_DIR
    os.makedirs(d, exist_ok=True)
    out = dict(live_files); out["manifest.json"] = manifest_bytes(live_manifest)
    for n, b in out.items():
        with open(os.path.join(d, n), "wb") as f:
            f.write(b)
    return sorted(out)


def main(argv=None, get=None, src_dir=None, out=print):
    ap = argparse.ArgumentParser(description="Diff the repo's nm-public-line Functions against the live build (read-only).")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="the default: diff repo vs live, change nothing")
    g.add_argument("--export", action="store_true", help="write the live sources into twilio/nm-public-line/ (local files only)")
    a = ap.parse_args(argv)
    try:
        files, manifest = fetch_live(get or make_get())
    except Exception as e:
        out("twilio deploy: could not read the live build (%s)" % type(e).__name__)
        return 2
    if a.export:
        names = export(files, manifest, src_dir)
        out("exported %d files: %s" % (len(names), ", ".join(names)))
        return 0
    rep = diff(files, manifest, read_repo(src_dir))
    if not rep:
        out("DRY RUN: 0 diff, the repo equals the live production build (%d Functions + manifest)" % len(files))
        return 0
    out("DRY RUN: the repo differs from live")
    for l in rep:
        out(l)
    return 1


if __name__ == "__main__":
    sys.exit(main())
