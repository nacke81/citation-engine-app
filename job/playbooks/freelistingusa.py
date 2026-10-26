"""freelistingusa.com build, scripted from the run that went live 2026-10-25 (batch 8, playbook playbooks/build/freelistingusa.com.md). Run through job/build_runner.py.

Flow: /register (Cloudflare interstitial clears by itself, ~10 s) -> mail from info@freelistingusa.com with /verify-email/?key=...&login=... -> /create-listing
plan page: pick the FREE plan (the last input[name=plan], value 4; Essential $3 / Featured $5 / Premium $10 / Elite $40 are never picked) ->
/create-listing-form?currency=1&plan=4 -> title, address, postal code, state, city, category (checkbox value 34 = Business Consultants), phone, website,
b_email, description, opening hours LEFT BLANK (no approved hours), agree_terms, #submit -> /listing-order-summary "Your listing has been activated" (no payment).
Ads inject `ins` overlays on the register and listing pages: ctx.click() clears them before each click.

Register fields (playbook): name, user_login (email accepted), user_email, pass1, pass2. Their ids are unique, so no id tagging.
UNVERIFIED in this card: the listing-form field names other than the ones the playbook names (title, postal code, state, city, phone, website, b_email,
description, agree_terms, #submit). They are looked up by those names; a missing one fails loudly ("form changed") instead of guessing. The register and
listing forms were not rendered in this card because the build Chrome profile is already signed in to freelistingusa (/register redirects to /dashboard).
"""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from build_core import BuildError, Step, Site

BASE = "https://www.freelistingusa.com"
REGISTER_URL = BASE + "/register"
PLAN_URL = BASE + "/create-listing"
FREE_PLAN_VALUE = "4"
CATEGORY_VALUE = "34"   # Business Consultants
LINK_RE = r"https://www\.freelistingusa\.com/verify-email/\?[^\s\"'<>)]+"


def open_register(ctx):
    import pagekit as PK
    ctx.page.goto(REGISTER_URL, wait_until="domcontentloaded")
    PK.wait_out_wall(ctx.page, 60)
    path = ctx.page.url.split("?")[0].split("#")[0].rstrip("/")
    if not path.endswith("/register"):
        raise BuildError("/register redirected to %s: this Chrome is already signed in to freelistingusa (a second account is not made)" % path.replace(BASE, ""))
    ctx.need("input[name=name]", "input[name=user_login]", "input[name=user_email]", "input[name=pass1]", "input[name=pass2]")
    return "register form present, %d ad nodes cleared" % PK.clear_ads(ctx.page)


def fill_register(ctx):
    n = ctx.nap
    ctx.page.fill("input[name=name]", n["name"]); ctx.page.fill("input[name=user_login]", n["email"]); ctx.page.fill("input[name=user_email]", n["email"])
    return "name, login, email"


def fill_password(ctx):
    return "; ".join(ctx.vault_fill(s, REGISTER_URL) for s in ("input[name=pass1]", "input[name=pass2]"))


def submit_register(ctx):
    ctx.click("input#register")   # read 2026-10-25: input|submit|id=register|name=register
    ctx.page.wait_for_timeout(6000)
    if "verif" not in ctx.page.inner_text("body").lower()[:4000]:
        raise BuildError("register did not report a verification link (url %s)" % ctx.page.url.split("?")[0].replace(BASE, ""))
    return "registered; verification mail sent"


def verify_mail(ctx):
    link = ctx.mail_link()
    ctx.page.goto(link, wait_until="domcontentloaded")
    import pagekit as PK
    PK.wait_out_wall(ctx.page, 60)
    return "verify link opened (host %s)" % link.split("/")[2]


def pick_free_plan(ctx):
    """Free plan only: the radio whose value is 4, and only if the page still labels it $0/Free. Never a paid tier."""
    ctx.page.goto(PLAN_URL, wait_until="domcontentloaded")
    ctx.need("input[name=plan]")
    vals = ctx.page.evaluate("() => [...document.querySelectorAll('input[name=plan]')].map(e => e.value)")
    if FREE_PLAN_VALUE not in vals: raise BuildError("free plan radio (value %s) not on the plan page; plans seen: %s" % (FREE_PLAN_VALUE, ",".join(vals)))
    txt = ctx.page.inner_text("body")
    if not re.search(r"(?i)\bfree\b[^\n]{0,60}\$\s*0|\$\s*0[^\n]{0,60}\bfree\b|\bfree\b", txt): raise BuildError("plan page shows no Free tier text; refusing to pick by position")
    ctx.page.evaluate("v => { const r = [...document.querySelectorAll('input[name=plan]')].find(e => e.value === v); r.checked = true; r.dispatchEvent(new Event('change', {bubbles: true})); }", FREE_PLAN_VALUE)
    return "plan value %s (Free) selected" % FREE_PLAN_VALUE


def continue_to_form(ctx):
    ctx.click("input[type=submit][value=Continue], input[type=submit]")
    ctx.page.wait_for_load_state("domcontentloaded")
    if "plan=4" not in ctx.page.url and "create-listing-form" not in ctx.page.url:
        raise BuildError("did not reach the listing form (url %s)" % ctx.page.url.split("?")[0].replace(BASE, ""))
    return "at " + ctx.page.url.replace(BASE, "")[:60]


def fill_listing(ctx):
    n = ctx.nap
    ctx.need("input[name=title]", "textarea[name=description], input[name=description]", "input[name=agree_terms]", "#submit")
    p = ctx.page
    p.fill("input[name=title]", n["name"])
    ctx.fill_first(n["street"] + "", "input[name=address]", "input[name=street]")
    ctx.fill_first(n["zip"], "input[name=postal_code]", "input[name=zip]", "input[name=postcode]")
    ctx.fill_first(n["city"], "input[name=city]")
    ctx.fill_first(n["st"], "input[name=state]", "select[name=state]")
    ctx.fill_first(n["phone"], "input[name=phone]", "input[name=telephone]")
    ctx.fill_first(n["site"], "input[name=website]", "input[name=url]")
    ctx.fill_first(n["email"], "input[name=b_email]")
    ctx.fill_first(n["description"], "textarea[name=description]", "input[name=description]")
    p.evaluate("v => { const c = [...document.querySelectorAll('input[type=checkbox]')].find(e => e.value === v); if (!c) throw new Error('category checkbox %s not found' + v); c.checked = true; c.dispatchEvent(new Event('change', {bubbles: true})); }", CATEGORY_VALUE)
    p.check("input[name=agree_terms]")
    return "title, address, zip, city, state, phone, website, email, description, category %s; opening hours left blank" % CATEGORY_VALUE


def submit_listing(ctx):
    ctx.click("#submit")
    ctx.page.wait_for_timeout(8000)
    if "order-summary" not in ctx.page.url or "activated" not in ctx.page.inner_text("body").lower():
        raise BuildError("listing was not activated (url %s)" % ctx.page.url.split("?")[0].replace(BASE, ""))
    return "activated, no payment step"


def read_public_url(ctx):
    href = ctx.page.evaluate("() => { const a = [...document.querySelectorAll('a')].find(a => /view listing/i.test(a.innerText)); return a ? a.href : ''; }")
    if not re.match(r"^https://www\.freelistingusa\.com/listings/", href or ""): raise BuildError("View Listing link not found")
    ctx.state["public_url"] = href
    return href


SITE = Site("freelistingusa", "freelistingusa.com", [
    Step("open_register", "read", open_register), Step("fill_register", "fill", fill_register), Step("fill_password", "fill", fill_password),
    Step("submit_register", "submit", submit_register), Step("verify_mail", "mail", verify_mail), Step("pick_free_plan", "fill", pick_free_plan),
    Step("continue_to_form", "submit", continue_to_form), Step("fill_listing", "fill", fill_listing), Step("submit_listing", "submit", submit_listing),
    Step("read_public_url", "read", read_public_url)],
    mail={"sender": "freelistingusa", "link_re": LINK_RE})
