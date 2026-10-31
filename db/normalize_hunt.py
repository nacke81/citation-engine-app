"""Normalize hunt-cycle seed files into db/directories_hunt_seed.json (the 62 catalog-only rows; kanban t_ab039aed).

  python db/normalize_hunt.py <hunt-cycle-1-seed.json> <hunt-cycle-2-seed.json> ...

Rulings (Nate, 2026-10-30): agent_access 403/429 -> blocked, every other value -> unknown with the probe text kept in notes;
build_route none, priority 4, weekly_scope none, build_eligible false (the weekly buildrows step skips these rows).
Unknown stays unknown: cost, account_needed and weekly_checkable are copied as the hunt graded them, never defaulted; an empty
verification_methods becomes ["unknown"] (the 86 rows' convention). signup_url stays null where the hunt found the site walled. No network.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "directories_hunt_seed.json")
KEYS = ["domain", "name", "cut", "priority", "da", "category", "checked_weekly", "weekly_scope", "search_method", "search_url_template",
        "zero_marker_known", "zero_marker_text", "claim_markers_verified", "claim_markers", "signup_url", "claim_url", "help_url", "cost",
        "cost_note", "account_needed", "account_note", "verification_methods", "build_route", "build_route_note", "agent_access", "agent_blocker",
        "agent_blocker_seen_on", "agent_blocker_source", "notes", "last_verified", "vertical", "weekly_checkable", "source", "build_eligible"]


def normalize(r):
    assert set(r) | {"build_eligible"} == set(KEYS), sorted(set(r) ^ set(KEYS))
    o = dict(r)
    probe = o["agent_access"]
    walled = bool(re.search(r"HTTP (403|429)", probe or ""))
    o["agent_access"] = "blocked" if walled else "unknown"
    if walled:
        o["agent_blocker"] = o["agent_blocker"] or probe
        o["agent_blocker_seen_on"] = o["last_verified"]
        o["agent_blocker_source"] = "manual"
    else:
        o["notes"] = ((o["notes"] + " ") if o["notes"] else "") + "Hunt probe access: %s." % probe
    o["priority"], o["weekly_scope"], o["build_route"], o["build_eligible"] = 4, "none", "none", False
    if not o["verification_methods"]: o["verification_methods"] = ["unknown"]
    if not o["search_method"]: o["search_method"] = "not checked"
    return {k: o[k] for k in KEYS}


def main(paths):
    rows = [normalize(r) for p in paths for r in json.load(open(p, encoding="utf-8"))]
    assert len({r["domain"] for r in rows}) == len(rows), "duplicate domain"
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rows, f, indent=1, ensure_ascii=False); f.write("\n")
    print("wrote", len(rows), "rows;", sum(r["agent_access"] == "blocked" for r in rows), "blocked;", sum(r["signup_url"] is None for r in rows), "null signup_url")


if __name__ == "__main__":
    main(sys.argv[1:])
