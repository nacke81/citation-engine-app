"""Supervised live dry run of the resolver. READ ONLY. SCC only. In-scope Directories only. Owned Chrome (job/owned_chrome.py), no login, no submit.
Run from a scratch clone, never the runtime clone. Output goes to --out (a workspace folder), never the real runs folder.

  python tests/resolver_dry_run.py --out <dir> [--pin <directory>=<word>] [--only yellowpages.com,cybo.com] [--edith <json>]

Writes <out>/dry_run.json and <out>/dry_run.md (table: Directory, resolved URL, NAP read, matches Edith's URL).
"""
import json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
def opt(name, default=None):
    return args[args.index(name) + 1] if name in args else default
OUT = opt("--out")
if not OUT:
    print("need --out <workspace dir>"); sys.exit(2)
OUT = os.path.abspath(OUT)
runs = os.path.normcase(os.path.expandvars("%LOCALAPPDATA%/citation-engine/runs")).replace("/", "\\")
if os.path.normcase(OUT).startswith(runs) or os.path.normcase(HERE).startswith(os.path.normcase(os.path.expandvars("%LOCALAPPDATA%/citation-engine/app"))):
    print("refusing: output or code is under the runtime clone / real runs folder"); sys.exit(2)
os.makedirs(OUT, exist_ok=True)
os.environ["CE_RUNS"] = OUT  # anything that imports run.py stays inside --out
os.environ["CE_ROWS"] = os.path.join(OUT, "rows.jsonl")
os.environ["CE_SHOTS"] = os.path.join(OUT, "shots")
os.makedirs(os.environ["CE_SHOTS"], exist_ok=True)
sys.path.insert(0, os.path.join(HERE, "..", "job"))

import core, discover, resolver  # noqa: E402
from cfg import IDENT  # noqa: E402
from owned_chrome import OwnedChrome  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

B = "SCC"
ident = dict(IDENT)
pins = {}
for p in (opt("--pin") or "").split(","):
    if "=" in p:
        k, v = p.split("=", 1); pins[k] = v
if pins:
    ident["RESOLVER_WORDS"] = {B: pins}

# Edith's proven URLs (scc-listing-playbooks-2026-10-22) hold the real business identity, so they live OUTSIDE the repo: --edith <json file>. Prefix compare for google.
EDITH = json.load(open(opt("--edith"), encoding="utf-8")) if opt("--edith") else {}


def nap_read(text):
    keep = []
    for l in (text or "").split("\n"):
        l = l.strip()
        if l and len(l) < 160 and (core.NAME[B].search(l) or core.STREET[B].search(l) or core.PHONE_RE.search(l)):
            if l not in keep:
                keep.append(l)
        if len(keep) >= 5:
            break
    return " | ".join(keep)[:400]


def same(d, got, want):
    if not got or not want:
        return None
    g = got.split("?")[0].rstrip("/")
    return g.startswith(want.rstrip("/")) if d == "google.com" else g.lower() == want.rstrip("/").lower()


only = (opt("--only") or "").split(",") if opt("--only") else list(resolver.INSCOPE)
open(os.environ["CE_ROWS"], "w").close()
rows = []
t0 = time.time()
with OwnedChrome() as oc, sync_playwright() as pw:
    ctx = pw.chromium.connect_over_cdp(oc.cdp_url).contexts[0]
    F = core.ChromeFetcher(ctx, human=True)
    F.caption = "[CE resolver dry run | read only]"

    def search_box(d, b):
        return discover.own_search_box(ctx, discover.NullRec(), d, b, "dry-" + d.split(".")[0] + "-" + b)[0]

    for d in only:
        r = resolver.resolve_cell(F, d, B, ident, search_box)
        row = dict(directory=d, status=r["status"], url=r["url"], nap=nap_read(r["text"]) if r["url"] else "", edith=EDITH.get(d),
                   matches_edith=same(d, r["url"], EDITH.get(d)), blocker=r["blocker"], note=r["note"], log=r["log"])
        rows.append(row)
        print(d, r["status"], r["url"], "| edith match:", row["matches_edith"], flush=True)

json.dump(dict(business=B, pins=pins, seconds=int(time.time() - t0), rows=rows), open(os.path.join(OUT, "dry_run.json"), "w", encoding="utf-8"), indent=1)
with open(os.path.join(OUT, "dry_run.md"), "w", encoding="utf-8") as f:
    f.write("| Directory | Result | Resolved URL | NAP read from that page | Matches Edith's URL |\n|---|---|---|---|---|\n")
    for r in rows:
        m = {True: "YES", False: "NO", None: "n/a (no URL proven)" if not r["edith"] else "no URL resolved"}[r["matches_edith"]]
        f.write("| %s | %s | %s | %s | %s |\n" % (r["directory"], r["status"] + ((" (" + r["blocker"][:60] + ")") if r["blocker"] else ""), r["url"] or "-", (r["nap"] or "-").replace("|", "/"), m))
print("wrote", OUT)
