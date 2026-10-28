"""Batch 22 regressions: no browser, network, secrets, Directory writes or production queue."""
import copy, io, json, os, sys, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
JOB = os.path.join(HERE, '..', 'job')
os.environ['CE_IDENTITY'] = os.path.join(HERE, 'test_identity.json')
sys.path.insert(0, JOB)
import mail_scan as M, workable as W, recheck as R, formspec as F

ok = []
def check(name, value):
    ok.append(bool(value))
    print(('PASS ' if value else 'FAIL ') + name)

message = {'from': 'Cylex <noreply@cylex.us.com>', 'folder': 'Junk', 'date': '2026-10-28T01:00',
           'subject': 'Your verification code 654321', 'body': 'Code 654321', 'to': ['listing@example.org'], 'uid': 2}
check('cylex.us and cylex.us.com alias match actual sender without printing code', M.presence('cylex.us', [message])[0] == 1 and M.presence('cylex.us.com', [message])[0] == 1)
out = []
M.headers_main(['cylex.us'], 30, messages=[message], out=out.append)
check('header-only mode masks code', '654321' not in '\n'.join(out) and '@cylex.us.com' in '\n'.join(out))
rows = [dict(id='create-cylex', directory='cylex.us', state='needs-human', recheck_due='2026-10-30'),
        dict(id='create-bbb', directory='bbb.org', state='submitted', recheck_due='2026-10-30'),
        dict(id='fix-bing', directory='bing.com', state='submitted')]
selected, skipped = M.select_rows(rows, {'cylex.us'}, '2026-10-28', historical=True)
check('historical selects named directory despite future due; default skips it', [r['id'] for r in selected] == ['create-cylex'] and skipped == 0 and M.select_rows(rows, {'cylex.us'}, '2026-10-28')[0] == [])
check('historical never selects another directory', all(r['directory'] == 'cylex.us' for r in selected))
original = M.Q.load_all_rows; read = M.read_messages
M.Q.load_all_rows = lambda _: rows
M.read_messages = lambda **kw: [message] if kw['folders'] == 'all' else []
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = M.main(['--historical','--directory','cylex.us','--queue','fixture','--days','30'])
M.Q.load_all_rows, M.read_messages = original, read
check('historical CLI reports selected/skipped/unread; reads all folders only', rc == 0 and 'selected=1 skipped=0 unread=0' in buf.getvalue() and '654321' not in buf.getvalue())

# No-URL backoff is explicitly scoped through the existing --row / only path.
import tempfile, pathlib, transitions as T
with tempfile.TemporaryDirectory() as temp:
    path = pathlib.Path(temp) / 'queue.json'
    base = {'canonical': {'name':'Alder Care', 'address':'100 Example Dr, Example KY 40000', 'phone':'(502) 555-0101'},
            'fix_queue': [dict(id='fix-bing', directory='bing.com', state='submitted', history=[])],
            'create_rows': [dict(id='create-discoverourtown', directory='discoverourtown.com', state='submitted', history=[]),
                            dict(id='create-dnb', directory='dnb.com', state='found', history=[])]}
    path.write_text(json.dumps(base), encoding='utf-8')
    def record(*args, **kwargs):
        return T.record_transition(*args, portal=type('Portal', (), {'latest_snapshot':lambda self, cid: {'payload':{'directories':[], 'totals':{}}}, 'upsert_snapshot':lambda *a: None, 'call':lambda *a: None})(), **kwargs)
    class DB:
        owner = 'fixture'
        def call(self, *args, **kwargs): return []
    identity = json.load(open(os.path.join(HERE, 'test_identity.json'), encoding='utf-8'))
    old = copy.deepcopy(base['fix_queue'])
    R.recheck(base, identity, plain=lambda u: R.Page(404, u, '', html=''), chrome=None, record=record, db=DB(), queue_path=str(path), today='2026-10-28', use_chrome=False,
              backoff_only=True, only={'create-discoverourtown', 'create-dnb'})
    after = json.loads(path.read_text(encoding='utf-8'))
    check('scoped backoff touches discoverourtown/dnb only, fix-bing byte-equivalent', after['fix_queue'] == old and all(r['recheck_due'] == '2026-10-30' for r in after['create_rows']))
    check('backoff history stays structured and one period per row', all(T.no_url_backoffs(r) == 1 for r in after['create_rows']))

cylex = json.load(open(os.path.join(JOB, 'playbooks', 'cylex.json'), encoding='utf-8'))
city = json.load(open(os.path.join(JOB, 'playbooks', 'citylocalpro_resend.json'), encoding='utf-8'))
for spec in (cylex, city): F.build_site(spec)
cs = cylex['steps']; names = [x.get('name') for x in cs]
check('Cylex code entry precedes executable stop; no unobserved selector or success marker compiles',
      names.index('code_entry_only') < names.index('inspect_code_page') < names.index('stop_before_unobserved_code_submit')
      and cs[-1]['do'] == 'stop_unproven' and cylex['record'] == 'none'
      and not any(x.get('do') in ('click', 'read_text') for x in cs[names.index('inspect_code_page') + 1:]))
import build_runner as B, build_core as C, types
compiled = F.build_site(cylex)
# Compiled terminal step and real runner; a no-network opener avoids signup.
terminal = compiled.steps[-1]
fixture_site = C.Site('cylex-fixture', 'cylex.us',
                      [C.Step('open_register', 'read', lambda ctx: 'fixture page', opener=True), terminal])
fixture_site.record = 'none'
class StopCtx:
    dry_run = False
    mailbox = None
    lease = chrome_check = None
    has_account = False
    state = {}
    page = types.SimpleNamespace(url='https://www.cylex.us.com/', inner_text=lambda *a, **k: '')
    log = staticmethod(lambda *args: None)
old_evidence = B.save_failure_evidence
B.save_failure_evidence = lambda *args: None
try:
    full = B.run_site(fixture_site, StopCtx())
    only_stop = B.run_site(fixture_site, StopCtx(), only={'stop_before_unobserved_code_submit'})
    only_legacy = B.run_site(fixture_site, StopCtx(), only={'submit_code_UNPROVEN', 'require_server_confirmation_UNPROVEN'})
finally: B.save_failure_evidence = old_evidence
check('compiled live runner fails closed before unobserved submit, never clicks',
      not full['ok'] and full['steps'][-1]['name'] == terminal.name and full['steps'][-1]['status'] == 'failed'
      and 'stop before code submit' in full['steps'][-1]['detail'])
check('--only terminal cannot bypass stop; legacy --only names fail before opener',
      not only_stop['ok'] and not only_legacy['ok'] and [x['name'] for x in only_legacy['steps']] == ['only_unknown_step'])
check('typed code is not server-confirmed; no executable account success assertion exists',
      cs[names.index('code_entry_only')]['do'] == 'wait_mail'
      and not any(x.get('do') == 'read_text' for x in cs[names.index('code_entry_only') + 1:]))
malformed = copy.deepcopy(cylex)
malformed['steps'].append({'name': 'unsafe_after_stop', 'do': 'click', 'selector': 'button', 'submit': True})
try: F.build_site(malformed); stop_terminal = False
except C.BuildError: stop_terminal = True
check('stop_unproven cannot be followed by an executable submit', stop_terminal)
ss = city['steps']; snames = [x.get('name') for x in ss]
check('Citylocalpro dry-run stop is before BOTH login and resend mutations', snames.index(None) < snames.index('login_attempt') < snames.index('resend_once') and ss[0]['expect'] == ['input[name=login]'] and ss[snames.index('login_attempt')]['selector'] == '#loginBtn')
check('resend result preserves limit-first sent unknown classification', list(ss[-1]['classes']) == ['limit','sent'] and ss[-1]['new_only'] and ss[-1]['do'] == 'read_result')

q = json.load(open(os.path.join(HERE, 'fixtures', 'workable_queue.json'), encoding='utf-8'))
cy = next(x for x in q['create_queue']['rows'] if x['id'] == 'create-cylex')
cy['history'].append({'at': '2026-10-28', 'note': 'Account code typed, NOT submitted; browser-field-not-rendered; 2 solves used'})
res = W.classify(q, '2026-10-28')
work = {x['row']: x for x in res['workable']}
check('cylex continues at unverified code stage, not a third hard-block day', 'code' in work['create-cylex']['why'] and 'hard-block retry' not in work['create-cylex']['why'])
check('two prior wall days persist', len(W.W.tries(cy)) == 2)
for rowid, price in [('create-botw', '$28/mo'), ('create-showmelocal', '$6.99')]:
    row = next(x for x in q['create_queue']['rows'] if x['id'] == rowid)
    row['history'].append({'at': '2026-10-28', 'note': 'paid tier ' + price + ' shown; no purchase'})
res = W.classify(q, '2026-10-28')
human = {x['row']: x['why'] for x in res['needs_human']}
check('latest botw/showmelocal price gates beat historical reasons', '$28/mo' in human['create-botw'] and '$6.99' in human['create-showmelocal'])

print('%d/%d passed' % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
