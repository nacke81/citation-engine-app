"""hotfrog.com build on the shared runner (t_560dd259). Wraps the proven steps of playbooks/hotfrog.py (batch 4 run) as runner steps.

Register form read 2026-10-25 (GET only): form POST /register with #name, #email, #password, #password_confirmation, #accept_terms, #opt_in_marketing
(left UNCHECKED: marketing consent is not ours to give), an ALTCHA proof-of-work checkbox (`altcha-checkbox-*`, self-verifying, not a CAPTCHA service call) and
a submit button. Mail from hotfrog with /verify-email/<id>/<hash>. After verify, the company edit page takes the website in the first input[type=url] + Add.
Hotfrog sits behind a Cloudflare interstitial that clears by itself in the real build Chrome; the runner waits and never solves it.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from build_core import BuildError, Step, Site
import hotfrog as H

LINK_RE = r"https://www\.hotfrog\.com/verify-email/[^\s\"'<>)]+"


def open_register(ctx):
    import pagekit as PK
    ctx.page.goto(H.REGISTER_URL, wait_until="domcontentloaded")
    PK.wait_out_wall(ctx.page, 60)
    path = ctx.page.url.split("?")[0].rstrip("/")
    if not path.endswith("/register"):
        raise BuildError("/register redirected to %s: this Chrome is already signed in to hotfrog" % path.replace("https://www.hotfrog.com", ""))
    ctx.need("#name", "#email", "#password", "#password_confirmation", "#accept_terms")
    return "register form present"


def fill_register(ctx):
    ctx.page.fill("#name", ctx.nap["name"]); ctx.page.fill("#email", ctx.nap["email"])
    return "name, email"


def fill_password(ctx):
    return "; ".join(ctx.vault_fill(s, H.REGISTER_URL) for s in ("#password", "#password_confirmation"))


def tick_terms(ctx):
    """Terms yes; marketing opt-in stays off. The ALTCHA checkbox verifies itself in the browser."""
    if ctx.page.locator("#cookiescript_reject").count():   # cookie banner: reject non-essential, it overlays the form
        try: ctx.page.locator("#cookiescript_reject").first.click(timeout=3000)
        except Exception: pass
    ctx.page.check("#accept_terms")
    # The ALTCHA widget is hidden (display none) on this form and verifies by itself; the form posts its `altcha` payload. Do not click a hidden box.
    # We only record whether the payload exists when the submit step runs, and refuse to submit without it.
    return "terms ticked, marketing opt-in left off, cookie banner rejected"


def altcha_ready(ctx):
    for _ in range(40):
        if ctx.page.evaluate("() => { const e = document.querySelector('input[name=altcha]'); return !!e && e.value.length > 0; }"): return True
        ctx.page.wait_for_timeout(500)
    return False


def submit_register(ctx):
    if not altcha_ready(ctx): raise BuildError("ALTCHA payload empty after 20 s; needs a human, not a bypass")
    ctx.click("form[action$='/register'] button[type=submit]")
    ctx.page.wait_for_timeout(7000)
    return "registered; at " + ctx.page.url.split("?")[0]


def verify_mail(ctx):
    link = ctx.mail_link()
    ctx.page.goto(link, wait_until="domcontentloaded"); ctx.page.wait_for_timeout(5000)
    return "verify link opened"


def add_website(ctx):
    if not H.add_website(ctx.page, ctx.nap["site"]): raise BuildError("website was not shown after Add; check the page by hand")
    return "website added: " + H.site_value(ctx.nap["site"])


SITE = Site("hotfrog", "hotfrog.com", [
    Step("open_register", "read", open_register), Step("fill_register", "fill", fill_register), Step("fill_password", "fill", fill_password),
    Step("tick_terms", "fill", tick_terms), Step("submit_register", "submit", submit_register), Step("verify_mail", "mail", verify_mail),
    Step("add_website", "submit", add_website)],
    mail={"sender": "hotfrog", "link_re": LINK_RE})
