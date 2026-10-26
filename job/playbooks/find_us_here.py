"""find-us-here.com build, scripted from the run that went live 2026-10-25 (batch 8, playbook playbooks/build/find-us-here.com.md). Run through job/build_runner.py.

Facts from that run (and the register form read again 2026-10-25, GET only):
  * /listing.php is marketing only; the form is /register.php (form#registration_form, fields business_country_id, _createregiontxt, _createcitytxt,
    business_name, business_category_id, business_first_name, business_last_name, business_email_address, confirm_business_email_address, username,
    password, confirm_password (no ids), submit = input._createsubmit).
  * Pick country first; region and city lists load by JS after it. SCC: USA / <state> / <city> from the identity file / category "Consultants" (no senior-care category).
  * Username allows letters, numbers, underscore only; an email is rejected. SCC uses `sccsolutions`.
  * The two password inputs have no id: tag them (#scc-pw1, #scc-pw2) so the Vaultwarden helper can target them. An ad adds `#google_vignette` to the URL
    (the helper now ignores the fragment; the replaceState trick is no longer needed but is applied anyway) and an `ins` interstitial covers the submit button.
  * Success = "Business listing has been created" and /dashboard_free.php. The listing stays unpublished until the dashboard has contact + address + description.
  * THE DASHBOARD PRINTS THE ACCOUNT PASSWORD IN PLAIN TEXT: this module never reads or returns dashboard text; the only page text it keeps is the
    public listing URL (copy_link textarea). Do not dump that page by hand either.
  UNVERIFIED (no account in this card, so the dashboard was not opened): the dashboard field names. dashboard_* steps look fields up by name hint and fail
  loudly with "form changed" instead of guessing. First live run: confirm them, then tighten the hints.
"""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from build_core import BuildError, Step, Site

SITE_URL = "https://www.find-us-here.com"
REGISTER_URL = SITE_URL + "/register.php"
USERNAME = "sccsolutions"
VAULT_ITEM = "SCC - find-us-here.com (username sccsolutions)"


def open_register(ctx):
    import pagekit as PK
    ctx.page.goto(REGISTER_URL, wait_until="domcontentloaded")
    PK.wait_out_wall(ctx.page, 30)
    ctx.need("#registration_form", "#business_country_id", "input[name=business_name]", "input[name=password]", "input._createsubmit")
    return "register form present, %d ad nodes cleared" % PK.clear_ads(ctx.page)


def choose_location(ctx):
    ctx.pick("#business_country_id", "USA", wait_next="select._createregiontxt")
    ctx.pick("select._createregiontxt", ctx.nap["state_name"], wait_next="select._createcitytxt")
    ctx.pick("select._createcitytxt", ctx.nap["city"])
    ctx.pick("#business_category_id", "Consultants")
    return "USA / %s / %s / Consultants" % (ctx.nap["state_name"], ctx.nap["city"])


def fill_identity(ctx):
    n = ctx.nap
    ctx.page.fill("#business_name", n["name"])
    ctx.page.fill("input[name=business_first_name]", n["first"])
    ctx.page.fill("input[name=business_last_name]", n["last"])
    for f in ("business_email_address", "confirm_business_email_address"): ctx.page.fill("input[name=%s]" % f, n["email"])
    ctx.page.fill("input[name=username]", USERNAME)
    return "name, contact, email x2, username %s" % USERNAME


def fill_password(ctx):
    ctx.page.evaluate("""() => { const p = document.querySelectorAll('#registration_form input[type=password]');
        if (p.length < 2) throw new Error('password inputs not found'); p[0].id = 'scc-pw1'; p[1].id = 'scc-pw2';
        history.replaceState(null, '', '/register.php'); }""")
    url = REGISTER_URL
    return "; ".join(ctx.vault_fill(s, url) for s in ("#scc-pw1", "#scc-pw2"))


def submit_register(ctx):
    import pagekit as PK
    ctx.click("input._createsubmit")
    ctx.page.wait_for_timeout(6000)
    # URL check only. The dashboard prints the account password in plain text, so its body text is never read into Python.
    if "dashboard" not in ctx.page.url:
        raise BuildError("register did not reach the dashboard (url %s)" % ctx.page.url.split("?")[0])
    return "created; at " + ctx.page.url.split("?")[0]


def _set_by_hint(ctx, value, *hints):
    """Fill the first visible text input/textarea on the dashboard whose name or id contains a hint."""
    ok = ctx.page.evaluate("""([hints, value]) => { const els = [...document.querySelectorAll('input[type=text],input[type=url],input[type=tel],input[type=email],input:not([type]),textarea')]
        .filter(e => e.getClientRects().length && !e.readOnly && !e.disabled);
        for (const h of hints) { const e = els.find(e => ((e.name||'') + ' ' + (e.id||'')).toLowerCase().includes(h)); if (e) { e.value = value;
          e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true})); return true; } } return false; }""", [list(hints), value])
    if not ok: raise BuildError("find-us-here dashboard form changed: no field matching %s" % "/".join(hints))


def _save(ctx, label_re):
    ctx.page.evaluate("""re => { const b = [...document.querySelectorAll('input[type=submit],button')].find(e => new RegExp(re, 'i').test(e.value || e.innerText || '')); if (!b) throw new Error('save button not found'); b.click(); }""", label_re)
    ctx.page.wait_for_timeout(2500)


def dashboard_contact(ctx):
    import pagekit as PK
    PK.clear_ads(ctx.page)
    n = ctx.nap
    _set_by_hint(ctx, n["phone"], "phone"); _set_by_hint(ctx, n["email"], "email"); _set_by_hint(ctx, n["site"], "website", "url", "web")
    _save(ctx, "save|update|submit")
    return "contact saved (phone, email, website)"


def dashboard_address(ctx):
    import pagekit as PK
    PK.clear_ads(ctx.page)
    n = ctx.nap
    _set_by_hint(ctx, n["street"], "street1", "address1", "street", "address"); _set_by_hint(ctx, n["city"], "city")
    _set_by_hint(ctx, n["st"], "state", "region"); _set_by_hint(ctx, n["zip"], "zip", "postal")
    _save(ctx, "save|update|submit")
    return "address saved"


def dashboard_description(ctx):
    _set_by_hint(ctx, ctx.nap["description"], "description", "about")
    _save(ctx, "save|update|submit")
    return "description saved"


def read_public_url(ctx):
    """Public URL = the copy_link textarea. Returns ONLY that URL, never other dashboard text (the page shows the password)."""
    v = ctx.page.evaluate("() => (document.querySelector('#copy_link, textarea[name=copy_link], textarea.copy_link') || {}).value || ''")
    if not re.match(r"^https://www\.find-us-here\.com/businesses/", v or ""): raise BuildError("public listing URL (copy_link) not found on the dashboard")
    ctx.state["public_url"] = v
    return v


SITE = Site("find-us-here", "find-us-here.com", [
    Step("open_register", "read", open_register), Step("choose_location", "fill", choose_location), Step("fill_identity", "fill", fill_identity),
    Step("fill_password", "fill", fill_password), Step("submit_register", "submit", submit_register), Step("dashboard_contact", "submit", dashboard_contact),
    Step("dashboard_address", "submit", dashboard_address), Step("dashboard_description", "submit", dashboard_description), Step("read_public_url", "read", read_public_url)],
    vault_item=VAULT_ITEM, mail=None)
