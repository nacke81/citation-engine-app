"""CapSolver spend count for a build batch (kanban t_d13bd638). The batch template asked for this tool by name; it did not exist.

Two jobs, both offline unless --live-balance is given:
  balance   before / after (USD) -> real spend = before - after
  solve log one JSON object per line, written by the build as it goes:
            {"row": "create-2findlocal", "kind": "image", "ok": false, "cost": 0.001, "note": "wrong at 0.87"}
            (cost = the CLI's `cost` field from its stdout; ok = the page accepted the answer, not just that CapSolver replied)
Output: per-row solve table, per-kind totals, logged cost vs balance delta, and a check against the batch cap.

  python job/count_capsolver_builds.py --log solves.jsonl [--before 10.0000 --after 9.9992] [--cap 0.05]
  python job/count_capsolver_builds.py --live-balance            print the current balance (the one network call; key read from env/profile .env by name, never printed)
Exit 1 when the spend is over --cap or the balance delta disagrees with the logged cost by more than --tolerance.
"""
import argparse, json, os, sys, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from moz import USER_AGENT   # t_8d1865a3: api.capsolver.com is Cloudflare-fronted; the default Python-urllib UA risks error 1010. One constant, leak_check-safe (split in moz.py).

ENV_NAME = "CAPSOLVER_API_KEY"
ENV_FILES = ("%LOCALAPPDATA%/hermes/profiles/citation-submitter/.env", "%LOCALAPPDATA%/hermes/.env")


def read_log(path):
    """-> list of solve dicts. Blank and '#' lines are skipped; a bad line is a ValueError naming the line number."""
    out = []
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        s = line.strip()
        if not s or s.startswith("#"): continue
        try: d = json.loads(s)
        except ValueError: raise ValueError("%s line %d is not JSON" % (path, n))
        if not isinstance(d, dict) or not d.get("row"): raise ValueError("%s line %d needs a row" % (path, n))
        d["cost"] = float(d.get("cost") or 0); d["kind"] = d.get("kind") or "unknown"; d["ok"] = bool(d.get("ok"))
        out.append(d)
    return out


def summarize(solves, before=None, after=None, cap=None):
    rows = {}
    for s in solves:
        r = rows.setdefault(s["row"], {"solves": 0, "accepted": 0, "cost": 0.0, "kinds": {}, "notes": []})
        r["solves"] += 1; r["accepted"] += 1 if s["ok"] else 0; r["cost"] += s["cost"]
        r["kinds"][s["kind"]] = r["kinds"].get(s["kind"], 0) + 1
        if s.get("note"): r["notes"].append(s["note"])
    kinds = {}
    for s in solves:
        k = kinds.setdefault(s["kind"], {"solves": 0, "accepted": 0, "cost": 0.0})
        k["solves"] += 1; k["accepted"] += 1 if s["ok"] else 0; k["cost"] += s["cost"]
    logged = round(sum(s["cost"] for s in solves), 6)
    out = {"rows": rows, "kinds": kinds, "logged_cost": logged, "solves": len(solves), "accepted": sum(1 for s in solves if s["ok"]),
           "balance_before": before, "balance_after": after, "balance_spend": None, "cap": cap, "over_cap": False, "mismatch": None}
    if before is not None and after is not None:
        out["balance_spend"] = round(before - after, 6)
    spend = out["balance_spend"] if out["balance_spend"] is not None else logged
    out["spend"] = spend
    out["over_cap"] = cap is not None and spend > cap + 1e-9
    return out


def render(s):
    w = max([len(r) for r in s["rows"]] + [3])
    lines = ["%-*s  %6s  %8s  %9s  %s" % (w, "row", "solves", "accepted", "cost USD", "kinds / notes"), "-" * (w + 40)]
    for r, v in s["rows"].items():
        lines.append("%-*s  %6d  %8d  %9.4f  %s%s" % (w, r, v["solves"], v["accepted"], v["cost"], ",".join("%s x%d" % kv for kv in sorted(v["kinds"].items())),
                                                       ("  | " + "; ".join(v["notes"])) if v["notes"] else ""))
    lines.append("")
    for k, v in sorted(s["kinds"].items()): lines.append("kind %-18s solves %d, accepted %d, cost %.4f" % (k, v["solves"], v["accepted"], v["cost"]))
    lines.append("logged cost %.4f over %d solves (%d accepted)" % (s["logged_cost"], s["solves"], s["accepted"]))
    if s["balance_spend"] is not None:
        lines.append("balance %.4f before, %.4f after: spend %.4f" % (s["balance_before"], s["balance_after"], s["balance_spend"]))
    if s["mismatch"]: lines.append("MISMATCH: " + s["mismatch"])
    if s["cap"] is not None: lines.append("cap %.2f: %s" % (s["cap"], "OVER" if s["over_cap"] else "ok"))
    return "\n".join(lines)


def api_key(env=None, files=ENV_FILES):
    env = os.environ if env is None else env
    if env.get(ENV_NAME): return env[ENV_NAME]
    for f in files:
        try:
            for l in open(os.path.expandvars(f), encoding="utf-8"):
                if l.startswith(ENV_NAME + "="): return l.split("=", 1)[1].strip().strip('"')
        except OSError: pass
    return None


def live_balance(key, opener=urllib.request.urlopen):
    """POST /getBalance -> float USD. The key goes in the request body only and is never returned or printed."""
    req = urllib.request.Request("https://api.capsolver.com/getBalance", method="POST", data=json.dumps({"clientKey": key}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
    with opener(req, timeout=20) as r: d = json.loads(r.read())
    if d.get("errorId"): raise RuntimeError("getBalance failed: %s" % d.get("errorCode"))
    return float(d["balance"])


def main(argv=None, balance_fn=None):
    a = argparse.ArgumentParser(description="CapSolver spend: balance before/after + per-row solve log")
    a.add_argument("--log"); a.add_argument("--before", type=float); a.add_argument("--after", type=float)
    a.add_argument("--cap", type=float, default=None, help="batch spend cap in USD (batch 7 template: 2.00)")
    a.add_argument("--tolerance", type=float, default=0.002, help="allowed gap between logged cost and balance delta")
    a.add_argument("--live-balance", action="store_true"); a.add_argument("--json", action="store_true")
    n = a.parse_args(argv)
    if n.live_balance:
        key = api_key()
        if not key: print("no %s in env or profile .env" % ENV_NAME, file=sys.stderr); return 1
        print("balance %.4f" % (balance_fn or (lambda: live_balance(key)))()); return 0
    if not n.log and n.before is None: a.error("give --log and/or --before/--after")
    if (n.before is None) != (n.after is None): a.error("--before and --after go together")
    s = summarize(read_log(n.log) if n.log else [], n.before, n.after, n.cap)
    if n.log and s["balance_spend"] is not None and abs(s["balance_spend"] - s["logged_cost"]) > n.tolerance:
        s["mismatch"] = "balance spend %.4f vs logged cost %.4f (gap over %.4f): a solve is missing from the log, or the CLI estimate is off" % (s["balance_spend"], s["logged_cost"], n.tolerance)
    print(json.dumps(s, indent=1) if n.json else render(s))
    return 1 if (s["over_cap"] or s["mismatch"]) else 0


if __name__ == "__main__":
    sys.exit(main())
