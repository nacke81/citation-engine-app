"""Pure result logic: raw discovery rows -> one result per business x Directory. No network, no browser.

Statuses: found | absent | couldnt_check | unsearchable.
Absent only under the strict rule (golden 2): a verified own-results page with >=1 result and no match, AND the same method found a
known listing (any business) on that Directory in the same run. Any other miss is couldnt_check. The engine never sets unsearchable;
the list comes from identity.json (Mike-confirmed, never by the engine).
"""
import math, re
from collections import defaultdict


def _norm(r, found_dirs_by_method):
    if r["status"] == "found":
        return "found"
    if r["status"] != "noresult":
        return "couldnt_check"
    strict = bool(r.get("verified") and r.get("results", 0) >= 1)
    ctrl = r["dir"] in found_dirs_by_method.get(r["method"], set())
    return "absent" if (strict and ctrl) else "couldnt_check"


def combine(rows, dirs, unsearchable=(), bizs=("SCC", "NM", "FAKE")):
    disc = [dict(r) for r in rows if r.get("kind") in ("dir", "map")]
    ctrl = defaultdict(set)
    for r in disc:
        if r["status"] == "found" and r["biz"] in ("SCC", "NM"):
            ctrl[r["method"]].add(r["dir"])
    for r in disc:
        r["result"] = _norm(r, ctrl)
    out = {}
    for b in bizs:
        for d in dirs:
            c = [r for r in disc if r["biz"] == b and r["dir"] == d]
            f = [r for r in c if r["result"] == "found"]
            a = [r for r in c if r["result"] == "absent"]
            if d in unsearchable and b != "FAKE":
                out[(b, d)] = ("unsearchable", None)
            elif f:
                out[(b, d)] = ("found", f[0])
            elif a:
                out[(b, d)] = ("absent", a[0])
            else:
                out[(b, d)] = ("couldnt_check", None)
    return out


def nap_flags(src):
    """Name/street/phone match flags from a found row's evidence."""
    ev = (src or {}).get("ev") or {}
    street = bool(ev.get("street"))
    phone = bool(ev.get("phones"))
    return {
        "name_match": bool(ev.get("name")), "street_match": street, "phone_match": phone,
        "stale_phone": bool(ev.get("stale_phone")), "old_street": bool(ev.get("old_street")),
        "match": bool(street and phone),   # Y only when both canonical street and canonical phone appear
    }


def hard_negative_ok(rows, hardneg_id):
    h = [r for r in rows if r.get("kind") == "hardneg"]
    return len(h) >= 2 and all(r["status"] == "rejected" for r in h) and not any(hardneg_id in (r.get("url") or "") and r["status"] == "claimed" for r in h)


def made_up_ok(combined):
    return not any(res == "found" for (b, d), (res, s) in combined.items() if b == "FAKE")


def blocked_ok(combined, rows, d="yellowpages.com"):
    cells = [r for r in rows if r.get("kind") == "dir" and r["biz"] == "FAKE" and r["dir"] == d and r.get("blocked_on_purpose")]
    return combined[("FAKE", d)][0] == "couldnt_check" and bool(cells) and all(r["status"] == "couldnt" for r in cells)


def load_truth(path):
    t = {}
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\|\s*(\d+)\s*\|\s*([a-z0-9.\-]+)\s*\|\s*(SCC|NM)\s*\|\s*(found|absent|couldn't check)\s*\|\s*([^|]*)\|", line)
        if m:
            t[(m.group(3), m.group(2))] = m.group(4)
    return t


def score(combined, truth, unsearchable=()):
    """Per-business found / denominator / bar, false absents, wrong business (found where truth says absent)."""
    found_truth = {(b, d) for (b, d), v in truth.items() if v == "found" and d not in unsearchable}
    denom = {b: sum(1 for (bb, d) in found_truth if bb == b) for b in ("SCC", "NM")}
    hits = {b: sum(1 for (bb, d) in found_truth if bb == b and combined[(bb, d)][0] == "found") for b in ("SCC", "NM")}
    bar = {b: math.ceil(0.8 * denom[b]) for b in denom}
    false_abs = [k for k, v in truth.items() if v == "found" and combined[k][0] == "absent"]
    wrong = [k for k, v in truth.items() if v == "absent" and combined[k][0] == "found"]
    return {"hits": hits, "denom": denom, "bar": bar, "false_absent": false_abs, "wrong_business": wrong}
