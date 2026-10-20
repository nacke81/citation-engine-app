"""Weekly claim fetch and queue-note regressions. Scrubbed identity, no network."""
import ast
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
os.environ["CE_IDENTITY"] = str(HERE / "test_identity.json")
sys.path.insert(0, str(HERE.parent / "job"))
# run.py creates its local artifact directories on import. Keep those inside this test.
TEMP = tempfile.TemporaryDirectory(prefix="weekly-claim-", dir=HERE)
os.environ["CE_RUNS"] = TEMP.name
os.environ["CE_ROWS"] = str(Path(TEMP.name) / "rows.jsonl")
import run as R
import claim as C
import core

ok = []
def check(name, cond):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name, flush=True)

D = "superpages.com"
SEARCH = "https://www.superpages.com/search?search_terms=alder"
RECORD = "https://www.superpages.com/exampleton-ky/bpp/alder-care-123456789"
TEXT = C.html_to_text((HERE / "fixtures/claim/superpages-unclaimed.html").read_text(encoding="utf-8"))
NAME = R.IDENT["BIZ"]["SCC"]["name"]
ROW = dict(kind="dir", biz="SCC", dir=D, method="chrome-ownbox", status="found", url=SEARCH,
           ev=dict(name=True, street=True, city=True, phones=["5025550101"]))
LINKS = {SEARCH: [dict(href=RECORD, text=NAME)]}

class Fetcher:
    def __init__(self, status=200, text=TEXT, err=None, redirect=None, raises=False):
        self.calls = []
        self.status, self.text, self.err = status, text, err
        self.redirect, self.raises = redirect, raises
    def fetch(self, url, label=""):
        self.calls.append(url)
        if self.raises:
            raise OSError("fixture fetch failure")
        return core.Result(self.status, self.redirect or url, self.text, [], self.err)

def exercise(fetcher, rows=None, texts=None, links=None):
    rows = rows if rows is not None else [copy.deepcopy(ROW)]
    texts = texts if texts is not None else {SEARCH: "Alder Care\nSearch results"}
    links = links if links is not None else copy.deepcopy(LINKS)
    R.read_claim_pages(rows, texts, links, fetcher)
    _, checks = R.build(rows, texts, links)
    return next(c for c in checks if c["biz"] == "SCC" and c["directory"] == D), texts

f = Fetcher()
c, texts = exercise(f)
check("weekly resolves and fetches search match's record exactly once", f.calls == [RECORD])
check("weekly build detects the fetched record marker", c["_claim"]["claim_status"] == "unclaimed")
check("weekly evidence names the record, not the search page", c["_claim"]["claim_evidence"]["url"] == RECORD)
check("weekly NAP evidence still comes from matched search page", c["_page"] == SEARCH and c["url"] == RECORD and c["match"] is True)
for name, f in [("403 with marker body", Fetcher(status=403)), ("500 with marker body", Fetcher(status=500)),
                ("network failure", Fetcher(status=None, text="", err="network")),
                ("fetch exception", Fetcher(raises=True)), ("empty 200", Fetcher(text="")),
                ("redirect to search", Fetcher(redirect=SEARCH)),
                ("redirect to another record", Fetcher(redirect=RECORD.replace("123456789", "123456780")))]:
    c, _ = exercise(f)
    check(name + " -> unknown without evidence", c["_claim"] == {"claim_status": "unknown", "claim_evidence": None} and f.calls == [RECORD])
# A wrapped discovery fetcher caches every response, including failed redirects.
for status in (200, 403):
    cached_texts = {SEARCH: "original search NAP"}
    cached_links = copy.deepcopy(LINKS)
    class CachingFetcher(Fetcher):
        def fetch(self, url, label=""):
            r = super().fetch(url, label)
            cached_texts[r.url] = r.text
            cached_links[r.url] = [{"href": "unrelated"}]
            return r
    f = CachingFetcher(status=status, redirect=SEARCH)
    c, _ = exercise(f, texts=cached_texts, links=cached_links)
    check("wrapped %s redirect preserves original search text and links" % status,
          cached_texts[SEARCH] == "original search NAP" and cached_links[SEARCH] == LINKS[SEARCH]
          and c["_claim"]["claim_status"] == "unknown")

f = Fetcher(redirect=RECORD + "?tracking=1#top")
c, _ = exercise(f)
check("harmless query/fragment redirect keeps record marker", c["_claim"]["claim_status"] == "unclaimed")
f = Fetcher()
exercise(f, texts={SEARCH: "search", RECORD: TEXT})
check("already-read record is not fetched again", not f.calls)
f = Fetcher()
exercise(f, texts={SEARCH: "search", RECORD + "?x=1#top": TEXT})
check("already-read record URL variant is not fetched again", not f.calls)
f = Fetcher()
exercise(f, rows=[{**ROW, "url": RECORD}], texts={RECORD: TEXT})
check("matched page already the record -> no extra fetch", not f.calls)
f = Fetcher()
exercise(f, links={})
check("no resolved record -> no fetch", not f.calls)
f = Fetcher()
rows = [dict(ROW), {**ROW, "biz": "NM"}, {**ROW, "biz": "FAKE"}]
with patch.object(R, "IDENT", {**R.IDENT, "BIZ": {**R.IDENT["BIZ"], "NM": R.IDENT["BIZ"]["SCC"]}}):
    exercise(f, rows=rows)
check("shared record across businesses fetched once; FAKE skipped", f.calls == [RECORD])
f = Fetcher(status=403)
with patch.object(R, "IDENT", {**R.IDENT, "BIZ": {**R.IDENT["BIZ"], "NM": R.IDENT["BIZ"]["SCC"]}}):
    exercise(f, rows=rows)
check("failed shared record attempted once, not retried", f.calls == [RECORD])
f = Fetcher()
exercise(f, rows=[{**ROW, "dir": "dexknows.com", "url": SEARCH.replace("superpages", "dexknows")}])
check("unverified Directory has no extra read", not f.calls)
f = Fetcher()
exercise(f, rows=[{**ROW, "status": "couldnt"}])
check("not-found result has no extra read", not f.calls)
_, checks = R.build([ROW], {SEARCH: "search"}, LINKS)
check("offline build stays unknown and does not fetch", next(c for c in checks if c["biz"] == "SCC" and c["directory"] == D)["_claim"]["claim_status"] == "unknown")

# Run the actual discover_all function with its external browser/search work replaced.
# AST extraction avoids importing Playwright in CI. Its hook and context lifetime are real code.
source = ast.parse((HERE.parent / "job/discover.py").read_text(encoding="utf-8"))
function = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "discover_all")
active = []
class Context:
    def __enter__(self):
        active.append(self)
        return self
    def __exit__(self, *args):
        active.remove(self)
    profile = "fixture-profile"
    cdp_url = "fixture-cdp"
    contexts = [None]
    def connect_over_cdp(self, url):
        return self
    @property
    def chromium(self):
        return self
class LiveFetcher(Fetcher):
    block = "blocked-from-prior-loop"
    def fetch(self, url, label=""):
        assert len(active) == 2, "claim fetched after browser cleanup"
        assert self.block is None, "claim read inherited deliberate block"
        return super().fetch(url, label)

f = LiveFetcher()
globals_ = dict(os=os, OUT=os.environ["CE_ROWS"], HERE=str(HERE), NullRec=lambda: None,
                HttpFetcher=Fetcher, ChromeFetcher=lambda *a, **kw: f, BIZS=[],
                OwnedChrome=Context, sync_playwright=Context,
                ladder=lambda *a: None, IDENT={"HARDNEG": []}, DIRS=[])
exec(compile(ast.Module(body=[function], type_ignores=[]), "discover.py", "exec"), globals_)
def discovered(on_chrome, on_complete):
    def complete(fetcher):
        Path(os.environ["CE_ROWS"]).write_text(json.dumps(ROW) + "\n", encoding="utf-8")
        on_complete(fetcher)
    globals_["discover_all"](on_chrome, complete)

fake_discover = SimpleNamespace(discover_all=discovered, own_search_box=lambda: None, mapnap=SimpleNamespace(lookup=lambda: {}))
fake_owned = SimpleNamespace(chrome_windows=lambda: [], window_count=lambda: 0)
with patch.dict(sys.modules, discover=fake_discover, owned_chrome=fake_owned), \
     patch.object(core, "HttpFetcher", Fetcher), patch.object(core, "ChromeFetcher", LiveFetcher), \
     patch.object(R, "chrome_procs_with", return_value=[]), patch.object(R.time, "sleep"), \
     patch.object(R, "read_claim_pages", wraps=R.read_claim_pages) as read, \
     patch.object(R, "load_rows", return_value=[ROW]), \
     patch.object(R, "build", wraps=R.build):
    # Supply the captured search links as discovery would, without doing any real searches.
    real_read = R.read_claim_pages._mock_wraps
    def read_with_links(rows, texts, links, fetcher):
        links.update(copy.deepcopy(LINKS))
        real_read(rows, texts, links, fetcher)
    read.side_effect = read_with_links
    wc, captured, links = R.discover_live()
check("discover_live invokes actual discovery completion hook inside live context", read.call_count == 1 and f.calls == [RECORD] and not active)
check("discovery cleanup/window evidence stays valid", wc["error"] is None and wc["equal"] and wc["owned_alive_after"] == [])
_, checks = R.build([ROW], captured, links)
check("main's post-discovery build sees newly fetched record text", next(c for c in checks if c["biz"] == "SCC" and c["directory"] == D)["_claim"]["claim_status"] == "unclaimed")

NOTE = "Thryv family record; one fix may cover YP, Superpages, DexKnows"
for d in ("yellowpages.com", "superpages.com"):
    row = dict(directory=d, fix_method=NOTE, login="old", fix_note="Existing hand note", state="submitted", mike_approval={"approved_by": "mike"})
    before = copy.deepcopy(row)
    update = {"claim_status": "unclaimed", "claim_evidence": {"text": "marker"}}
    after = C.apply_to_queue_row(row, update)
    check(d + " preserves hand method alongside existing fix_note", after["fix_note"] == "Existing hand note\n" + NOTE and after["fix_method"] == "claim")
    check(d + " keeps state/approval and input unchanged", after["state"] == row["state"] and after["mike_approval"] == row["mike_approval"] and row == before)
    check(d + " repeated application does not duplicate note", C.apply_to_queue_row(after, update) == after)
    check(d + " unknown leaves hand method/note alone", C.apply_to_queue_row(row, {"claim_status": "unknown"})["fix_note"] == row["fix_note"])
row = C.apply_to_queue_row({"fix_method": NOTE}, {"claim_status": "unclaimed"})
check("missing fix_note initialized with original hand method", row["fix_note"] == NOTE)
check("existing identical note is not duplicated", C.apply_to_queue_row({"fix_method": NOTE, "fix_note": NOTE}, {"claim_status": "unclaimed"})["fix_note"] == NOTE)
check("plain claim method produces no spurious fix_note", "fix_note" not in C.apply_to_queue_row({"fix_method": "claim"}, {"claim_status": "unclaimed"}))

TEMP.cleanup()
print("\n%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
