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
Verbs: open, clear_ads, fill, select, upload_logo, check, vault_fill, click, wait_mail, stop_before_submit.
Canonical NAP keys (from the approved identity, never typed into a spec): name street city st zip phone site email contact first last description state_name.
Every spec is validated at load: unknown verb, unknown NAP key, missing field, or a literal phone number / email in a value is refused before any browser starts.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_core import BuildError, Step, Site

NAP_KEYS = ("name", "street", "city", "st", "zip", "phone", "site", "email", "contact", "first", "last", "description", "state_name")
VERBS = ("open", "clear_ads", "fill", "select", "upload_logo", "check", "vault_fill", "click", "wait_mail", "stop_before_submit")
_REF = re.compile(r"\{([a-z_]+)\}")
_LITERAL_PHONE = re.compile(r"\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}")
_LITERAL_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
SPEC_DIR = os.path.join(HERE, "playbooks")


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
                "vault_fill": ("selector", "url"), "click": ("selector",)}.get(do, ())
        for k in need:
            if not s.get(k): _fail(site, i, "%s needs %r" % (do, k))
        if do == "fill" and not (s.get("key") or s.get("value") is not None): _fail(site, i, "fill needs key or value")
        if s.get("key") and s["key"] not in NAP_KEYS: _fail(site, i, "unknown NAP key %r (known: %s)" % (s["key"], ", ".join(NAP_KEYS)))
        for field in ("value", "url", "selector", "target"):
            v = s.get(field)
            if not isinstance(v, str): continue
            for ref in _REF.findall(v):
                if ref not in NAP_KEYS: _fail(site, i, "unknown NAP key {%s} in %s" % (ref, field))
            if field == "value" and (_LITERAL_PHONE.search(v) or _LITERAL_EMAIL.search(v)):
                _fail(site, i, "literal phone/email in value: use a NAP key ({phone}, {email}), the identity file owns them")
        if do == "wait_mail" and not spec.get("mail"): _fail(site, i, "wait_mail needs a top-level mail {sender, link_re}")
        if do == "stop_before_submit": stop_seen = True
        if do == "click" and s.get("submit") and not stop_seen and not any(x.get("do") == "stop_before_submit" for x in spec["steps"][:i]):
            _fail(site, i, "a submit click must come after a stop_before_submit marker (dry runs stop there)")
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
        ctx.page.check(sel); return "checked %s" % sel
    return fn


def _v_vault_fill(s):
    def fn(ctx):
        return ctx.vault_fill(_sel(ctx, s), render(s["url"], ctx.nap))
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
        ctx.page.goto(link, wait_until="domcontentloaded"); PK.wait_out_wall(ctx.page, 60)
        return "verify link opened (host %s)" % link.split("/")[2]
    return fn


def _v_stop(s):
    return lambda ctx: "live run passes the dry-run stop"


KIND = {"open": "read", "clear_ads": "fill", "fill": "fill", "select": "fill", "upload_logo": "fill", "check": "fill", "vault_fill": "fill",
        "wait_mail": "mail", "stop_before_submit": "submit"}


def build_site(spec):
    """spec dict -> build_core.Site. click is `fill` unless the step says submit:true."""
    validate(spec)
    steps = []
    for i, s in enumerate(spec["steps"]):
        do = s["do"]
        fn = _v_wait_mail(s, spec) if do == "wait_mail" else {"open": _v_open, "clear_ads": _v_clear_ads, "fill": _v_fill, "select": _v_select, "upload_logo": _v_upload_logo,
              "check": _v_check, "vault_fill": _v_vault_fill, "click": _v_click, "stop_before_submit": _v_stop}[do](s)
        kind = ("submit" if s.get("submit") else "fill") if do == "click" else KIND[do]
        name = s.get("name") or "%02d_%s" % (i + 1, do)
        steps.append(Step(name, kind, fn))
    mail = spec.get("mail")
    return Site(spec["site"], spec["domain"], steps, spec.get("vault_item"), mail)


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
