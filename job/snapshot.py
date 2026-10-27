"""Snapshot shape (t_f6267312): pure functions, no network, no env. Imported by buildqueue (overlay) and portal (payload).

Row states in the snapshot: live, submitted, pending-verify, nap-fix, blocked, rejected (plus the scan's absent / couldnt_check for rows the queue does not hold).
The queue keeps `needs-human` internally; the snapshot never shows it.
  nap-fix  = the listing exists but the NAP on it is wrong or unproven (a person fixes the listing).
  blocked  = no listing yet and a person has to do something (login, ID check, paid, wall).
Summary = recount of the rows on every write (`summary_from_rows`). No stored total survives a write.
"""

SUMMARY_KEYS = ("live", "inProgress", "napCorrect", "napChecked", "napFix", "blocked", "declined")
FROZEN_KEYS = ("found", "notFound", "correct", "withNapErrors", "couldntCheck", "checked", "pctFound", "pctFoundBasis", "directoriesChecked", "catalogTotal")
IN_PROGRESS = ("submitted", "pending-verify")


def has_listing(queue_row, d=None):
    """True when the queue row (or its snapshot row) shows a real listing: a listing URL, a listing-permalink evidence URL, or the queue state `found` / `claimed-unverified`."""
    r = queue_row or {}
    if r.get("state") in ("found", "claimed-unverified"): return True
    if r.get("listing_url"): return True
    d = d or {}
    if d.get("urlKind") == "listing" and d.get("url"): return True
    if d.get("napConsistent") is False: return True
    ev = r.get("evidence_url")
    if ev and r.get("directory"):
        try:
            import listing
            return bool(listing.is_permalink(r["directory"], ev))
        except Exception:
            return False
    return False


def classify_needs_human(queue_row=None, d=None):
    """-> 'nap-fix' | 'blocked'. A listing whose NAP is already proven right (napConsistent True) is not a NAP fix: it is blocked on a claim step."""
    if (d or {}).get("napConsistent") is True: return "blocked"
    return "nap-fix" if has_listing(queue_row, d) else "blocked"


def apply_nap_check(d, nap_check):
    """Show a live row's stored NAP read on its snapshot row. consistent None keeps napConsistent None with a reasonText (never False)."""
    if not isinstance(nap_check, dict): return d
    c = nap_check.get("consistent")
    d["napConsistent"] = c if c in (True, False) else None
    flds = [f for f in (nap_check.get("fields") or []) if isinstance(f, str)]
    d["issues"] = flds if c is False else []
    d["napErrors"] = [{"field": e.get("field"), "live": e.get("live"), "right": e.get("right")} for e in (nap_check.get("errors") or []) if isinstance(e, dict) and e.get("field")] if c is False else []
    d["napCheckedAt"] = nap_check.get("at")
    if c is None: d["reasonText"] = nap_check.get("reason") or "NAP could not be read on the listing page"
    return d


def summary_from_rows(directories):
    n = lambda f: sum(1 for d in directories if f(d))
    live = [d for d in directories if d.get("state") == "live"]
    return {
        "live": len(live),
        "inProgress": n(lambda d: d.get("state") in IN_PROGRESS),
        "napCorrect": sum(1 for d in live if d.get("napConsistent") is True),
        "napChecked": sum(1 for d in live if d.get("napConsistent") is not None),
        "napFix": n(lambda d: d.get("state") == "nap-fix"),
        "blocked": n(lambda d: d.get("state") == "blocked"),
        "declined": n(lambda d: d.get("state") == "rejected"),
    }


def finalize(payload):
    """Copy of payload: any leftover needs-human row becomes nap-fix / blocked, the frozen scan totals are dropped, summary recounted from the rows."""
    out = dict(payload)
    dirs = []
    for d in payload.get("directories") or []:
        d = dict(d)
        if d.get("state") == "needs-human":
            d["state"] = classify_needs_human(None, d)
        dirs.append(d)
    out["directories"] = dirs
    for k in FROZEN_KEYS: out.pop(k, None)
    out["summary"] = summary_from_rows(dirs)
    return out
