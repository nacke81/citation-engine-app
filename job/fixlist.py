"""Pure fix-list logic: one found listing -> the NAP fields that differ from canonical. No network, no browser.

A diff is {field, live, canonical}. Fields: phone, address, name. Only KNOWN stale values are flagged for phone and address
(identity.json stale_phones / old_street), so a phone this engine has never been told about is not flagged (known gap, slice 2).
Canonical display strings come from identity["CANON"][biz] when present, else are derived from the identity fields.
"""
import difflib, re

PHONE_RE = re.compile(r"\(?(\d{3})\)?[\s.\-]*(\d{3})[\s.\-]*(\d{4})")


def fmt_phone(p10):
    return f"({p10[:3]}) {p10[3:6]}-{p10[6:]}"


def canon(ident, b):
    x = ident["BIZ"][b]
    c = dict((ident.get("CANON") or {}).get(b) or {})
    c.setdefault("name", x["name"])
    c.setdefault("phone", fmt_phone(x["phones"][0]))
    c.setdefault("address", f"{x['street']}, {x['city']}, {x['st']} {x['zip']}")
    return c


def _norm_name(s):
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\b(llc|inc|the|and)\b", " ", s)
    return " ".join(s.split())


def _short_lines(text, n=90):
    return [l.strip() for l in (text or "").split("\n") if l.strip() and len(l.strip()) <= n]


def phone_diffs(text, ident, b, ev_stale):
    x = ident["BIZ"][b]
    stale = set(x.get("stale_phones") or [])
    live = []
    for l in _short_lines(text, 200):
        for m in PHONE_RE.finditer(l):
            p = m.group(1) + m.group(2) + m.group(3)
            if p in stale and p not in live:
                live.append(p)
    if not live and ev_stale:           # the job saw the stale number on the page but the saved text is thin: report the known stale value(s)
        live = list(x.get("stale_phones") or [])
    return live


def name_diff(text, ident, b):
    x = ident["BIZ"][b]
    rx = re.compile(ident["RX"]["name"][b], re.I)
    ok = {_norm_name(x["name"]), _norm_name(x["short"])}
    for l in _short_lines(text, 70):
        l2 = re.sub(r"^\d+\.\s*", "", l)
        m = rx.match(l2)
        if not m or "," in l2 or " in " in l2.lower() or " - " in l2 or "|" in l2:
            continue
        n = _norm_name(l2)
        if n in ok:
            return None
        if any(n and difflib.SequenceMatcher(None, n, o).ratio() >= 0.8 for o in ok) and not any(o.startswith(n) for o in ok):
            return l2
    return None


def old_street_live(text, ident, b):
    rx = (ident["RX"].get("old_street") or {}).get(b)
    if not rx:
        return None
    m = re.search("(?i)(" + rx + r")[^\n]{0,40}", text or "")
    return " ".join(m.group(0).split()) if m else None


def diffs_for(text, ev, ident, b):
    """ev = the discovery row's evidence flags (name/street/old_street/phones/stale_phone). Returns a list of diffs."""
    ev = ev or {}
    c = canon(ident, b)
    out = []
    for p in phone_diffs(text, ident, b, ev.get("stale_phone")) if ev.get("stale_phone") else []:
        out.append({"field": "phone", "live": fmt_phone(p), "canonical": c["phone"]})
    if ev.get("old_street") and not ev.get("street"):
        live = old_street_live(text, ident, b) or ident["BIZ"][b].get("old_street", "old street")
        out.append({"field": "address", "live": live, "canonical": c["address"]})
    nd = name_diff(text, ident, b) if text else None
    if nd:
        out.append({"field": "name", "live": nd, "canonical": c["name"]})
    return out
