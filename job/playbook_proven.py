"""Bridge-side proven write-back (kanban t_eae8e59f). After the verify helper recorded `result --outcome accepted` (the request is `verified`), the BRIDGE run
(which holds the Directory DB access; the agent has no key) turns that request's sanitized step trace (PR #107 promote file) into the Directory's `verify`
playbook with last_proven_at = now and source = the request id. Same functions as `playbook.py from-trace --proven`.

  trace usable and not shorter than a proven playbook -> steps replaced, version bumped, last_proven_at now        -> "written"
  no trace, empty trace, or fewer steps than a proven playbook, playbook exists -> steps kept, only last_proven_at   -> "touched"
  trace fails validate_steps (6+ digit selector, email, code assignment), wrong domain / request id               -> "refused", nothing written
  nothing to prove (no trace, no playbook)                                                                         -> "no_trace"
The caller gates on the request status being `verified`; this module never decides that.
"""
import datetime, glob, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playbook as PB

NOTE_MAX = 200


def clean_note(note):
    """One line, no values: the same text rules as a step. -> the note or None (dropped, never an error)."""
    if not isinstance(note, str): return None
    t = re.sub(r"\s+", " ", note).strip()[:NOTE_MAX]
    if not t or t.lower() == "ok": return None
    try:
        PB._check_text("note", t)
    except PB.PlaybookError:
        return None
    return t


def _source(request_id, note):
    n = clean_note(note)
    return "request %s" % request_id + ("; note: " + n if n else "")


def find_trace(trace_dir, request_id, domain):
    hits = glob.glob(os.path.join(trace_dir, "promote", "%s__*__%s.json" % (domain, request_id)))
    return hits[0] if hits else None


def write_proven(db, request_id, domain, trace_dir, note=None, now=None, log=lambda m: None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    domain = (domain or "").strip().lower()
    source = _source(request_id, note)
    steps, path = None, find_trace(trace_dir, request_id, domain)
    if path:
        try:
            with open(path, encoding="utf-8") as f: tr = json.load(f)
            if not isinstance(tr, dict) or tr.get("request_id") != request_id or (tr.get("domain") or "").lower() != domain:
                log("trace does not match this request"); return "refused"
            if isinstance(tr.get("steps"), list) and tr["steps"]:
                steps = PB.steps_from_trace(tr)   # PlaybookError on a code-like or unknown step
        except PB.PlaybookError as e:
            log("trace refused: %s" % str(e)[:80]); return "refused"
        except (OSError, ValueError):
            log("trace unreadable"); return "refused"
    cur = PB.get_playbook(db, domain, "verify")
    if steps and not cur:
        steps = None   # t_8b8c2650: a trace cannot name the send step and every verify playbook needs exactly one, so it cannot create a row
        log("no stored verify playbook and a trace cannot name the send step: nothing written (set one with playbook.py set)")
    if steps and cur:
        steps = None   # t_3223ee18: a trace has no send mark, so it cannot replace a signup playbook's steps; the accepted run still proves it (touch below)
        log("stored verify playbook keeps its steps (a trace cannot name the send step)")
    if steps and not (cur and cur.get("last_proven_at") and len(steps) < len(cur.get("steps") or [])):
        PB.set_playbook(db, domain, "verify", steps, bool((cur or {}).get("send_is_signup")), source, ts, now=now)
        return "written"
    if cur:
        patch = {"last_proven_at": ts, "updated_at": ts, "source": source}
        if "stale" in cur: patch["stale"] = False
        db.call("PATCH", "ce_directory_playbooks?domain=eq.%s&task=eq.verify" % domain, patch, "return=minimal")
        return "touched"
    return "no_trace"
