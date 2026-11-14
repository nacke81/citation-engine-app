"""Verify Now per-stage scoreboard (t_e49457af).

Writers (never raise, never hold a code): stamp(rid, stage, at=None, **meta) records one stage time in a per-request scratch file under
CE_LOGS/verify-stages/ (first write wins per stage); finalize(rid, outcome) appends ONE row to CE_LOGS/verify-scoreboard.jsonl
(default %LOCALAPPDATA%/citation-engine/logs) and removes the scratch file. A second finalize writes nothing. VerifyRpc.finish calls
finalize after a successful finish_code_request, so every close path (helper, send run, sweeper, fence refusal) lands one row.

Row: request_id, tenant, domain, channel, requested_at (the click), bridge_pickup_at (portal claimed_at), agent_start_at (launch),
agent_ready_at (the agent's first helper call: its cold start is agent_start -> agent_ready; null for script rows), signed_in_at,
send_clicked_at, code_sent_at, code_submitted_at (the client's code reached the agent/script), code_entered_at (typed and the page answered),
verified_at, outcome, send_mode (agent|script). A stage the run never reached is null.

Reader:  python job/verify_scoreboard.py --summary [--file F]   one table row per run + medians (click-to-send, code-to-verified, pickup+start).
"""
import argparse, datetime, json, os, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

STAGES = ("requested_at", "bridge_pickup_at", "agent_start_at", "agent_ready_at", "signed_in_at", "send_clicked_at", "code_sent_at",
          "code_submitted_at", "code_entered_at")
META = ("tenant", "domain", "channel", "send_mode")
FIELDS = ("request_id", "tenant", "domain", "channel") + STAGES + ("verified_at", "outcome", "send_mode")
PICKUP_START_FLAG_S = 90
SEND_MODES = ("agent", "script")


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def iso(dt):
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dir():
    import sitegate
    return sitegate.logs_dir()


def path():
    return os.path.join(_dir(), "verify-scoreboard.jsonl")


def _stage_file(rid):
    return os.path.join(_dir(), "verify-stages", "%s.json" % rid)


def _clean_rid(rid):
    s = str(rid or "")
    return s if s and all(c.isalnum() or c == "-" for c in s) else None


def _log(msg):
    print("verify_scoreboard: " + msg, file=sys.stderr, flush=True)


def _at(at):
    if at is None: return iso(now())
    return at if isinstance(at, str) else iso(at)


def stamp(rid, stage, at=None, **meta):
    """Record `stage` (first write wins) and any allow-listed meta (last write wins). Silent on any problem: timing must never break a send."""
    try:
        rid = _clean_rid(rid)
        if not rid or (stage is not None and stage not in STAGES): return False
        f = _stage_file(rid)
        os.makedirs(os.path.dirname(f), exist_ok=True)
        cur = {}
        if os.path.exists(f):
            with open(f, encoding="utf-8") as h: cur = json.load(h)
        if stage and not cur.get(stage): cur[stage] = _at(at)
        for k, v in meta.items():
            if k in META and v and (k != "send_mode" or v in SEND_MODES): cur[k] = str(v)[:80]
        tmp = f + ".tmp"
        with open(tmp, "w", encoding="utf-8") as h: json.dump(cur, h)
        os.replace(tmp, f)
        return True
    except Exception as e:
        _log("stamp skipped: %s" % type(e).__name__); return False


NOTE_MAX = 400


def set_note(rid, text):
    """t_eae8e59f: the agent's one-line playbook note, kept in the request's stage file (last write wins). The caller validates the text. -> bool."""
    try:
        rid = _clean_rid(rid)
        if not rid or not isinstance(text, str): return False
        f = _stage_file(rid)
        os.makedirs(os.path.dirname(f), exist_ok=True)
        cur = {}
        if os.path.exists(f):
            with open(f, encoding="utf-8") as h: cur = json.load(h)
        cur["playbook_note"] = text[:NOTE_MAX]
        tmp = f + ".tmp"
        with open(tmp, "w", encoding="utf-8") as h: json.dump(cur, h)
        os.replace(tmp, f)
        return True
    except Exception as e:
        _log("note skipped: %s" % type(e).__name__); return False


def take_note(rid):
    """Read the note once and drop what is left of the stage file (a finalized `verified` run leaves only the note). -> text or None."""
    try:
        rid = _clean_rid(rid)
        f = _stage_file(rid) if rid else None
        if not f or not os.path.exists(f): return None
        with open(f, encoding="utf-8") as h: cur = json.load(h)
        note = cur.get("playbook_note")
        if set(cur) <= {"playbook_note"}: os.remove(f)
        return note if isinstance(note, str) and note else None
    except Exception as e:
        _log("take_note skipped: %s" % type(e).__name__); return None


def finalize(rid, outcome, at=None):
    """Append the one row for `rid` (outcome = verified | failed:<code> | could_not_start:<code> | superseded). No stage file = nothing to report."""
    try:
        rid = _clean_rid(rid)
        if not rid: return False
        f = _stage_file(rid)
        if not os.path.exists(f): return False
        with open(f, encoding="utf-8") as h: cur = json.load(h)
        row = {"request_id": rid}
        for k in ("tenant", "domain", "channel"): row[k] = cur.get(k)
        for k in STAGES: row[k] = cur.get(k)
        row["verified_at"] = _at(at) if str(outcome) == "verified" else None
        row["outcome"] = str(outcome)
        row["send_mode"] = cur.get("send_mode")
        p = path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as h: h.write(json.dumps(row, separators=(",", ":")) + "\n")
        note = cur.get("playbook_note")
        if note and str(outcome) == "verified":   # the bridge's proven write-back runs after this; it reads the note once with take_note()
            with open(f, "w", encoding="utf-8") as h: json.dump({"playbook_note": note}, h)
        else:
            os.remove(f)
        return True
    except Exception as e:
        _log("finalize skipped: %s" % type(e).__name__); return False


# ---- reader ------------------------------------------------------------------------------------------------------------------------
def _p(ts):
    try: return datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc) if ts else None
    except Exception: return None


def _d(row, a, b):
    ta, tb = _p(row.get(a)), _p(row.get(b))
    return int((tb - ta).total_seconds()) if ta and tb else None


def load(file=None):
    rows = []
    try:
        with open(file or path(), encoding="utf-8") as h:
            for line in h:
                try:
                    r = json.loads(line)
                    if isinstance(r, dict) and r.get("request_id"): rows.append(r)
                except ValueError: continue
    except OSError:
        pass
    return rows


def durations(row):
    return {"pickup": _d(row, "requested_at", "bridge_pickup_at"), "start": _d(row, "bridge_pickup_at", "agent_start_at"),
            "cold": _d(row, "agent_start_at", "agent_ready_at"),
            "pickup_start": _d(row, "requested_at", "agent_ready_at") if row.get("agent_ready_at") else _d(row, "requested_at", "agent_start_at"),
            "signin": _d(row, "agent_ready_at", "signed_in_at") if row.get("agent_ready_at") else _d(row, "agent_start_at", "signed_in_at"),
            "to_click": _d(row, "signed_in_at", "send_clicked_at"), "click_to_send": _d(row, "requested_at", "code_sent_at"),
            "code_to_verified": _d(row, "code_submitted_at", "verified_at"), "enter": _d(row, "code_submitted_at", "code_entered_at")}


def _fmt(v):
    return "-" if v is None else str(v)


def median(vals):
    vals = [v for v in vals if v is not None]
    return int(statistics.median(vals)) if vals else None


def summary(rows, out=print):
    cols = ("request", "tenant", "domain", "ch", "mode", "outcome", "pickup_s", "start_s", "cold_s", "signin_s", "to_click_s", "click_to_send_s", "code_to_verified_s")
    keys = ("pickup", "start", "cold", "signin", "to_click", "click_to_send", "code_to_verified")
    table = []
    for r in rows:
        d = durations(r)
        table.append([str(r["request_id"])[:8], _fmt(r.get("tenant")), _fmt(r.get("domain")), _fmt(r.get("channel")), _fmt(r.get("send_mode")),
                      _fmt(r.get("outcome"))] + [_fmt(d[k]) for k in keys])
    widths = [max(len(c), *(len(t[i]) for t in table)) if table else len(c) for i, c in enumerate(cols)]
    line = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths)).rstrip()
    out(line(cols))
    for t in table: out(line(t))
    ds = [durations(r) for r in rows]
    m = lambda k: median([d[k] for d in ds])
    out("")
    out("runs: %d" % len(rows))
    out("median click-to-send (requested -> code_sent): %s s" % _fmt(m("click_to_send")))
    out("median code-to-verified (code_submitted -> verified): %s s" % _fmt(m("code_to_verified")))
    out("median bridge pickup (requested -> claimed): %s s" % _fmt(m("pickup")))
    out("median agent start (claimed -> agent_start): %s s" % _fmt(m("start")))
    ps = m("pickup_start")
    out("median agent cold start (agent_start -> agent_ready, agent runs): %s s" % _fmt(m("cold")))
    out("median pickup+start (requested -> agent_ready; agent_start for script rows): %s s%s" % (_fmt(ps), "  ** over %d s: propose a faster pickup **" % PICKUP_START_FLAG_S if ps is not None and ps > PICKUP_START_FLAG_S else ""))
    return {"click_to_send": m("click_to_send"), "code_to_verified": m("code_to_verified"), "pickup_start": ps, "cold": m("cold")}


def main(argv=None):
    a = argparse.ArgumentParser(description="Verify Now scoreboard")
    a.add_argument("--summary", action="store_true", required=True)
    a.add_argument("--file")
    n = a.parse_args(argv)
    summary(load(n.file))
    return 0


if __name__ == "__main__":
    sys.exit(main())
