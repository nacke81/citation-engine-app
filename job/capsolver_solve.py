"""Logged CapSolver solve for hand/CLI use (kanban t_bc10b2d3). Wraps pagekit.solve_captcha, so every call appends one line
{row, kind, ok, cost, note} to the solve log (CE_SOLVE_LOG, default %LOCALAPPDATA%/citation-engine/logs/capsolver-solves.jsonl),
and the per-row 3-call cap applies. Prints one JSON line like capsolver-cli.js: {"ok": true, "solution": {"gRecaptchaResponse": ...}} or {"ok": false, "reason": ...}.
The CapSolver key is never read here (the CLI reads it by name).

  python job/capsolver_solve.py --row create-findcarez --kind recaptcha-v3 --url https://www.findcarez.com/signup --sitekey <key> --page-action register
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pagekit as PK


def main(argv=None, runner=None, log_path=None, out=None):
    out = out or sys.stdout
    a = argparse.ArgumentParser(description="CapSolver solve with an automatic solve-log line")
    a.add_argument("--row", required=True)
    a.add_argument("--kind", required=True, choices=["recaptcha-v2", "recaptcha-v3", "turnstile", "image"])
    a.add_argument("--url", required=True)
    a.add_argument("--sitekey")
    a.add_argument("--page-action", help="reCAPTCHA v3 action (sent as pageAction)")
    a.add_argument("--extra", help="extra JSON object for the CLI (e.g. image body)")
    a.add_argument("--max-tries", type=int, default=3)
    ns = a.parse_args(argv)
    extra = json.loads(ns.extra) if ns.extra else {}
    if ns.page_action:
        if ns.kind != "recaptcha-v3": print(json.dumps({"ok": False, "reason": "--page-action is for recaptcha-v3 only"}), file=out); return 2
        extra["pageAction"] = ns.page_action
    try:
        tok = PK.solve_captcha(ns.row, {"type": ns.kind, "sitekey": ns.sitekey}, ns.url, runner=runner, log_path=log_path,
                               max_tries=ns.max_tries, extra=extra or None)
    except (PK.CaptchaError, ValueError) as e:
        print(json.dumps({"ok": False, "reason": str(e)[:200]}), file=out)
        return 2
    print(json.dumps({"ok": True, "solution": {"token": tok, "gRecaptchaResponse": tok} if ns.kind != "image" else {"token": tok}}), file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
