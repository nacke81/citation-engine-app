"""Data-driven site descriptions for build_runner (t_d7a907d5). A site is a JSON file next to the playbooks: job/playbooks/<site>.json. No new Python per site.

{
  "site": "citylocalpro", "domain": "citylocalpro.com", "vault_item": "SCC - citylocalpro.com",      (vault_item optional)
  "mail": {"sender": "citylocalpro", "link_re": "https://citylocalpro\\.com/verify[^\\s\"'<>)]+"},        (optional; needed by wait_mail)
  "steps": [
    {"name": "open_form", "do": "open", "url": "https://citylocalpro.com/add-your-business", "expect": ["input[name=company_name]"]},
    {"do": "clear_ads"},
    {"do": "fill", "selector": "input[name=company_name]", "key": "name"},                        key = a canonical NAP key
    {"do": "fill", "selector": "textarea[name=company_description]", "value": "{description}"},  value = text with {NAP keys}
    {"do": "fill", "selector": "input[name=state]", "key": "state_name", "optional": true},
    {"do": "select", "target": "#category", "value": "Business Consultants"},                     pagekit.select: native / select2 / Choices.js
    {"do": "upload_logo", "selector": "input[name=company_logo]"},
    {"do": "check", "selector": "#term"},
    {"do": "vault_fill", "selector": "#password", "url": "https://citylocalpro.com/add-your-business"},   password from Vaultwarden, never in the file
    {"do": "stop_before_submit"},                                                                 a dry run ends here; a live run passes it
    {"do": "click", "selector": "#signupBtn", "submit": true, "frames": false},                  submit:true = writes to the Directory (dry runs never reach it)
    {"do": "wait_mail"}                                                                          reads listings@, opens the verify link (dry runs never reach it)
  ]
}
Verbs: open, clear_ads, fill, select, upload_logo, check, vault_fill, click, wait_mail, stop_before_submit,
  uncheck {selector, js?}              check {selector, js?:true clicks it by script when the page hides the box}
  select_native {selector, label|index}  a plain <select> by visible label or position
  type_pick {selector, key|value, pick_text|pick_selector?, delay_ms?}  type slowly into a type-ahead, then click the suggestion (or ArrowDown+Enter)
  fill {..., slow:true}  types key by key instead of setting the value
  click_text {text, tag?, js?, force?}   click the first button/link whose text matches (force:true enables a disabled button first)
  type_text {selector, key|value, delay_ms?}   click + type into a rich-text box (SunEditor)
  set_value {selector, key|value}   set .value by script + input/change events (Shoelace sl-input, hidden inputs)   remove {selector}   delete blocking overlay nodes
  click_text {..., optional:true}   skip quietly when the control is absent (cookie banners)
  wait {ms}   expect_url {contains}   list_fields {}  (prints every visible control, so an unseen wizard step is discovered in ONE call)
  solve_captcha {widget?}  AFTER stop_before_submit only: reads the page, solves the widget with CapSolver (3 tries per row, logged), injects the token
vault_fill url may be "{current}" (the page's own URL, query string and all). Top-level "record": "submitted" (default) | "created-unlisted" (listing exists, not public yet / no full NAP) | "none" (--live records nothing).
Canonical NAP keys (from the approved identity, never typed into a spec): name street city st zip phone site email contact first last description state_name.
Every spec is validated at load: unknown verb, unknown NAP key, missing field, or a literal phone number / email in a value is refused before any browser starts.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_core import BuildError, Step, Site

NAP_KEYS = ("name", "street", "city", "st", "zip", "phone", "site", "email", "contact", "first", "last", "description", "state_name", "phone_digits")
VERBS = ("open", "clear_ads", "fill", "select", "upload_logo", "check", "vault_fill", "click", "wait_mail", "stop_before_submit",
         "uncheck", "select_native", "type_pick", "click_text", "wait", "expect_url", "list_fields", "solve_captcha",
         "type_text", "set_value", "remove")
_REF = re.compile(r"\{([a-z_]+)\}")
_LITERAL_PHONE = re.compile(r"\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}")
_LITERAL_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
SPEC_DIR = os.path.join(HERE, "playbooks")
RECORDS = ("submitted", "created-unlisted", "none")   # what a full --live run records; created-unlisted = the listing exists but is not public yet / lacks full NAP (t_f707b644)


def spec_path(name, spec_dir=None):
    return os.path.join(spec_dir or SPEC_DIR, name + ".json")


def has_spec(name, spec_dir=None):
    return os.path.isfile(spec_path(name, spec_dir))


def list_specs(spec_dir=None):
    d = spec_dir or SPEC_DIR
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json")) if os.path.isdir(d) else []


def _fail(site, i, msg):
    raise BuildError("spec %s step %d: %s" % (site, i + 1, msg))


def validate(spec):
    """Raises BuildError naming the step. Returns the spec."""
    site = spec.get("site")
    if not site or not spec.get("domain") or not isinstance(spec.get("steps"), list) or not spec["steps"]:
        raise BuildError("spec needs site, domain and a non-empty steps list")
    stop_seen = False
    for i, s in enumerate(spec["steps"]):
        do = s.get("do")
        if do not in VERBS: _fail(site, i, "unknown verb %r (known: %s)" % (do, ", ".join(VERBS)))
        need = {"open": ("url",), "fill": ("selector",), "select": ("target", "value"), "upload_logo": ("selector",), "check": ("selector",),
                "vault_fill": ("selector", "url"), "click": ("selector",), "uncheck": ("selector",), "select_native": ("selector",),
                "type_pick": ("selector",), "type_text": ("selector",), "set_value": ("selector",), "remove": ("selector",), "click_text": ("text",), "expect_url": ("contains",), "wait": ("ms",)}.get(do, ())
        for k in need:
            if not s.get(k): _fail(site, i, "%s needs %r" % (do, k))
        if do == "fill" and not (s.get("key") or s.get("value") is not None): _fail(site, i, "fill needs key or value")
        if do == "type_pick" and not (s.get("key") or s.get("value") is not None): _fail(site, i, "type_pick needs key or value")
        if do in ("type_text", "set_value") and not (s.get("key") or s.get("value") is not None): _fail(site, i, "%s needs key or value" % do)
        if do == "select_native" and s.get("label") is None and s.get("index") is None: _fail(site, i, "select_native needs label or index")
        if do == "solve_captcha" and not any(x.get("do") == "stop_before_submit" for x in spec["steps"][:i]):
            _fail(site, i, "solve_captcha spends money: it must come after a stop_before_submit marker (dry runs never reach it)")
        if s.get("key") and s["key"] not in NAP_KEYS: _fail(site, i, "unknown NAP key %r (known: %s)" % (s["key"], ", ".join(NAP_KEYS)))
        for field in ("value", "url", "selector", "target"):
            v = s.get(field)
            if not isinstance(v, str): continue
            for ref in _REF.findall(v):
                if ref == "current" and field == "url" and do == "vault_fill": continue
                if ref not in NAP_KEYS: _fail(site, i, "unknown NAP key {%s} in %s" % (ref, field))
            if field == "value" and (_LITERAL_PHONE.search(v) or _LITERAL_EMAIL.search(v)):
                _fail(site, i, "literal phone/email in value: use a NAP key ({phone}, {email}), the identity file owns them")
        if do == "wait_mail" and not spec.get("mail"): _fail(site, i, "wait_mail needs a top-level mail {sender, link_re}")
        if do == "wait_mail" and s.get("as") not in (None, "code", "link"): _fail(site, i, "wait_mail 'as' is 'link' (default) or 'code'")
        if do == "wait_mail" and s.get("as") == "code" and not s.get("selector"): _fail(site, i, "wait_mail as code needs 'selector' (the input the key is typed into)")
        if s.get("press") and not (do == "fill" and s.get("slow")): _fail(site, i, "'press' is only for fill with slow:true")
        if do == "stop_before_submit": stop_seen = True
        if do == "click" and s.get("submit") and not stop_seen and not any(x.get("do") == "stop_before_submit" for x in spec["steps"][:i]):
            _fail(site, i, "a submit click must come after a stop_before_submit marker (dry runs stop there)")
    d = spec.get("recheck_due_days")
    if d is not None and not (isinstance(d, int) and not isinstance(d, bool) and 1 <= d <= 30): raise BuildError("spec recheck_due_days must be a whole number of days, 1 to 30")
    g = spec.get("guard")
    if g is not None:
        if not isinstance(g, dict) or not g.get("flag") or not g.get("reason") or not isinstance(g.get("refuse_rows", []), list):
            raise BuildError("spec guard needs {flag, reason} and an optional refuse_rows list")
    if spec.get("record", "submitted") not in RECORDS: raise BuildError("spec record must be 'submitted', 'created-unlisted' or 'none'")
    if spec.get("record", "submitted") != "none":
        steps = spec["steps"]
        stop_i = next((i for i, x in enumerate(steps) if x.get("do") == "stop_before_submit"), None)
        def _is_submit(x): return (x.get("do") in ("click", "click_text") and x.get("submit")) or x.get("do") == "solve_captcha"
        if steps[-1].get("do") == "list_fields" or (stop_i is not None and not any(_is_submit(x) for x in steps[stop_i + 1:])):
            raise BuildError("spec %s: record '%s' needs a final submit step after stop_before_submit (this spec ends at %s); set \"record\": \"none\" until the fills land" % (site, spec.get("record", "submitted"), steps[-1].get("do")))
    if spec.get("mail"):
        for k in ("sender", "link_re"):
            if not spec["mail"].get(k): raise BuildError("spec mail needs %r" % k)
        re.compile(spec["mail"]["link_re"])
    return spec


def render(template, nap):
    """'{name}, {city}' -> text. Missing key is a BuildError (validate() already refused unknown names)."""
    def sub(m):
        k = m.group(1)
        if k not in nap or nap[k] in (None, ""): raise BuildError("NAP key %r has no value" % k)
        return str(nap[k])
    return _REF.sub(sub, template)


# ---- verbs -> Step functions ----------------------------------------------------------------------------------------------
def _sel(ctx, s):
    return render(s["selector"], ctx.nap)


def _v_open(s):
    def fn(ctx):
        import pagekit as PK
        ctx.page.goto(render(s["url"], ctx.nap), wait_until="domcontentloaded")
        PK.wait_out_wall(ctx.page, int(s.get("wall_seconds", 60)))
        if s.get("expect"): ctx.need(*s["expect"], wait_ms=int(s.get("wait_ms", 15000)))
        return "opened %s, %d ad/overlay nodes cleared" % (ctx.page.url.split("?")[0].split("#")[0][-60:], PK.clear_all(ctx.page))
    return fn


def _v_clear_ads(s):
    def fn(ctx):
        import pagekit as PK
        return "%d ad/overlay nodes cleared" % PK.clear_all(ctx.page, s.get("target"))
    return fn


def _v_fill(s):
    def fn(ctx):
        sel = _sel(ctx, s)
        val = ctx.nap[s["key"]] if s.get("key") else render(s["value"], ctx.nap)
        if s.get("optional") and not ctx.page.locator(sel).count(): return "skipped (%s absent)" % sel
        if s.get("slow"):   # forms that only enable their button on real key events (Thryv step 2)
            ctx.need(sel, wait_ms=int(s.get("wait_ms", 15000)))
            ctx.page.click(sel)
            if s.get("select_all"): ctx.page.keyboard.press("Control+A")   # foursquare: replace the old value by keyboard, fill() leaves Submit disabled
            else: ctx.page.fill(sel, "")
            ctx.page.type(sel, str(val), delay=int(s.get("delay_ms", 40)))
            if s.get("press"):   # t_6b1e01ff: a key after typing (chamberofcommerce ZIP + Tab fills City and State)
                ctx.page.keyboard.press(s["press"])
                if s.get("settle_ms"): ctx.page.wait_for_timeout(int(s["settle_ms"]))
            return "typed %s" % sel
        used = ctx.fill_first(str(val), *([sel] + list(s.get("fallbacks") or [])))
        return "filled %s" % used
    return fn


def _v_select(s):
    def fn(ctx):
        import pagekit as PK
        r = PK.select(ctx.page, render(s["target"], ctx.nap), render(s["value"], ctx.nap))
        return "%s -> %r (%s)" % (s["target"], r["shown"], r["kind"])
    return fn


def _v_upload_logo(s):
    def fn(ctx):
        import pagekit as PK
        return "attached %s" % PK.set_file(ctx.page, _sel(ctx, s), PK.ensure_logo())
    return fn


def _v_check(s):
    def fn(ctx):
        import pagekit as PK
        sel = _sel(ctx, s); PK.clear_ads(ctx.page, sel)
        if s.get("js"):
            ctx.page.evaluate("(s) => { const c = document.querySelector(s); if (c && !c.checked) c.click(); }", sel)
        else:
            ctx.page.check(sel)
        return "checked %s" % sel
    return fn


def _v_vault_fill(s):
    def fn(ctx):
        url = ctx.page.url if s["url"] == "{current}" else render(s["url"], ctx.nap)
        return ctx.vault_fill(_sel(ctx, s), url)
    return fn


def _v_click(s):
    def fn(ctx):
        import pagekit as PK
        sel = _sel(ctx, s)
        if s.get("frames"):
            where = PK.click_in_frames(ctx.page, [sel] if sel != "auto" else PK.SUBMIT_SELECTORS)
        else:
            ctx.click(sel); where = "page"
        if s.get("settle_ms"): ctx.page.wait_for_timeout(int(s["settle_ms"]))
        if s.get("expect_text") and s["expect_text"].lower() not in ctx.page.inner_text("body").lower()[:6000]:
            raise BuildError("after clicking %s the page does not show %r (url %s)" % (sel, s["expect_text"], ctx.page.url.split("?")[0][-60:]))
        return "clicked %s (%s)" % (sel, where)
    return fn


def _v_wait_mail(s, spec):
    def fn(ctx):
        import pagekit as PK
        link = ctx.mail_link()
        if s.get("as") == "code":   # t_6b1e01ff: the mail carries a key to TYPE (chamberofcommerce activation key), not a link to open
            sel = _sel(ctx, s)
            ctx.need(sel, wait_ms=int(s.get("wait_ms", 15000)))
            ctx.page.click(sel); ctx.page.fill(sel, ""); ctx.page.type(sel, str(link), delay=int(s.get("delay_ms", 40)))
            return "code of %d chars from the %s mail typed into %s" % (len(str(link)), spec["mail"]["sender"], sel)
        ctx.page.goto(link, wait_until="domcontentloaded"); PK.wait_out_wall(ctx.page, 60)
        return "verify link opened (host %s)" % link.split("/")[2]
    return fn


def _v_uncheck(s):
    def fn(ctx):
        import pagekit as PK
        sel = _sel(ctx, s); PK.clear_ads(ctx.page, sel)
        if s.get("js"):
            ctx.page.evaluate("(s) => { const c = document.querySelector(s); if (c && c.checked) c.click(); }", sel)
        else:
            ctx.page.uncheck(sel)
        return "unchecked %s" % sel
    return fn


def _v_select_native(s):
    def fn(ctx):
        sel = _sel(ctx, s)
        ctx.need(sel, wait_ms=int(s.get("wait_ms", 15000)))
        if s.get("label") is not None: ctx.page.select_option(sel, label=render(str(s["label"]), ctx.nap))
        else: ctx.page.select_option(sel, index=int(s["index"]))
        return "selected %s in %s" % (s.get("label", "#%s" % s.get("index")), sel)
    return fn


def _v_type_pick(s):
    def fn(ctx):
        sel = _sel(ctx, s)
        val = str(ctx.nap[s["key"]]) if s.get("key") else render(s["value"], ctx.nap)
        ctx.need(sel, wait_ms=int(s.get("wait_ms", 15000)))
        ctx.page.click(sel); ctx.page.fill(sel, "")
        ctx.page.type(sel, val, delay=int(s.get("delay_ms", 100)))
        ctx.page.wait_for_timeout(int(s.get("settle_ms", 2500)))
        if s.get("pick_text"): ctx.page.get_by_text(render(s["pick_text"], ctx.nap), exact=bool(s.get("exact", True))).first.click(timeout=8000); how = s["pick_text"]
        elif s.get("pick_selector"): ctx.page.locator(s["pick_selector"]).first.click(timeout=8000); how = s["pick_selector"]
        else:
            ctx.page.keyboard.press("ArrowDown"); ctx.page.wait_for_timeout(400); ctx.page.keyboard.press("Enter"); how = "ArrowDown+Enter"
        ctx.page.wait_for_timeout(int(s.get("after_ms", 1500)))
        return "typed %d chars into %s, picked %s" % (len(val), sel, how)
    return fn


CLICK_TEXT_JS = """(a) => {
  const want = a.text.trim().toLowerCase();
  const el = [...document.querySelectorAll(a.tag)].find(x => ((x.innerText || x.value || '').trim().toLowerCase()) === want || (!a.exact && (x.innerText || x.value || '').trim().toLowerCase().includes(want)));
  if (!el) return false;
  if (a.force) { el.disabled = false; el.removeAttribute('disabled'); }
  el.click(); return true;
}"""


def _v_click_text(s):
    def fn(ctx):
        import pagekit as PK
        PK.clear_ads(ctx.page)
        ok = ctx.page.evaluate(CLICK_TEXT_JS, {"text": render(s["text"], ctx.nap), "tag": s.get("tag", "button,a,input[type=submit]"), "exact": bool(s.get("exact", True)), "force": bool(s.get("force"))})
        if not ok and s.get("optional"): return "skipped (no %s reading %r)" % (s.get("tag", "button/link"), s["text"])
        if not ok: raise BuildError("no %s reading %r on %s" % (s.get("tag", "button/link"), s["text"], ctx.page.url.split("?")[0][-50:]))
        if s.get("settle_ms"): ctx.page.wait_for_timeout(int(s["settle_ms"]))
        if s.get("expect_text") and s["expect_text"].lower() not in ctx.page.inner_text("body").lower()[:6000]:
            raise BuildError("after clicking %r the page does not show %r (url %s)" % (s["text"], s["expect_text"], ctx.page.url.split("?")[0][-60:]))
        return "clicked text %r" % s["text"]
    return fn


def _v_type_text(s):
    """Click a contenteditable / rich-text box (SunEditor) and type into it. The text is a NAP key or a template; never a literal phone/email."""
    def fn(ctx):
        sel = _sel(ctx, s)
        val = str(ctx.nap[s["key"]]) if s.get("key") else render(s["value"], ctx.nap)
        ctx.need(sel, wait_ms=int(s.get("wait_ms", 15000)))
        ctx.page.click(sel); ctx.page.type(sel, val, delay=int(s.get("delay_ms", 20)))
        return "typed %d chars into %s" % (len(val), sel)
    return fn


SET_VALUE_JS = """(a) => { const el = document.querySelector(a.sel); if (!el) return false; el.value = a.val;
  el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); return true; }"""


def _v_set_value(s):
    """Set .value by script + input/change events: Shoelace sl-input, hidden lat/long inputs, anything fill() refuses."""
    def fn(ctx):
        sel = _sel(ctx, s)
        val = str(ctx.nap[s["key"]]) if s.get("key") else render(s["value"], ctx.nap)
        if not ctx.page.evaluate(SET_VALUE_JS, {"sel": sel, "val": val}): raise BuildError("set_value: %s not found on %s" % (sel, ctx.page.url.split("?")[0][-50:]))
        return "set %s (%d chars)" % (sel, len(val))
    return fn


REMOVE_JS = "(sel) => { const n = document.querySelectorAll(sel); n.forEach(e => e.remove()); return n.length; }"


def _v_remove(s):
    """Remove blocking overlay nodes (acompio .fullscreen-notification). Zero matches is fine."""
    def fn(ctx):
        n = ctx.page.evaluate(REMOVE_JS, _sel(ctx, s))
        return "removed %s node(s) matching %s" % (n or 0, _sel(ctx, s))
    return fn


def _v_wait(s):
    def fn(ctx):
        ctx.page.wait_for_timeout(int(s["ms"])); return "waited %s ms" % s["ms"]
    return fn


def _v_expect_url(s):
    def fn(ctx):
        waited = 0
        while s["contains"] not in ctx.page.url:
            if waited >= int(s.get("wait_ms", 15000)): raise BuildError("expected the URL to contain %r, it is %s" % (s["contains"], ctx.page.url.split("?")[0][-70:]))
            ctx.page.wait_for_timeout(500); waited += 500
        return "url has %s" % s["contains"]
    return fn


LIST_FIELDS_JS = """() => [...document.querySelectorAll('input,select,textarea,button')].filter(e => e.type !== 'hidden' && e.getClientRects().length)
  .slice(0, 60).map(e => [e.tagName.toLowerCase(), e.type || '', e.id, e.name, (e.placeholder || e.innerText || e.value || '').toString().slice(0, 30).replace(/\\s+/g, ' '), e.disabled ? 'disabled' : ''].join('|'))"""


def _v_list_fields(s):
    def fn(ctx):
        rows = ctx.page.evaluate(LIST_FIELDS_JS) or []
        ctx.log("  fields on %s:" % ctx.page.url.split("?")[0][-60:])
        for r in rows: ctx.log("    " + str(r))
        return "%d visible controls listed (no values)" % len(rows)
    return fn


def _v_solve_captcha(s):
    def fn(ctx):
        import pagekit as PK
        if ctx.dry_run: raise BuildError("solve_captcha refused in a dry run (it spends money)")
        if not ctx.row_id: raise BuildError("solve_captcha needs the queue row id (--row): the 3-try cap is counted per row")
        r = PK.solve_and_inject(ctx.page, ctx.row_id, widget_type=s.get("widget"), log_path=getattr(ctx, "solve_log", None))
        return "solved %s: %d field(s), %d callback(s), call %d of 3" % (r["kind"], r["fields"], r["callbacks"], r["tries"])
    return fn


def _v_stop(s):
    return lambda ctx: "live run passes the dry-run stop"


KIND = {"open": "read", "clear_ads": "fill", "fill": "fill", "select": "fill", "upload_logo": "fill", "check": "fill", "vault_fill": "fill",
        "wait_mail": "mail", "stop_before_submit": "submit", "uncheck": "fill", "select_native": "fill", "type_pick": "fill",
        "click_text": "fill", "wait": "read", "expect_url": "read", "list_fields": "read", "solve_captcha": "submit",
        "type_text": "fill", "set_value": "fill", "remove": "fill"}


def build_site(spec):
    """spec dict -> build_core.Site. click is `fill` unless the step says submit:true."""
    validate(spec)
    steps = []
    for i, s in enumerate(spec["steps"]):
        do = s["do"]
        fn = _v_wait_mail(s, spec) if do == "wait_mail" else {"open": _v_open, "clear_ads": _v_clear_ads, "fill": _v_fill, "select": _v_select, "upload_logo": _v_upload_logo,
              "check": _v_check, "vault_fill": _v_vault_fill, "click": _v_click, "stop_before_submit": _v_stop, "uncheck": _v_uncheck,
              "select_native": _v_select_native, "type_pick": _v_type_pick, "click_text": _v_click_text, "wait": _v_wait, "expect_url": _v_expect_url,
              "list_fields": _v_list_fields, "solve_captcha": _v_solve_captcha, "type_text": _v_type_text, "set_value": _v_set_value, "remove": _v_remove}[do](s)
        kind = ("submit" if s.get("submit") else "fill") if do in ("click", "click_text") else KIND[do]
        if do == "click_text" and s.get("submit"): kind = "submit"
        name = s.get("name") or "%02d_%s" % (i + 1, do)
        steps.append(Step(name, kind, fn))
    mail = spec.get("mail")
    site = Site(spec["site"], spec["domain"], steps, spec.get("vault_item"), mail)
    site.recheck_due_days = spec.get("recheck_due_days")   # t_6b1e01ff: an edit spec sets recheck_due = run day + N instead of a state change
    site.guard = spec.get("guard")                          # t_6b1e01ff: {"refuse_rows": [...], "flag": "new-listing", "reason": "..."}
    site.record = spec.get("record", "submitted")   # 'none': a live run does not record `submitted` (the flow stops at a verify step)
    return site


def load_spec(name_or_path, spec_dir=None):
    p = name_or_path if os.path.isfile(name_or_path) else spec_path(name_or_path, spec_dir)
    try:
        with open(p, encoding="utf-8") as f: spec = json.load(f)
    except OSError:
        raise BuildError("no site spec at %s" % p)
    except ValueError as e:
        raise BuildError("site spec %s is not valid JSON: %s" % (p, e))
    return spec


def load_site(name_or_path, spec_dir=None):
    return build_site(load_spec(name_or_path, spec_dir))
