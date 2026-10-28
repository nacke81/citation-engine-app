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
check('Cylex code entry is distinct from an unproven submit and server confirmation', names.index('code_entry_only') < names.index('submit_code_UNPROVEN') < names.index('require_server_confirmation_UNPROVEN') and cylex['record'] == 'none')
class BodyPage:
    url = 'https://www.cylex.us.com/'
    def __init__(self, body): self.body = body
    def inner_text(self, selector): return self.body
class StatusCtx:
    def __init__(self, body): self.page = BodyPage(body)
read = F._v_read_text(cs[names.index('require_server_confirmation_UNPROVEN')])
try: read(StatusCtx('Code entered')); mistaken = True
except Exception: mistaken = False
check('typed code alone cannot certify account', not mistaken)
check('explicit response after submit can satisfy confirmation stage', 'account verified' in read(StatusCtx('Account verified')).lower())
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
