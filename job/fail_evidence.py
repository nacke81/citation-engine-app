"""Failure evidence for a build run (t_03a74bae). Kept out of build_runner.py, which must never write files other than through the queue helpers."""
import json, os, re, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import pagekit as PK


def runs_root():
    return os.environ.get("CE_RUNS") or os.path.expandvars("%LOCALAPPDATA%/citation-engine/runs")


# The modal / dialog / form markup that is on screen, plus every visible error-ish node's text. No input values are read (strip_values drops them anyway).
HTML_JS = """() => { const out = []; const sel = '#login-box, [role=dialog], .modal, .modal-dialog, form, .error-area, .error, .alert, [class*=error]';
  for (const e of document.querySelectorAll(sel)) { if (e.offsetParent === null && !e.matches('#login-box')) continue; out.push(e.outerHTML.slice(0, 6000)); if (out.length >= 8) break; }
  return out.join('\\n<!-- ---- -->\\n'); }"""


def strip_values(html):
    """Drop value="..." attributes and the content of password inputs from saved HTML (belt and braces: the page was never typed into by a dry run)."""
    html = re.sub(r"""(?i)\svalue\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", ' value="***"', html or "")
    return html


def save(ctx, site, step, error):
    """t_03a74bae: the page a failed step left behind, saved BEFORE the context closes: fail-<step>.png + fail-<step>.json (step, url, error, visible text excerpt,
    redacted). Local run folder only: never attach it, a dashboard can show a password. Never raises; returns {screenshot, json, url} (missing keys = could not save)."""
    out = {}
    try:
        if ctx.run_dir is None: ctx.run_dir = os.path.join(runs_root(), "build-%s-%s" % (site.name, time.strftime("%Y%m%d-%H%M%S")))
        os.makedirs(ctx.run_dir, exist_ok=True)
        safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", step.name)[:60]
        try: url = ctx.page.url
        except Exception: url = None
        try: text = PK.redact(ctx.page.inner_text("body", timeout=3000))[:1500]
        except Exception: text = ""
        png = os.path.join(ctx.run_dir, "fail-%s.png" % safe)
        try: ctx.page.screenshot(path=png, timeout=5000); out["screenshot"] = png
        except Exception: pass
        try:   # t_2d15878c: the login modal / form HTML (values and passwords stripped) so a run can tell wrong password / no account / selector apart
            raw = ctx.page.evaluate(HTML_JS)
            hp = os.path.join(ctx.run_dir, "fail-%s.html" % safe)
            with open(hp, "w", encoding="utf-8") as f: f.write(PK.redact(strip_values(raw))[:30000])
            out["html"] = hp
        except Exception: pass
        js = os.path.join(ctx.run_dir, "fail-%s.json" % safe)
        with open(js, "w", encoding="utf-8") as f: json.dump({"site": site.name, "step": step.name, "url": url, "error": PK.redact(str(error))[:500], "text_excerpt": text}, f, indent=1)
        out["json"], out["url"] = js, url
    except Exception:
        pass
    return out


