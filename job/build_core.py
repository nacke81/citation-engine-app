"""Types shared by build_runner.py and the per-site modules (t_560dd259). Kept separate so a site module never imports the runner (which may be __main__)."""

KINDS = ("read", "fill", "mail", "submit")


class BuildError(Exception):
    pass


class Step:
    """kind: read (loads/reads only) | fill (types into forms, sends nothing) | mail (reads listings@, opens the link) | submit (writes to the Directory)."""
    def __init__(self, name, kind, fn, when=None, opener=False):
        if kind not in KINDS: raise ValueError("step kind %r" % kind)
        self.name, self.kind, self.fn = name, kind, fn
        self.when = when        # t_03a74bae: None | "has_account" | "new_account": the step runs only on that branch of the spec
        self.opener = opener    # t_03a74bae: the page-open / sign-in step `--only` always runs first


class Site:
    def __init__(self, name, domain, steps, vault_item=None, mail=None):
        self.name, self.domain, self.steps, self.vault_item = name, domain, steps, vault_item or "SCC - %s" % domain
        self.record = "submitted"
        self.recheck_due_days = None   # t_6b1e01ff
        self.guard = None              # t_6b1e01ff
        self.uses_account = False   # t_03a74bae: a login / vault_fill step exists (a mail-only Directory must never run such a spec)
        self.mail = mail   # {"sender": "freelistingusa", "link_re": r"https://..."} or None
