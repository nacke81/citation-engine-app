"""Which SCC rows can an agent still move, and when (kanban t_8d1865a3, from batch 21 t_55f368e7).

The batch worker used to write "rows still workable" by hand. This reads the queue file, the walls.gate state (hard-block tries) and the batch out-of-scope list
and prints ONE table from code:  row | state | why an agent can move it | opens on (date).
Rows that need a person (verify_type phone-call / sms / postcard / id-check / client-email, a paid tier, a Cloudflare click, a STOPPED hard-block wall) are listed
separately as "needs Mike/client" with the reason. Rows in the batch out-of-scope list are listed last. READ-ONLY: it never writes the queue. Exit 0 always.

  python job/workable.py [--queue PATH] [--today YYYY-MM-DD] [--json]

Run it FIRST and LAST in every batch and paste the table in the handoff (citation-submit skill, "Batch 21 fixes").
"""
import datetime, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import buildqueue as Q
import transitions as T
import walls as W

# Sourced from the batch 21 card body (t_55f368e7, "Out of scope (do not touch)"): tupalo paid claim, fix-bing, nextdoor, Thryv rows (yellowpages, dexknows, superpages,
# com-yellowpages), ezlocal, data-axle, ibegin, mapquest, every paid-tier row (botw, showmelocal), enrollbusiness, americasbestcompanies, 2findlocal, yelp, merchantcircle.
# One place: the next batch card edits this constant, not the report.
OUT_OF_SCOPE = {
    "tupalo.com": "tupalo paid claim", "bing.com": "fix-bing", "nextdoor.com": "nextdoor",
    "yellowpages.com": "Thryv row", "dexknows.com": "Thryv row", "superpages.com": "Thryv row", "com-yellowpages.com": "Thryv row",
    "ezlocal.com": "ezlocal", "data-axle.com": "data-axle", "ibegin.com": "ibegin", "mapquest.com": "mapquest",
    "botw.org": "paid-tier row", "showmelocal.com": "paid-tier row", "enrollbusiness.com": "enrollbusiness",
    "americasbestcompanies.com": "americasbestcompanies", "2findlocal.com": "2findlocal", "yelp.com": "yelp", "merchantcircle.com": "merchantcircle",
}
# Rows the batch card says open on a fixed date (batch 21 item 6: "fyple + yellowbot only if today is after 2026-10-29").
OPEN_AFTER = {"fyple.com": "2026-10-30", "yellowbot.com": "2026-10-30"}
NO_SEARCH = ("dnb.com", "discoverourtown.com")   # job/lookup.py SEARCH rows with url=None
WAITING = ("submitted", "pending-verify", "found", "created-unlisted", "claimed-unverified")
HUMAN_VERIFY = {"phone-call": "phone-call verification: the client takes the call", "sms": "SMS verification: the client's phone gets the code",
                "postcard": "postcard verification: a card is mailed to the client", "id-check": "ID check: the client does the photo-ID step herself",
                "client-email": "client-email attestation: needs the client's own address, not listings@"}
HUMAN_NOTE = (
    (re.compile(r"(?i)paid[- ]tier|Mike decides"), "paid tier: Mike decides (never buy)"),
    (re.compile(r"WALL:cloudflare-click"), "Cloudflare click wall: a person clicks it"),
    (re.compile(r"(?i)VERIFY:id|Veriff"), HUMAN_VERIFY["id-check"]),
    (re.compile(r"(?i)declined: .*\(Mike"), "declined by Mike"),
)


def _rows(q):
    return [r for _k, _kind, rows in T._row_lists(q) for r in rows if r.get("id")]


def _last_note(r):
    h = [x for x in (r.get("history") or []) if isinstance(x, dict)]
    return (h[-1].get("note") or "") if h else ""


def _last_verify(r):
    for x in reversed([x for x in (r.get("history") or []) if isinstance(x, dict)]):
        if x.get("verify_type"): return x["verify_type"]
    return None


def human_reason(r):
    """-> why only a person can move this row, or None. Looks at the latest verify_type and the latest note only (an old note does not outvote a newer one)."""
    if W.is_stopped(r): return "hard-block wall STOPPED after 3 tries: only Mike's --reset-wall clears it"
    st = r.get("state")
    vt = _last_verify(r)
    if vt in HUMAN_VERIFY and st in ("needs-human", "found", "submitted", "pending-verify"): return HUMAN_VERIFY[vt]
    # found / needs-human rows keep their human marker in an EARLIER note (dnb: "VERIFY:id" on 10/26; a later backoff note must not hide it). A waiting row
    # (submitted / pending-verify) is judged on its latest note only, so an old wall note does not outvote a newer step.
    notes = [(x.get("note") or "") for x in (r.get("history") or []) if isinstance(x, dict)]
    for note in (notes if st in ("found", "needs-human") else notes[-1:]):
        for rx, why in HUMAN_NOTE:
            if rx.search(note): return why
    return None


def _plus(day, n):
    return (datetime.date.fromisoformat(day) + datetime.timedelta(days=n)).isoformat()


def agent_route(q, r, today):
    """-> (why an agent can move it, opens-on date). Opens today means open now."""
    st, d = r.get("state"), r.get("directory")
    due = str(r["recheck_due"]) if r.get("recheck_due") else None
    if st in WAITING:
        opens = max(today, due) if due else today
        used = T.no_url_backoffs(r)
        if due is None and not r.get("listing_url") and d in NO_SEARCH:   # an entry/thank-you page in evidence_url is not a listing
            why = "recheck --backoff-only (no public search, mail scan only); NO recheck_due set yet"
        elif st == "pending-verify" and not r.get("listing_url"): why = "re-send the verify mail once, read listings@ (all folders), open the link"
        elif r.get("listing_url"): why = "recheck: read listing_url, --write on a NAP match"
        elif Q.is_mail_only(r): why = "mail_scan.py approval mail, then recheck"
        else: why = "lookup.py / recheck: find the listing URL, --write on a NAP match"
        if used: why += " (no-URL backoffs %d/%d)" % (used, T.MAX_NO_URL_BACKOFFS)
        return why, opens
    if st == "queued":
        return ("build: queued with Mike's blanket approval" if Q.approval_ok(r) else "queued but NOT approved (needs Mike's approval row)"), today
    if st == "needs-human":
        gate = W.gate(q, d, today)
        if gate:   # a hard-block try already happened today: one try per calendar day
            return "hard-block retry (%d of %d used): %s" % (len(W.tries(r)), W.MAX_TRIES, gate.split(": ", 1)[-1]), _plus(today, 1)
        if d in OPEN_AFTER: return "retry the free route (site was down / updating)", max(today, OPEN_AFTER[d])
        if W.tries(r): return "hard-block retry (%d of %d used), gate open today" % (len(W.tries(r)), W.MAX_TRIES), today
        return None, None
    return None, None


def classify(q, today):
    """-> {"counts", "workable", "needs_human", "out_of_scope"}; each list holds {row, directory, state, why, opens, recheck_due}."""
    rows = _rows(q)
    counts = {}
    out = {"workable": [], "needs_human": [], "out_of_scope": []}
    for r in rows:
        st = r.get("state") or "?"
        counts[st] = counts.get(st, 0) + 1
        if st in ("live", "rejected"): continue
        item = {"row": r["id"], "directory": r.get("directory"), "state": st, "recheck_due": str(r["recheck_due"]) if r.get("recheck_due") else None, "why": None, "opens": None}
        h = human_reason(r)
        if h:
            item["why"] = h; out["needs_human"].append(item); continue
        if r.get("directory") in OUT_OF_SCOPE:
            item["why"] = "out of scope this batch (%s)" % OUT_OF_SCOPE[r["directory"]]; out["out_of_scope"].append(item); continue
        why, opens = agent_route(q, r, today)
        if why is None:
            item["why"] = "needs-human with no agent route recorded: %s" % (_last_note(r)[:90].replace("\n", " ") or "no note")
            out["needs_human"].append(item); continue
        item["why"], item["opens"] = why, opens
        out["workable"].append(item)
    out["workable"].sort(key=lambda i: (i["opens"], i["row"]))
    out["needs_human"].sort(key=lambda i: i["row"]); out["out_of_scope"].sort(key=lambda i: i["row"])
    out["counts"] = dict(sorted(counts.items()))
    return out


def render(res, today):
    def table(items, cols, heads):
        w = [max(len(h), *(len(str(i.get(c) or "-")) for i in items)) if items else len(h) for c, h in zip(cols, heads)]
        ln = [" | ".join(h.ljust(n) for h, n in zip(heads, w)), "-+-".join("-" * n for n in w)]
        ln += [" | ".join(str(i.get(c) or "-").ljust(n) for c, n in zip(cols, w)) for i in items]
        return ln
    lines = ["workable rows as of %s   (queue states: %s)" % (today, ", ".join("%s %d" % kv for kv in res["counts"].items())), ""]
    lines.append("AN AGENT CAN MOVE (%d)" % len(res["workable"]))
    lines += table([dict(i, opens=("now" if i["opens"] <= today else i["opens"])) for i in res["workable"]], ("row", "state", "why", "opens"), ("row", "state", "why an agent can move it", "opens on"))
    lines += ["", "NEEDS MIKE / CLIENT (%d)" % len(res["needs_human"])]
    lines += table(res["needs_human"], ("row", "state", "why", "recheck_due"), ("row", "state", "reason", "recheck_due"))
    lines += ["", "OUT OF SCOPE THIS BATCH (%d)" % len(res["out_of_scope"])]
    lines += table(res["out_of_scope"], ("row", "state", "why"), ("row", "state", "why"))
    now = sum(1 for i in res["workable"] if i["opens"] <= today)
    lines += ["", "open now: %d; open later: %d; needs Mike/client: %d; out of scope: %d" % (now, len(res["workable"]) - now, len(res["needs_human"]), len(res["out_of_scope"]))]
    return "\n".join(lines)


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="Print which SCC rows an agent can still move and the date each opens (read-only)")
    a.add_argument("--queue", default=None)
    a.add_argument("--today", default=None)
    a.add_argument("--json", action="store_true")
    n = a.parse_args(argv)
    today = n.today or datetime.date.today().isoformat()
    with open(n.queue or Q.QUEUE_PATH, encoding="utf-8") as f: q = json.load(f)
    res = classify(q, today)
    print(json.dumps(dict(res, today=today), indent=2) if n.json else render(res, today))
    return 0


if __name__ == "__main__":
    sys.exit(main())
