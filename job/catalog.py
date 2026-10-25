"""Catalog writers for ce_directories: price + period of paid rows, and the dead-row flag. Needs db/004_catalog_flags.sql applied first.

Mike's standing rule (10/25): skip paid rows, record price and period. Catalog rows are never deleted; a dead row is flagged and the build skips it.
Both helpers go through one injectable `db` (the real one is directories.DirDB). No Directory traffic.
"""
import os, sys, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PERIODS = ("one-time", "/mo", "/yr")


class CatalogError(Exception):
    pass


def _domain(d):
    d = (d or "").strip().lower()
    if not d or "/" in d or " " in d or "?" in d or "&" in d:
        raise CatalogError("domain must be a bare domain, got %r" % (d,))
    return d


def write_cost(db, domain, amount, period, note=None, day=None):
    """Mark a Directory paid with its amount (USD) and period. period None is allowed only when it is genuinely unconfirmed (then say so in the note)."""
    domain = _domain(domain)
    if period is not None and period not in PERIODS:
        raise CatalogError("period must be one of %s or None, got %r" % ("/".join(PERIODS), period))
    if amount is not None:
        try: amount = round(float(amount), 2)
        except (TypeError, ValueError): raise CatalogError("amount must be a number, got %r" % (amount,))
        if amount <= 0: raise CatalogError("amount must be positive")
    day = day or datetime.date.today().isoformat()
    body = {"cost": "paid", "cost_amount": amount, "cost_period": period, "last_verified": day, "updated_at": day + "T00:00:00Z"}
    if note: body["cost_note"] = note
    db.call("PATCH", "ce_directories?domain=eq.%s" % domain, body)
    return body


def mark_dead(db, domain, reason, day=None):
    """Flag a Catalog row dead. Never deletes. Reason is required."""
    domain = _domain(domain)
    if not (reason or "").strip(): raise CatalogError("a dead flag needs a reason")
    day = day or datetime.date.today().isoformat()
    body = {"dead": True, "dead_reason": reason.strip(), "dead_on": day, "updated_at": day + "T00:00:00Z"}
    db.call("PATCH", "ce_directories?domain=eq.%s" % domain, body)
    return body


def main(argv=None):
    import argparse, directories as D
    a = argparse.ArgumentParser(description="Write paid-row cost or a dead flag to ce_directories")
    s = a.add_subparsers(dest="cmd", required=True)
    c = s.add_parser("cost"); c.add_argument("domain"); c.add_argument("--amount", type=float, required=True)
    c.add_argument("--period", choices=PERIODS); c.add_argument("--note")
    d = s.add_parser("dead"); d.add_argument("domain"); d.add_argument("--reason", required=True)
    n = a.parse_args(argv)
    db = D.DirDB()
    print(write_cost(db, n.domain, n.amount, n.period, n.note) if n.cmd == "cost" else mark_dead(db, n.domain, n.reason))
    return 0


if __name__ == "__main__":
    sys.exit(main())
