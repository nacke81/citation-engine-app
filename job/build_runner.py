"""Replayable listing-build runner (t_560dd259). One runner, one small module per site.

A site is a list of Steps. Each step has a KIND:
  read    only loads / reads pages (safe in a dry run)
  fill    types into forms in the build Chrome but sends nothing to the Directory
  mail    reads the listings@ mailbox (read-only: EXAMINE + BODY.PEEK) and opens the link
  submit  anything that writes to the Directory (form submit, plan pick, dashboard save)
`--dry-run` runs steps until the FIRST `submit` or `mail` step and stops there, so nothing is created and no mail is waited on.
`--live` is refused unless `--card <id>` names the Nate card that authorizes the build (it creates a Directory account).
Browser: the build Chrome on CDP 9333 (job/build_chrome.py). Passwords: never in this file; `vault_fill()` calls the skill's vaultwarden-cli-fill.js
(`--cdp`, `--item-id` or `--name`) which reads the vault item and sets the field in the page. The runner never sees or prints the password.
Mail: hotfrog.ImapMailbox over LISTINGS_IMAP_* (read-only).

  python job/build_runner.py find-us-here --dry-run
  python job/build_runner.py freelistingusa --dry-run
  python job/build_runner.py hotfrog --dry-run
  python job/build_runner.py <site> --live --card t_xxxx [--item-id <vault id>] [--only step,step]

A NEW SITE needs: one module job/playbooks/<site>.py exporting SITE = Site(name, domain, steps, vault_item, mail=None) where each step is
`Step(name, kind, fn)` and fn(ctx) uses ctx.page (Playwright page), ctx.nap (name/street/city/st/zip/phone/site/email/first/last/description),
ctx.vault_fill(selector, url), ctx.mail_link(), ctx.state; plus one line in SITES below and a test with a fake page. Nothing else changes.
"""
import email, html, importlib, json, os, re, subprocess, sys, time
from email.header import decode_header, make_header

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "playbooks"))
import pagekit as PK
import walls as W
from build_core import BuildError, Step, Site, KINDS

CDP_URL = "http://127.0.0.1:9333"
STOP_IN_DRY_RUN = ("mail", "submit")
SITES = {"find-us-here": "find_us_here", "freelistingusa": "freelistingusa", "hotfrog": "hotfrog_build"}
ORG, COLLECTION = "Senior Care Consulting", "Citations"
FILL_JS = os.environ.get("CE_FILL_JS") or os.path.expandvars("%LOCALAPPDATA%/hermes/profiles/citation-submitter/skills/devops/vaultwarden-cli-write/scripts/vaultwarden-cli-fill.js")
STATE_NAMES = {"KY": "Kentucky", "TN": "Tennessee"}


def nap_from_identity(ident, contact="Lea Ann Klarner", email_addr="listings@seniorcaresolutions.co", description=None):
    """The approved identity -> the dict the steps use. Name/address/phone come from the identity file, never from a site module."""
    x = ident["BIZ"]["SCC"]
    p = re.sub(r"\D", "", x["phones"][0])[-10:]
    first, last = (contact.rsplit(" ", 1) + [""])[:2] if " " in contact else (contact, "")
    return {"name": x["name"], "street": x["street"], "city": x["city"], "st": x["st"], "zip": x["zip"], "phone": "%s-%s-%s" % (p[:3], p[3:6], p[6:]),
            "site": x.get("site") or "https://seniorcaresolutions.co", "email": email_addr, "contact": contact, "first": first, "last": last,
            "description": description or "Senior care consulting for families in %s, %s and the surrounding area." % (x["city"], STATE_NAMES.get(x["st"], x["st"])), "state_name": STATE_NAMES.get(x["st"], x["st"]), "phone_digits": p, **_description_long(x)}


def _description_long(biz):
    """t_d2f75685: the canonical `description_long` (identity BIZ.SCC.description_long, written by the batch from seniorcaresolutions.co). Only a text that passes
    description_long.validate becomes a NAP key; a bad one leaves a reason that formspec.render raises, so no form is ever filled with it. Absent = no key."""
    import description_long as DL
    raw = biz.get("description_long")
    if raw in (None, ""): return {}
    try: return {"description_long": DL.validate(raw)}
    except DL.DescriptionError as e: return {"_description_long_error": str(e)}


# ---- mail ------------------------------------------------------------------------------------------------------------
def extract_link(raw, link_re):
    """First link matching link_re in a raw message (text or html parts, QP decoded, &amp; unescaped)."""
    msg = email.message_from_bytes(raw) if isinstance(raw, bytes) else email.message_from_string(raw)
    rx = re.compile(link_re)
    for part in msg.walk():
        if part.get_content_type() not in ("text/plain", "text/html"): continue
        body = part.get_payload(decode=True)
        if not body: continue
        m = rx.search(html.unescape(body.decode(part.get_content_charset() or "utf-8", "replace")))
        if m: return m.group("v") if "v" in rx.groupindex and m.group("v") else m.group(0)   # (?P<v>..) = just the key, not the text around it (t_6b1e01ff)
    return None


def make_mailbox(sender, link_re, env=None, imap_cls=None):
    import hotfrog as H
    kw = {"imap_cls": imap_cls} if imap_cls else {}
    return H.ImapMailbox(env, extract=lambda raw: extract_link(raw, link_re), sender_hint=sender, **kw)


# ---- context -----------------------------------------------------------------------------------------------------------
class Ctx:
    def __init__(self, site, page, nap, *, mailbox=None, runner=None, item_id=None, cdp=CDP_URL, dry_run=True, sleep=time.sleep, now=time.time,
                 poll_seconds=180, poll_every=10, log=print):
        self.site, self.page, self.nap, self.mailbox, self.item_id, self.cdp, self.dry_run = site, page, nap, mailbox, item_id, cdp, dry_run
        self._runner, self.sleep, self.now, self.poll_seconds, self.poll_every, self.log = runner or subprocess.run, sleep, now, poll_seconds, poll_every, log
        self.state, self._base_uid = {}, None
        self.has_account = False   # t_03a74bae: --has-account; steps tagged when has_account / new_account follow it
        self.run_dir = None        # t_03a74bae: where failure evidence goes (default: <runs>/build-<site>-<stamp>, made on the first failure)
        self.item_name = None   # vault item NAME resolved by `python job/vault_item.py --domain D` (build_runner --item-name); beats the spec's vault_item
        self.row_id = None      # queue row id of a live run (--row): the CAPTCHA 3-try cap is counted per row
        self.solve_log = None   # CapSolver solve log path (None = pagekit.SOLVE_LOG)
        self.lease = None  # chrome_keepalive.Lease: refreshed before every step so the build Chrome timer does not fire (t_d7a907d5)
        self.chrome_check = None   # callable() -> "up" | "restarted"; None in tests / non-9333 endpoints
        self.reconnect = None      # callable() -> new page after a restart
        self.sweep = None          # callable() -> closed URLs; run after a Chrome restart (a restored foreign tab must not be acted on)

    # Vaultwarden: the helper reads the item and sets the field in the page; stdout is `fill=success ...` only.
    def vault_fill(self, selector, url):
        url = url.split("#")[0]   # an ad adds #google_vignette; the helper ignores fragments, but never pass one on
        if not self.dry_run:
            # The vault helper chooses the focused target among same-URL tabs. Activate the
            # Playwright page the spec just navigated to; never fill a restored/stale tab.
            if self.page.url.split("#")[0].split("?")[0] != url.split("#")[0].split("?")[0]:
                raise BuildError("vault fill refused: current page changed before secure handoff")
            self.page.bring_to_front()
        cmd = ["node", FILL_JS, "--organization", ORG, "--collection", COLLECTION, "--url", url, "--field", selector, "--cdp", self.cdp]
        cmd += ["--item-id", self.item_id] if self.item_id else ["--name", getattr(self, "item_name", None) or self.site.vault_item]   # item_name: the name `python job/vault_item.py --domain D` printed (t_d2f75685)
        if self.dry_run: cmd = [c for c in cmd if c not in ("--field", selector)] + ["--lookup-only"]
        r = self._runner(cmd, capture_output=True, text=True, timeout=180)
        out = ((getattr(r, "stdout", "") or "") + (getattr(r, "stderr", "") or "")).strip()
        if getattr(r, "returncode", 1) != 0 and not self.item_id and "reason=not-found" in out:
            # t_3ac43137: the spec name did not match ('SCC - acompio' vs 'SCC - acompio.com'). Resolve the one item that names/links this registrable domain, retry once by id.
            import vault_item as VI
            try: self.item_id, _name = VI.resolve_for_domain(self.site.domain, runner=self._runner)
            except VI.VaultItemError as e: raise BuildError("vault fill failed: %s" % str(e)[:200])
            self.log("  vault item resolved by domain %s: %s" % (self.site.domain, _name))
            cmd = [c for c in cmd]; i = cmd.index("--name"); cmd[i:i + 2] = ["--item-id", self.item_id]
            r = self._runner(cmd, capture_output=True, text=True, timeout=180)
            out = ((getattr(r, "stdout", "") or "") + (getattr(r, "stderr", "") or "")).strip()
        if getattr(r, "returncode", 1) != 0:
            last = (out.splitlines()[-1] if out else "no output")[:200]
            # A dry run only LOOKS the item up. A seat without vault credentials cannot do that; say so, do not fail the whole dry run.
            if self.dry_run and re.search(r"reason=(profile-env-unavailable|credentials-unavailable|bw-cli-missing)", last):
                return "vault lookup skipped in dry run (%s)" % last.split("reason=")[-1]
            raise BuildError("vault fill failed: %s" % last)
        return out.splitlines()[-1] if out else "ok"

    def mail_link(self):
        if not self.mailbox or not self.site.mail: raise BuildError("%s has no mailbox configured" % self.site.name)
        if self._base_uid is None: self._base_uid = self.state.get("mail_base", 0)
        deadline = self.now() + self.poll_seconds
        while self.now() < deadline:
            found = self.mailbox.newest_verify_link(since_uid=self._base_uid)
            if found: return found[1]
            self.sleep(self.poll_every)
        raise BuildError("no %s mail at listings@ within %ds" % (self.site.mail["sender"], self.poll_seconds))

    def click(self, selector, **kw):
        """Click after clearing ad overlays (ins / google_ads / #google_vignette intercept clicks)."""
        PK.clear_ads(self.page)
        self.page.locator(selector).first.click(timeout=kw.get("timeout", 15000))

    def fill_first(self, value, *selectors):
        """Fill the first selector that exists (sites rename fields between forms). BuildError when none does."""
        for s in selectors:
            if self.page.locator(s).count():
                self.page.locator(s).first.fill(value); return s
        raise BuildError("%s form changed: none of %s found" % (self.site.name, ", ".join(selectors)))

    def pick(self, selector, label, wait_next=None, timeout_ms=15000):
        """select_option by visible label; then wait until `wait_next` (a dependent <select>) has loaded options via JS."""
        self.page.select_option(selector, label=label)
        if wait_next:
            waited = 0
            while waited < timeout_ms and int(self.page.evaluate("s => (document.querySelector(s) || {options: []}).options.length", wait_next)) <= 1:
                self.page.wait_for_timeout(500); waited += 500
            if waited >= timeout_ms: raise BuildError("%s did not load options after choosing %s" % (wait_next, label))

    def need(self, *selectors, wait_ms=15000):
        """Every selector must exist. Polls up to wait_ms first: an interstitial that clears by itself reloads the page under us."""
        for s in selectors:
            waited = 0
            while self.page.locator(s).count() == 0:
                if waited >= wait_ms: raise BuildError("%s form changed: %s not found" % (self.site.name, s))
                self.page.wait_for_timeout(500); waited += 500


# ---- run ----------------------------------------------------------------------------------------------------------------
CAPTURE_RANK = {"listing": 4, "public-from-owner": 3, "owner": 2, "confirmation": 1}


def capture_listing(ctx, site):
    """t_3ac43137: after a live step, keep the best listing URL the page shows (permalink > public URL built from an owner id > owner view > confirmation URL)
    and any listing id in ctx.state['captured']; record_live saves it on the row. Reads the page URL and text only; never raises."""
    import listing_capture as LC
    try:
        try: text = ctx.page.inner_text("body", timeout=3000)
        except Exception: text = ""
        c = LC.capture(site.domain, ctx.page.url, text)
    except Exception:
        return None
    cur = ctx.state.get("captured") or {}
    if c["listing_url"] and CAPTURE_RANK.get(c["kind"], 0) > CAPTURE_RANK.get(cur.get("kind") or "", 0): cur = dict(cur, **c)
    elif c["listing_id"] and not cur.get("listing_id"): cur = dict(cur, listing_id=c["listing_id"])
    if cur: ctx.state["captured"] = cur
    return cur or None


def save_failure_evidence(ctx, site, step, error):
    import fail_evidence
    return fail_evidence.save(ctx, site, step, error)


def active(st, ctx):
    """False when a step is tagged for the other branch of the spec (has_account / new_account)."""
    w = getattr(st, "when", None)
    return w is None or (w == "has_account") == bool(ctx.has_account)


def open_step_for(site, ctx):
    """The step --only always runs first: the first active step that opens a page or signs in; a Python site falls back to the first step named open_*. None = the spec has none."""
    act = [st for st in site.steps if active(st, ctx)]
    return next((st for st in act if getattr(st, "opener", False)), None) or next((st for st in act if st.name.startswith("open")), None)


def run_site(site, ctx, only=None):
    """-> {site, mode, steps:[{name, kind, status, detail}], stopped_before}. Raises nothing for a failed step: it is recorded and the run stops there."""
    res = {"site": site.name, "mode": "dry-run" if ctx.dry_run else "live", "steps": [], "stopped_before": None, "ok": True}
    if not ctx.dry_run and site.mail and ctx.mailbox is not None:
        try: ctx.state["mail_base"] = ctx.mailbox.max_uid()
        except Exception as e: res["steps"].append({"name": "mail_baseline", "kind": "read", "status": "failed", "detail": str(e)[:200]}); res["ok"] = False; return res
    last_open = None
    steps = list(site.steps)
    if only:
        # t_03a74bae: --only never runs on a blank page. The spec's open / sign-in step runs first; a spec without one fails loudly, before any step.
        op = open_step_for(site, ctx)
        if op is None:
            res["steps"].append({"name": "only_needs_open", "kind": "read", "status": "failed", "detail": "--only needs an open step: spec %s has none (add a 'do: open' step)" % site.name}); res["ok"] = False; return res
        steps = [op] + [st for st in steps if st is not op and st.name in only]   # the opener first, even when the spec lists it later
    for st in steps:
        if not active(st, ctx):
            res["steps"].append({"name": st.name, "kind": st.kind, "status": "skipped", "detail": "other branch (%s)" % st.when}); continue
        if ctx.dry_run and st.kind in STOP_IN_DRY_RUN:
            res["stopped_before"] = st.name; break
        try:
            # Before every step: hold the lease and make sure the build Chrome still answers. If it died (batch 9 lost CDP 9333), restart it on the SAME
            # profile (logins kept), take a fresh page, and replay the last page-open step so this step has a page to work on.
            if ctx.lease is not None: ctx.lease.touch()
            if ctx.chrome_check is not None and ctx.chrome_check() == "restarted":
                if ctx.reconnect is None: raise BuildError("build Chrome had exited and was restarted, but this run cannot reconnect; rerun the build")
                swept = []
                if ctx.sweep is not None:
                    try: swept = ctx.sweep() or []
                    except Exception: swept = []
                ctx.page = ctx.reconnect()
                res["steps"].append({"name": "chrome_restart", "kind": "read", "status": "ok", "detail": "build Chrome had exited; restarted on the same profile" + ("; closed %d foreign tab(s)" % len(swept) if swept else "")})
                if last_open is not None: last_open.fn(ctx)
            detail = st.fn(ctx)
            if st.kind == "read": last_open = st
            if not ctx.dry_run: capture_listing(ctx, site)
            res["steps"].append({"name": st.name, "kind": st.kind, "status": "ok", "detail": PK.redact(str(detail)) if detail is not None else ""})
        except Exception as e:
            ev = save_failure_evidence(ctx, site, st, e)   # t_03a74bae: BEFORE the caller closes the context
            res["steps"].append({"name": st.name, "kind": st.kind, "status": "failed", "detail": PK.redact(str(e))[:300], **({"evidence": ev} if ev else {})}); res["ok"] = False; break
    return res


def format_result(res):
    lines = ["%s [%s]" % (res["site"], res["mode"])]
    for s in res["steps"]:
        lines.append("  %-7s %-22s %-7s %s" % (s["kind"], s["name"], s["status"], s["detail"][:110]))
        if s.get("evidence"): lines.append("          failure evidence: %s | %s | url %s" % (s["evidence"].get("screenshot", "no screenshot"), s["evidence"].get("json", "no json"), s["evidence"].get("url")))
    if res["stopped_before"]: lines.append("  -- dry run stopped BEFORE step '%s' (nothing was submitted)" % res["stopped_before"])
    if any(W.is_block_text(s["detail"]) for s in res["steps"] if s["status"] == "failed"):
        ray = next((W.parse_ray_id(s["detail"]) for s in res["steps"] if s["status"] == "failed" and W.parse_ray_id(s["detail"])), None)
        lines.append("  HARD BLOCK: log the try with: python job/walls.py --record-try <row id>%s" % (" --ray-id " + ray if ray else ""))
    lines.append("  result: %s" % ("ok" if res["ok"] else "FAILED"))
    return "\n".join(lines)


def all_sites(spec_dir=None):
    """Python site modules plus every job/playbooks/<site>.json spec (t_d7a907d5)."""
    import formspec
    return sorted(set(SITES) | set(formspec.list_specs(spec_dir)))


def load_site(name, spec_dir=None):
    """A registered Python module wins; otherwise job/playbooks/<name>.json is built into the same Site/Step shape (formspec.py)."""
    if name in SITES: return importlib.import_module(SITES[name]).SITE
    import formspec
    if formspec.has_spec(name, spec_dir): return formspec.load_site(name, spec_dir)
    raise BuildError("unknown site %r; known: %s" % (name, ", ".join(all_sites(spec_dir))))


def connect(cdp, fresh=False):
    """-> (playwright, page, closer). fresh=True (dry runs): an isolated context with no cookies, so a signed-in build profile does not redirect /register
    and nothing from the dry run lands in the persistent profile. Live runs use the persistent context (logins survive between batches)."""
    from playwright.sync_api import sync_playwright
    import chrome_keepalive as KA
    port = int(cdp.rsplit(":", 1)[-1].strip("/") or KA.PORT)
    if port == KA.PORT:
        try: KA.ensure_up(port)   # same persistent build profile, logins kept
        except RuntimeError as e: raise BuildError(str(e)) from e
    p = sync_playwright().start()
    try:
        b = p.chromium.connect_over_cdp(cdp)
    except Exception as e:
        p.stop(); raise BuildError("build Chrome not reachable on %s (python job/build_chrome.py)" % cdp) from e
    if fresh:
        c = b.new_context()
        return p, c.new_page(), c.close
    pg = b.contexts[0].new_page()
    return p, pg, pg.close


def wall_gate(site, queue_path=None, today=None):
    """Hard-block cap (t_fccbb7ef): a log line when any queue row for this Directory is STOPPED or already had its one try today; else None.
    Runs before the build Chrome is touched. A missing/unreadable queue file means no known wall (the runner never writes the queue)."""
    import buildqueue as Q
    path = queue_path or Q.QUEUE_PATH
    try:
        with open(path, encoding="utf-8") as f: q = json.load(f)
    except (OSError, ValueError):
        return None
    return W.gate(q, site.domain, today)


def _brand(domain):
    """'www.acompio.us' -> 'acompio'; 'accounts.yellowpages.com' -> 'yellowpages'. The label left of the TLD (country-code second levels co/com/org skipped)."""
    p = [x for x in (domain or "").lower().split(".") if x and x != "www"]
    if len(p) >= 3 and len(p[-1]) == 2 and p[-2] in ("co", "com", "org", "net", "gov", "edu", "ac"): return p[-3]
    return p[-2] if len(p) >= 2 else (p[0] if p else "")


def same_directory(row_dir, site_domain):
    """A queue row's directory and a spec's domain name the same Directory: equal, or the same brand on a different TLD (row acompio.us, spec acompio.com;
    row tupalo.com, spec tupalo.co). t_3ac43137"""
    return row_dir == site_domain or (bool(_brand(row_dir)) and _brand(row_dir) == _brand(site_domain))


def find_row(row_id, site, queue_path=None):
    """The queue row a live run builds. Refuses before any browser starts: unknown row, or a row for a different Directory than the site."""
    import buildqueue as Q
    try: rows = Q.load_all_rows(queue_path)   # fix_queue + create_rows + create_queue.rows (t_3ac43137)
    except (OSError, ValueError, Q.QueueError) as e: raise SystemExit("--row: cannot read the queue (%s)" % str(e)[:80])
    hit = [r for r in rows if r["id"] == row_id]
    if not hit: raise SystemExit("--row %s is not in the queue" % row_id)
    if not same_directory(hit[0]["directory"], site.domain): raise SystemExit("--row %s is for %s, not %s" % (row_id, hit[0]["directory"], site.domain))
    return hit[0]


def is_full_run(site, res, only=None):
    """True only when NO --only filter was used and every spec step ran with status ok. A subset or discovery run sent no listing and never records."""
    if only: return False
    done = [x for x in res["steps"] if x["name"] != "chrome_restart"]
    return bool(res["ok"]) and len(done) == len(site.steps) and all(x["status"] in ("ok", "skipped") for x in done) and any(x["status"] == "ok" for x in done)


def record_live(row, site, record=None, captured=None):
    """After an ok live run: record `submitted` through buildqueue.submit_row(live=True) -> transitions.record_transition. Returns one log line, never raises:
    a refusal (no Mike approval, paid row, no vault item) is printed, and nothing is recorded."""
    import buildqueue as Q
    to = getattr(site, "record", "submitted")
    days = getattr(site, "recheck_due_days", None)
    if days:   # t_6b1e01ff: an edit spec (foursquare) leaves the row's state alone and sets the day recheck may read it again
        import datetime, transitions
        due = (datetime.date.today() + datetime.timedelta(days=int(days))).isoformat()
        try: out = (record or transitions.record_transition)("SCC", row["id"], row["state"], None, "edit sent via %s spec; recheck due %s" % (site.name, due), recheck_due=due)
        except Exception as e: return "NOT recorded (recheck_due failed: %s). Set it with transitions.py." % PK.redact(str(e))[:120]
        return "recheck due %s set on %s (state stays %s)" % (due, row["id"], row["state"])
    if to == "none":
        return "not recorded: this spec stops at a verify step (record none). Set the state with transitions.py (needs-human + verify_type)."
    row = dict(row); row.setdefault("vaultwarden_item", site.vault_item)
    try:
        res = Q.submit_row(row, lambda item: {"checked": "vault_fill used it in this run"}, record=record, live=True, to=to,
                         captured_url=(captured or {}).get("listing_url"), captured_id=(captured or {}).get("listing_id"))
    except Q.SubmitRefused as e:
        return "NOT recorded (submit_row refused: %s). Record it with transitions.py." % e
    except Exception as e:
        return "NOT recorded (recording failed: %s). Record it with transitions.py." % PK.redact(str(e))[:120]
    return "recorded: %s -> %s (%s)" % (res["id"], to, str(res.get("recorded"))[:120])


def check_mail_only(site):
    """t_03a74bae: discoverourtown and loc8nearme have no account and no vault item; their status arrives by mail only (mail_scan.py). A spec that signs in
    or reads a vault item for one of them is refused before any browser starts. Returns a refusal text or None."""
    import buildqueue as Q
    if getattr(site, "uses_account", False) and Q.is_mail_only(site.domain): return "%s refused: %s is a mail-only Directory (no account, no vault item). Its status path is `python job/mail_scan.py`." % (site.name, site.domain)
    return None


def check_guard(site, row_id=None, flags=()):
    """t_6b1e01ff: a spec may carry guard {refuse_rows, flag, reason}. A row in refuse_rows is refused outright; without the spec's --<flag> the spec is refused
    (showmelocal_claim is for a NEW listing only: the SCC listing is claimed now, and create-showmelocal must never run it). Returns a refusal text or None."""
    g = getattr(site, "guard", None)
    if not g: return None
    if row_id and row_id in (g.get("refuse_rows") or []): return "%s refused for row %s: %s" % (site.name, row_id, g["reason"])
    if g["flag"] not in flags: return "%s refused: %s Pass --%s only for a new listing." % (site.name, g["reason"], g["flag"])
    return None


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="Scripted listing build (build Chrome, CDP 9333)")
    a.add_argument("site", help="a registered site or a job/playbooks/<site>.json spec; known: " + ", ".join(all_sites()))
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="read and fill only; stop before the first submit/mail step")
    g.add_argument("--live", action="store_true", help="create the listing; needs --card and --row")
    a.add_argument("--row", default=None, help="the queue row id this live run builds (e.g. create-storeboard); a successful run records `submitted` for it")
    a.add_argument("--card", default=None, help="the Nate card that authorizes a live build")
    a.add_argument("--cdp", default=CDP_URL)
    a.add_argument("--item-id", default=None, help="Vaultwarden item id (when two items share the name)")
    a.add_argument("--item-name", default=None, help="Vaultwarden item NAME as printed by `python job/vault_item.py --domain <domain>` (overrides the spec's vault_item)")
    a.add_argument("--ignore-due", action="store_true", help="work a row whose recheck_due is still in the future")
    a.add_argument("--only", default=None, help="comma list of step names (the spec's open / sign-in step always runs first)")
    a.add_argument("--has-account", action="store_true", help="the Directory account already exists: steps tagged when has_account run (login), when new_account do not (signup + mail)")
    a.add_argument("--new-listing", action="store_true", help="the Directory has no listing for us yet (needed by specs guarded for new listings only, e.g. showmelocal_claim)")
    n = a.parse_args(argv)
    if n.live and not n.card: raise SystemExit("--live is refused without --card <id> (a Directory account is written)")
    site = load_site(n.site)
    refused = check_guard(site, n.row, ("new-listing",) if n.new_listing else ())
    if refused: raise SystemExit(refused)   # before any browser starts
    row = None
    if n.live:
        if not n.row: raise SystemExit("--live needs --row <queue row id> (the transition is recorded for that row)")
        row = find_row(n.row, site)
        import buildqueue as Q
        due = Q.not_due(row)
        if due and not n.ignore_due: print("SKIP %s: recheck_due %s (retry later; --ignore-due to work it anyway)" % (n.row, due)); return 0   # t_d2f75685: before any browser
    mo = check_mail_only(site)
    if mo: raise SystemExit(mo)
    skip = wall_gate(site)
    if skip:
        print(skip); return 0   # hard-block cap: no Chrome, no Directory touched
    from cfg import IDENT
    nap = nap_from_identity(IDENT)
    mailbox = None
    if site.mail and n.live:
        mailbox = make_mailbox(site.mail["sender"], site.mail["link_re"])
    import chrome_keepalive as KA
    lease = KA.Lease(n.card or "dry-run:" + n.site)   # the --seconds timer in build_chrome.py does not fire while this is fresh
    lease.touch()
    pw, page, close = connect(n.cdp, fresh=not n.live)
    try:
        ctx = Ctx(site, page, nap, mailbox=mailbox, item_id=n.item_id, cdp=n.cdp, dry_run=not n.live)
        ctx.row_id = n.row
        ctx.has_account = n.has_account
        ctx.item_name = n.item_name
        ctx.lease = lease
        if int(n.cdp.rsplit(":", 1)[-1].strip("/") or 0) == KA.PORT:
            ctx.chrome_check = lambda: KA.ensure_up(KA.PORT)
            def _reconnect():
                nonlocal pw, close
                try: pw.stop()
                except Exception: pass
                pw, pg2, close = connect(n.cdp, fresh=not n.live)
                return pg2
            ctx.reconnect = _reconnect
            ctx.sweep = lambda: KA.sweep_foreign_tabs(KA.PORT)
        only = set(n.only.split(",")) if n.only else None
        res = run_site(site, ctx, only)
    finally:
        lease.__exit__()
        try: close()
        except Exception: pass
        pw.stop()
    print(format_result(res))
    if n.live and res["ok"]:
        if is_full_run(site, res, only): print("  " + record_live(row, site, captured=ctx.state.get("captured")))
        else: print("  NOT recorded (partial run: --only or a discovery run sends no listing, so it never records). Run the full spec to record.")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
