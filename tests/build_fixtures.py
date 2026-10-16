"""Run LOCALLY after a weekly run. Reads the run's pages.local.json (real pages, real NAP; never committed) and writes scrubbed
fixtures to tests/fixtures/ using placeholder identity (tests/test_identity.json). Also checks the judge's verdict is identical before
and after scrubbing, and writes the hash denylist used by the leak check. Usage: python tests/build_fixtures.py <run_dir>"""
import json, os, re, sys, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job"))
run_dir = sys.argv[1]
real = json.load(open(os.path.expandvars("%LOCALAPPDATA%/citation-engine/identity.json"), encoding="utf-8"))
test = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
pages = json.load(open(os.path.join(run_dir, "pages.local.json"), encoding="utf-8"))

def digits(p): return [p, f"({p[:3]}) {p[3:6]}-{p[6:]}", f"{p[:3]}-{p[3:6]}-{p[6:]}", f"{p[:3]}.{p[3:6]}.{p[6:]}", f"+1{p}", f"{p[:3]}{p[3:6]}{p[6:]}"]

def pairs(b):
    r, t = real["BIZ"][b], test["BIZ"][b]
    out = [(r["name"], t["name"]), (r["short"], t["short"]), (r["street"], t["street"]), (r["city"], t["city"]), (r["zip"], t["zip"])]
    out += [(r["name"].replace("&", "and"), t["name"].replace("&", "and"))]
    for rp, tp in zip(r["phones"] + r["stale_phones"], t["phones"] + t["stale_phones"]):
        out += list(zip(digits(rp), digits(tp)))
    if r.get("old_street"): out.append((r["old_street"], t["old_street"]))
    out += [(r["slug"], t["slug"]), (r["short"].replace(" ", ""), t["short"].replace(" ", ""))]
    return out

def scrub(text, b):
    r, t = real["BIZ"][b], test["BIZ"][b]
    # the business name in any variant the Directory printed (the matcher's own regex), then joined/dashed/domain forms
    text = re.sub(real["RX"]["name"][b], t["name"], text, flags=re.I)
    words = [w for w in re.findall(r"[A-Za-z]+", r["short"]) if len(w) > 3]
    tw = [w for w in re.findall(r"[A-Za-z]+", t["short"]) if len(w) > 3]
    for w, z in zip(words[:1], tw[:1]):        # first distinctive word of the name -> placeholder (covers joined, domain and owner-name forms)
        text = re.sub(w, z, text, flags=re.I)
    for a, z in sorted(pairs(b), key=lambda x: -len(x[0])):
        text = re.sub(re.escape(a), z, text, flags=re.I)
    return text

def scrub_hardneg(text):
    for pat, rep in (("Senior Solutions\\s*(&|and)\\s*Consulting", "Alder Solutions & Consulting"), ("Don Allen", "Elm"), ("905[\\s.\\-)]*2290", "502-555-0199"), ("Louisville", "Louisville"), ("40207", "40299"), ("465253659", "000001")):
        text = re.sub(pat, rep, text, flags=re.I)
    return text

os.environ["CE_IDENTITY"] = os.path.expandvars("%LOCALAPPDATA%/citation-engine/identity.json")
import core as real_core  # judged with the REAL identity
fx = os.path.join(HERE, "fixtures"); os.makedirs(fx, exist_ok=True)
for f in os.listdir(fx): os.remove(os.path.join(fx, f))
manifest = []
for i, p in enumerate(pages):
    b = p["biz"]
    if p.get("hardneg"):
        verdict_real = real_core.judge_listing(p["text"], "SCC")[0]
        text = scrub_hardneg(scrub(p["text"], "SCC")); kind = "hardneg"
    else:
        verdict_real = real_core.judge_listing(p["text"], b)[0]
        text = scrub(p["text"], b); kind = "listing"
    text = text[:6000]
    name = f"{kind}-{b.lower()}-{p['directory'].split('.')[0]}-{i}.txt"
    open(os.path.join(fx, name), "w", encoding="utf-8").write(text)
    manifest.append(dict(file=name, kind=kind, biz=b, directory=p["directory"], real_verdict=verdict_real))
json.dump(manifest, open(os.path.join(fx, "manifest.json"), "w"), indent=1)

# denylist: sha256 of every identifying token (words and digit runs), so CI can scan the repo without holding the real values
GENERIC = {"senior", "nashville", "tennessee", "kentucky", "suite", "blvd"}   # common words, not identifying alone
toks = set()
for b in ("SCC", "NM"):
    r = real["BIZ"][b]
    for s in [r["name"], r["short"], r["street"], r["city"], r["zip"], r.get("old_street", "")] + r["phones"] + r["stale_phones"]:
        for w in re.findall(r"[A-Za-z0-9]+", s.lower()):
            if len(w) >= 4 and w not in ("care", "media", "consulting", "solutions", "blvd", "hills") or w.isdigit() and len(w) >= 4: toks.add(w)
    toks.add(r["slug"])
toks.add("ce" + "-leak-" + "control")
for b in ("SCC", "NM"):                       # derived from identity.json, never typed here
    r = real["BIZ"][b]; toks.add(r["short"].replace(" ", "").lower()); toks.add(re.findall(r"[A-Za-z]+", r["short"])[0].lower())
toks -= GENERIC
json.dump(sorted(hashlib.sha256(t.encode()).hexdigest() for t in toks), open(os.path.join(HERE, "denylist.json"), "w"))
print("fixtures", len(manifest), "denylist", len(toks))
