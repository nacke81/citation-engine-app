"""Regenerate db/directories_seed.json and db/002_directories.sql from the v1 Catalog plus this repo's job facts.

  python db/gen_directories_seed.py --catalog <v1-catalog.json>
  python db/gen_directories_seed.py --hunt      (keeps the 86 v1 rows already in the seed; rewrites the seed JSON + 009_hunt_catalog_seed.sql from db/directories_hunt_seed.json)

<v1-catalog.json> is V1_CATALOG from nacke81/citation-engine src/catalog.ts, dumped with JSON.stringify (86 rows).
Reads job/cfg.py (the weekly 25), job/create_discovery.py (the 10 create-queue Directories) and job/claim_rules.py facts.
No client NAP is written: search URLs are templates ({name}, {short}, {city}, {st}), never filled in. The identity file is the
placeholder tests/test_identity.json, so nothing real is read. No network.
"""
import json, os, re, sys
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
os.environ["CE_IDENTITY"] = os.path.join(ROOT, "tests", "test_identity.json")
sys.path.insert(0, os.path.join(ROOT, "job"))
import cfg  # noqa: E402
import create_discovery as CD  # noqa: E402

SEED_JSON = os.path.join(HERE, "directories_seed.json")
MIGRATION = os.path.join(HERE, "002_directories.sql")
HUNT_SEED = os.path.join(HERE, "directories_hunt_seed.json")
HUNT_TEMPLATE = os.path.join(HERE, "009_hunt_catalog_seed.sql.tpl")
HUNT_MIGRATION = os.path.join(HERE, "009_hunt_catalog_seed.sql")
TOTAL_ROWS = 153   # 86 v1 Catalog + 59 hunt cycle 1 + 3 hunt cycle 2 (t_ab039aed) + 5 hunt cycle 3 (t_9736bbe4)
TEMPLATE = os.path.join(HERE, "002_directories.sql.tpl")

CATEGORY_NICHE_SENIOR = {"caring.com"}
CATEGORY_NICHE_OTHER = {"nashvegas.com", "maplenmain.com", "accountantfinder.com", "buildzoom.com", "fixr.com", "houzz.com", "thumbtack.com", "macraesbluebook.com",
                        "vetpronetwork.com", "activityhero.com", "vivinavi.com"}
CATEGORY_LOCAL = {"tntownsquare.com", "herenashville.com", "nextdoor.com", "citysquares.com", "discoverourtown.com"}

# claim_rules.py markers, copied as facts (quotes are the generic page text, not client data).
CLAIM_MARKERS = {
    "mapquest.com": "Unclaimed: 'Own this business?' then 'Claim it' on the record page. The footer 'Claim your business' never counts.",
    "merchantcircle.com": "Unclaimed: 'Is this your business?' then 'Claim your business now' (GET html), or the Chrome form 'Is this your business?' / 'Claim this business' (read 2026-10-20).",
    "yellowpages.com": "Claimed: a 'Claimed' badge in the listing header. Unclaimed: 'Is this your business?' / 'Claim This Business' (Chrome read 2026-10-20). Both on one page = unknown.",
    "superpages.com": "Unclaimed only: 'Are you the business owner?' then 'Claim This Business' (Chrome read 2026-10-20). Plain GET answers 403. A page without the pair stays unknown.",
    "n49.com": "Unclaimed only: 'Own this Business' then 'Get Verified' on the record page. 'Business Claimed' is not read as claimed.",
    "hotfrog.com": "Unclaimed only: 'Is this your business? Claim this business' directly under this listing's own block.",
}
# Facts seen on the 2026-10-21 runs. Agent blocked = the agent cannot do the step; Mike or a human must.
BLOCKED = {
    "yellowpages.com": "Cloudflare block on the agent's visit (2026-10-21 run).",
    "superpages.com": "Thryv claim page answers 403 (2026-10-21 run). Thryv also runs DexKnows; not yet seen there.",
    "acompio.us": "Signup page is behind a Turnstile CAPTCHA (2026-10-21 run).",
    "bing.com": "Microsoft signup anti-abuse check blocks agent signups (2026-10-21 run).",
}
BLOCKED_ON = "2026-10-21"

BING_ROUTE_NOTE = ("Mike's Bing Places agency account, GBP sync. The agency account imports each client from their Google Business Profile and "
                   "re-syncs with the Sync button. Fix Bing NAP by fixing GBP first, then press Sync. A sync publishes in 7-12 days "
                   "('Pending publish') with no phone verification. Never create a per-client Microsoft account or a listings@ Bing account. "
                   "On 2026-10-21 the agency account held 4 locations (SCC, NM and two others). If an agent ever needs to log in, Mike adds "
                   "a user on the agency account and shares the item in Vaultwarden. Until then, Bing work is a one-click Mike task. "
                   "Source: Bing row of references/directory-verification.md in the client-citation-building skill.")


def token_identity():
    """Swap the placeholder identity for brace tokens so URL builders print templates, never values."""
    for k in ("SCC", "NM"):
        cfg.BIZ[k].update(name="{name}", short="{short}", city="{city}", st="{st}", slug="{slug}")


def template(url):
    return url.replace("%7B", "{").replace("%7D", "}") if url else None


# Hunt Directories Nate approved for SCC builds (t_ff170c85); db/010_promote_hunt_scc.sql flips the same 8 in prod.
PROMOTED_SCC = frozenset({"yellowpagecity.com", "bizhwy.com", "expressbusinessdirectory.com", "smartcustomer.com",
                          "usbizs.com", "usaypage.com", "trustpilot.com", "threebestrated.com"})


# Promoted by migration 013 (t_41f55574): free claim page, Nate ruling on t_1061017b.
PROMOTED_013 = frozenset({"salespider.com", "hub.biz"})
PROMOTED_013_NOTES = {"salespider.com": 'Promoted t_1061017b: free claim page; agent builds, parks before any code or CAPTCHA step it cannot do free.',
                      "hub.biz": 'Promoted t_1061017b: free .hub.biz business page with public NAP; agent builds, parks before any code or CAPTCHA step it cannot do free.'}
# Added and promoted by migration 014 (t_9736bbe4): hunt-3 rows, free self-serve path seen 2026-11-09. 014 INSERTs them (they are not in prod yet).
PROMOTED_014 = frozenset({"kentuckyonline.us", "kentuckyizze.com", "findcarez.com", "elder-care.us", "findhelp.org"})
PROMOTED_014_NOTE = 'Promoted t_9736bbe4: free self-serve path seen 2026-11-09 (public GET only); agent builds, parks before any code or CAPTCHA step it cannot do free.'
# Never promote (t_e20d28d9). Lead-gen / referral class (APFM family, paid lead forms): caring.com queue row create-caring is rejected, "declined: paid lead form (Mike 10/26)"; its get-listed page is a HubSpot lead form with a required care category.
EXCLUDED_REFERRAL = frozenset({"caring.com", "agingcare.com", "senioradvisor.com", "seniorly.com", "payingforseniorcare.com", "aplaceformom.com"})
EXCLUDED_REFERRAL_NOTE = "declined: paid lead form (Mike 10/26); lead-gen/referral class, never promote"
# Agency lead magnets: a "get listed" page that hands the client's contact details to a competing agency. whosinmycity.com /get-listed/ is a Pichardo Marketing lead magnet (Nate ruling 2026-11-09). It has no row; the migration update is a no-op until one appears.
EXCLUDED_AGENCY_LEAD_MAGNET = {"whosinmycity.com": "agency lead magnet"}
EXCLUDED_AGENCY_LEAD_MAGNET_NOTE = "excluded: agency lead magnet (get-listed page hands contact details to a competing agency); never promote"
PROMOTED_ALL = PROMOTED_SCC | PROMOTED_013 | PROMOTED_014


PROMOTED_NOTE = 'Promoted t_ff170c85: free self-serve signup; agent builds, parks before any code or CAPTCHA step it cannot do free.'


def is_hunt(r):
    return str(r.get("cut") or "").startswith(("cycle1-", "cycle2-", "cycle3-"))


def main_hunt():
    """Hunt-only regenerate: the v1 rows are read back from the committed seed (002_directories.sql is not touched)."""
    rows = [r for r in json.load(open(SEED_JSON, encoding="utf-8")) if not is_hunt(r)]
    hunt = json.load(open(HUNT_SEED, encoding="utf-8"))
    write_seed(rows, hunt)
    write_sql(json.load(open(SEED_JSON, encoding="utf-8"))[:len(rows)])   # 002 carries the v1 rows incl. the exclusion


def write_seed(rows, hunt):
    assert len(rows) == 86 and len({r["domain"] for r in rows}) == 86, "v1 catalog must be 86 unique Directories"
    assert PROMOTED_ALL <= {r["domain"] for r in hunt}, "every promoted domain must be a hunt row"
    hunt = [dict(r, build_eligible=True, build_route="agent", build_route_note=PROMOTED_NOTE) if r["domain"] in PROMOTED_SCC
            else dict(r, build_eligible=True, build_route="agent", build_route_note=PROMOTED_013_NOTES[r["domain"]]) if r["domain"] in PROMOTED_013
            else dict(r, build_eligible=True, build_route="agent", build_route_note=PROMOTED_014_NOTE) if r["domain"] in PROMOTED_014
            else dict(r, build_eligible=False) for r in hunt]   # migration 010 (t_9675083c): a reseed keeps the promotion
    excl = lambda r: dict(r, build_eligible=False, build_route="none", build_route_note=EXCLUDED_REFERRAL_NOTE) if r["domain"] in EXCLUDED_REFERRAL else r
    rows = [excl(r) for r in rows]
    hunt = [excl(r) for r in hunt]   # migration 015 (t_e20d28d9): a reseed keeps the exclusion
    everything = rows + hunt
    assert len(everything) == TOTAL_ROWS and len({r["domain"] for r in everything}) == TOTAL_ROWS, "seed must be %d unique Directories" % TOTAL_ROWS
    assert not (PROMOTED_ALL & (EXCLUDED_REFERRAL | set(EXCLUDED_AGENCY_LEAD_MAGNET))), "an excluded domain can never be promoted"
    assert all(r["build_eligible"] is (r["domain"] in PROMOTED_ALL) and (r["build_route"] == "agent") is (r["domain"] in PROMOTED_ALL) for r in hunt), "hunt rows are catalog-only (build_eligible false, route none) except the promoted list"
    with open(HUNT_SEED, "w", encoding="utf-8", newline="\n") as f:
        json.dump(hunt, f, indent=1, ensure_ascii=False); f.write("\n")
    with open(SEED_JSON, "w", encoding="utf-8", newline="\n") as f:
        json.dump(everything, f, indent=1, ensure_ascii=False); f.write("\n")
    write_hunt_sql(hunt)
    print("wrote", len(everything), "rows (%d v1 + %d hunt)" % (len(rows), len(hunt)))


def main():
    if "--hunt" in sys.argv:
        return main_hunt()
    cat = json.load(open(sys.argv[sys.argv.index("--catalog") + 1], encoding="utf-8"))
    weekly = list(cfg.DIRS)
    # facts that need the placeholder identity (pattern URLs need a real state) are computed BEFORE tokens go in
    has_pattern = {d: bool(cfg.pattern_urls(d, "SCC")) for d in weekly}
    has_phone = {d: cfg.phone_urls(d, "SCC", "5025550101") is not None for d in weekly}
    token_identity()
    own_search = {d: template(cfg.search_url(d, "SCC")) for d in weekly}
    create = CD.CREATE_DIRS
    create_search = {}
    for d, c in create.items():
        create_search[d] = template(c["search"]("{name}")) if c["search"] else None
    rows = []
    for i, c in enumerate(cat):
        d = c["domain"]
        in25, in10 = d in weekly, d in create
        cr = create.get(d)
        if c.get("aggregator"): category = "aggregator"
        elif d in CATEGORY_NICHE_SENIOR: category = "niche-senior"
        elif d in CATEGORY_NICHE_OTHER: category = "niche-other"
        elif d in CATEGORY_LOCAL: category = "local"
        else: category = "general"
        if in25 and c["cut"] == "SCC-38": priority = 1
        elif c["cut"] == "SCC-38": priority = 2
        elif c["cut"] == "sheet-fill": priority = 3
        else: priority = 4
        methods = []
        if in25:
            methods.append("own-search")
            if has_pattern[d]: methods.append("URL pattern")
            if has_phone[d]: methods.append("phone search")
            if d in ("google.com", "maps.apple.com", "bing.com"): methods.append("map own-search")
            method, tmpl = "; ".join(methods), own_search[d]
        elif in10:
            method, tmpl = ("own-search (create discovery)", create_search[d]) if create_search[d] else ("none found (no public own-search, 2026-10-19)", None)
        else:
            method, tmpl = "not checked", None
        vm = [k for k, v in c["verificationMethods"].items() if v in ("optional", "required") and k != "none"]
        vm = [{"phone-call": "phone", "sms": "sms", "postcard": "postcard", "email": "email", "video": "video"}[k] for k in vm]
        if d == "bing.com": vm.append("gbp-sync")
        if not vm: vm = ["unknown"]
        cost = c["pricing"] if c["pricing"] in ("free", "paid") else "unknown"
        cost_note = None
        account, account_note = "unknown", None
        if cr:
            if cr["cost_class"] in ("free", "paid"): cost = cr["cost_class"]
            cost_note = cr["cost"]
            la = cr["login_needed"]
            account = "yes" if la.startswith("yes") else "unknown"
            account_note = la
        if c["emailVerify"] == "required" or c["verificationMethods"].get("email") == "required": account = "yes" if account == "unknown" else account
        route, route_note = "agent", None
        if c.get("aggregator"):
            route, route_note = "aggregator", "Flagged aggregator in the v1 Catalog: fixed at the data source, not per site."
        if d == "bing.com": route, route_note = "agency-account", BING_ROUTE_NOTE
        if d in ("google.com", "maps.apple.com", "yelp.com"):
            route_note = "Agent prepares and parks before the verification step; Mike answers the code live (v1 Catalog parking point)."
        access = "blocked" if d in BLOCKED else "unknown"
        zero = bool(cr and cr["zero"])
        ev = c.get("verificationEvidence") or {}
        notes = []
        if d in CLAIM_MARKERS: notes.append("Claim markers read in job/claim_rules.py.")
        if c.get("worksheetAuthority"): notes.append("Worksheet authority %s (%s)." % (c["worksheetAuthority"], c.get("worksheetObservedAt")))
        if cr and cr.get("signup_note"): notes.append("Signup page: " + cr["signup_note"] + " (read %s)." % cr["checked_on"])
        if d == "dexknows.com": notes.append("Thryv-owned like Superpages; the Superpages claim page 403 may apply. Not yet seen here.")
        last = BLOCKED_ON if d in BLOCKED else (cr["checked_on"] if cr else (ev.get("observedAt") or None))
        rows.append(dict(
            domain=d, name=c["name"], cut=c["cut"], priority=priority, da=c.get("da"), category=category,
            checked_weekly=bool(in25 or in10), weekly_scope="weekly-25" if in25 else ("create-discovery-10" if in10 else "none"),
            search_method=method, search_url_template=tmpl,
            zero_marker_known=zero, zero_marker_text="resulted in 0 Results" if zero else None,
            claim_markers_verified=d in CLAIM_MARKERS, claim_markers=CLAIM_MARKERS.get(d),
            signup_url=(cr or {}).get("signup_url") or None, claim_url=None,
            help_url=ev.get("sourceUrl") or None,
            cost=cost, cost_note=cost_note, account_needed=account, account_note=account_note, verification_methods=vm,
            build_route=route, build_route_note=route_note,
            agent_access=access, agent_blocker=BLOCKED.get(d), agent_blocker_seen_on=BLOCKED_ON if d in BLOCKED else None,
            agent_blocker_source="manual" if d in BLOCKED else None,
            notes=" ".join(notes) or None, last_verified=last))
    hunt = json.load(open(HUNT_SEED, encoding="utf-8"))
    assert all(d in {r["domain"] for r in rows} for d in weekly), "every weekly-25 domain must be in the Catalog"
    write_seed(rows, hunt)
    write_sql(rows)
    print(sum(r["checked_weekly"] for r in rows), "checked weekly;", sum(r["agent_access"] == "blocked" for r in rows), "blocked")


def build_sql(rows):
    tpl = open(TEMPLATE, encoding="utf-8").read()
    rows = [dict(r, build_eligible=False, build_route="none", build_route_note=EXCLUDED_REFERRAL_NOTE) if r["domain"] in EXCLUDED_REFERRAL else r for r in rows]   # same exclusion as the seed (t_e20d28d9)
    blob = json.dumps(rows, separators=(",", ":"), ensure_ascii=False)
    assert "$seed$" not in blob
    return tpl.replace("@@SEED_JSON@@", blob)


def build_hunt_sql(hunt):
    tpl = open(HUNT_TEMPLATE, encoding="utf-8").read()
    blob = json.dumps(hunt, separators=(",", ":"), ensure_ascii=False)
    assert "$seed$" not in blob
    return tpl.replace("@@SEED_JSON@@", blob)


MIGRATION_014 = os.path.join(HERE, "014_add_scc_hunt3.sql")
HEADER_014 = ("-- Add and promote 5 hunt-3 Directories for SCC (kanban t_9736bbe4; Nate go on t_9736bbe4, hunt t_df418e7f). GENERATED: edit db/directories_hunt_seed.json and run python db/gen_directories_seed.py --hunt.\n"
              "-- Data only and idempotent: INSERT of exactly these 5 rows, ON CONFLICT (domain) DO NOTHING. No update, no delete, no DDL. REQUIRES 008 applied.\n"
              "-- Rows land build_eligible=true, build_route=agent: the next buildrows --write queues them for the SCC submitter. Apply only after Nate's review.\n")


def build_014_sql(hunt):
    tpl = open(HUNT_TEMPLATE, encoding="utf-8").read().replace("\r\n", "\n")
    body = "\n".join(l for l in tpl.split("\n") if not l.startswith("--"))
    rows = [r for r in hunt if r["domain"] in PROMOTED_014]
    assert len(rows) == len(PROMOTED_014)
    blob = json.dumps(rows, separators=(",", ":"), ensure_ascii=False)
    assert "$seed$" not in blob
    return HEADER_014 + body.replace("@@SEED_JSON@@", blob)


MIGRATION_015 = os.path.join(HERE, "015_exclude_referral_directories.sql")
HEADER_015 = ("-- Exclude the lead-gen/referral class and agency lead magnets from building (kanban t_e20d28d9; Nate ruling 2026-11-09). GENERATED: python db/gen_directories_seed.py --hunt.\n"
              "-- Data only and idempotent: UPDATE of three columns (build_eligible, build_route, build_route_note) on exactly the excluded domains. No insert, no delete, no DDL, no other column.\n"
              "-- caring.com is the live row it changes (build_eligible was true, route agent). A domain absent from ce_directories is simply not matched.\n")


def sql_quote(t):
    return "'" + t.replace("'", "''") + "'"


def build_015_sql():
    out = HEADER_015
    for doms, note in ((sorted(EXCLUDED_REFERRAL), EXCLUDED_REFERRAL_NOTE), (sorted(EXCLUDED_AGENCY_LEAD_MAGNET), EXCLUDED_AGENCY_LEAD_MAGNET_NOTE)):
        out += ("update public.ce_directories\n   set build_eligible = false,\n       build_route = 'none',\n       build_route_note = %s\n where domain in (%s);\n"
                % (sql_quote(note), ", ".join(sql_quote(d) for d in doms)))
    return out


def write_hunt_sql(hunt):
    with open(MIGRATION_015, "w", encoding="utf-8", newline="\n") as f:
        f.write(build_015_sql())
    with open(MIGRATION_014, "w", encoding="utf-8", newline="\n") as f:
        f.write(build_014_sql(hunt))
    with open(HUNT_MIGRATION, "w", encoding="utf-8", newline="\n") as f:
        f.write(build_hunt_sql(hunt))


def write_sql(rows):
    with open(MIGRATION, "w", encoding="utf-8", newline="\n") as f:
        f.write(build_sql(rows))


if __name__ == "__main__":
    main()
