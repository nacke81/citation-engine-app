"""t_79c39f75 sign-in Send: stub node runner only. No vault, network, portal, secrets or Directory."""
import io, json, os, sys, types, contextlib, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'job'))
os.environ['CE_IDENTITY'] = os.path.join(HERE, 'test_identity.json')
import signin_send as S

ok = []
def check(name, value):
    ok.append(bool(value)); print(('PASS ' if value else 'FAIL ') + name)

SECRET = 'hunter2-SECRET-pw'
URL = 'https://bitwardenrs.mikenacke.com/#/send/abc/KEYMATERIAL123'
ENV = {'BW_CLIENTID': 'x', 'BW_CLIENTSECRET': 'y', 'BW_PASSWORD': 'z'}
EXP = '2026-11-06T12:00:00.000Z'

calls = []
def runner_ok(cmd, **kw):
    calls.append(cmd)
    return types.SimpleNamespace(returncode=0, stdout=json.dumps({'url': URL, 'expires_at': EXP}) + '\n', stderr='')
def runner_missing(cmd, **kw):
    calls.append(cmd)
    return types.SimpleNamespace(returncode=3, stdout='', stderr='send=failed reason=item-missing')
def runner_boom(cmd, **kw):
    calls.append(cmd); raise OSError(SECRET)

# poison the network: nothing here may open a URL
urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network call'))

logs = []
def L(m): logs.append(m)

# happy path
r = S.make_signin_send('SCC', 'nextdoor.com', 'document-upload', runner=runner_ok, env=ENV, log=L)
check('document-upload gets url + expiry', r == {'signin_send_url': URL, 'signin_send_expires_at': EXP})
check('node was asked for the one directory', calls and calls[-1][calls[-1].index('--directory') + 1] == 'nextdoor.com')
check('id-check also gets a Send', S.make_signin_send('SCC', 'nextdoor.com', 'id-check', runner=runner_ok, env=ENV, log=L) is not None)
check('success logs nothing', logs == [])

# phone / sms / postcard / client-email: no Send, vault never called
calls.clear()
for vt in ('phone-call', 'sms', 'postcard', 'client-email', None):
    check('%s row: no Send' % vt, S.make_signin_send('SCC', 'nextdoor.com', vt, runner=runner_ok, env=ENV, log=L) is None)
check('phone/sms rows never reach the vault', calls == [])

# missing item -> None, one log line, no write
logs.clear(); calls.clear()
tbl = S.StubTable()
st = S.issue('SCC', 'nextdoor.com', 'id-check', write=True, table=tbl, runner=runner_missing, env=ENV, log=L, flag='1')
check('missing item: no-send', st == 'no-send')
check('missing item: no row write', [c for c in tbl.calls if c[0] != 'GET'] == [])
check('missing item: exactly one log line', len(logs) == 1 and 'missing' in logs[0])

# creds missing -> skip, vault not called
logs.clear(); calls.clear()
check('no creds: None, vault not called, one log line', S.make_signin_send('SCC', 'nextdoor.com', 'id-check', runner=runner_ok, env={}, log=L) is None and calls == [] and len(logs) == 1)

# vault command crash: fail closed, secret-bearing exception text never logged
logs.clear()
check('runner crash: None', S.make_signin_send('SCC', 'nextdoor.com', 'id-check', runner=runner_boom, env=ENV, log=L) is None)
check('runner crash: exception text not logged', SECRET not in ' '.join(logs) and len(logs) == 1)

# garbage stdout, non-https URL
for bad in ('', 'not json', json.dumps({'url': 'http://x', 'expires_at': EXP})):
    logs.clear()
    rn = lambda cmd, **kw: types.SimpleNamespace(returncode=0, stdout=bad, stderr='')
    check('bad vault output %r: None' % bad[:12], S.make_signin_send('SCC', 'nextdoor.com', 'id-check', runner=rn, env=ENV, log=L) is None)

# bad directory / non-SCC
check('bad directory refused', S.make_signin_send('SCC', 'x; rm -rf', 'id-check', runner=runner_ok, env=ENV, log=L) is None)
check('non-SCC refused', S.make_signin_send('NM', 'nextdoor.com', 'id-check', runner=runner_ok, env=ENV, log=L) is None)

# write is gated: flag off -> dry-run, no PATCH
tbl = S.StubTable()
st = S.issue('SCC', 'nextdoor.com', 'document-upload', write=True, table=tbl, runner=runner_ok, env=ENV, log=L, flag='0')
check('flag off: dry-run, no PATCH', st.startswith('dry-run') and tbl.calls == [])
tbl = S.StubTable()
st = S.issue('SCC', 'nextdoor.com', 'document-upload', write=False, table=tbl, runner=runner_ok, env=ENV, log=L, flag='1')
check('no --write: no PATCH', tbl.calls == [])
tbl = S.StubTable()
st = S.issue('SCC', 'nextdoor.com', 'document-upload', write=True, table=tbl, runner=runner_ok, env=ENV, log=L, flag='1')
pc = [c for c in tbl.calls if c[0] == 'PATCH']
check('write + flag: one PATCH of exactly the two columns', len(pc) == 1 and set(pc[0][2]) == {'signin_send_url', 'signin_send_expires_at'})
check('PATCH only touches a requires_verification row of this directory', 'directory=eq.nextdoor.com' in pc[0][1] and 'state=eq.requires_verification' in pc[0][1])
check('status string carries no URL or key', URL not in st and 'KEYMATERIAL' not in st)

# real dry run (no runner injected, flag off): no vault, no network
calls.clear()
check('real dry run makes no Send', S.issue('SCC', 'nextdoor.com', 'id-check', write=False, env=ENV, flag='0').startswith('dry-run'))

# reissue CLI: output never carries the URL; phone type is rejected by argparse
buf, err = io.StringIO(), io.StringIO()
real_make = S.make_signin_send
S.make_signin_send = lambda *a, **k: {'signin_send_url': URL, 'signin_send_expires_at': EXP}
S.StubTable.call = lambda self, *a, **k: None
os.environ.pop(S.FLAG, None)
with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
    rc = S.main(['--reissue', '--directory', 'nextdoor.com', '--verify-type', 'document-upload'])
S.make_signin_send = real_make
check('reissue CLI works and prints no URL/key', rc == 0 and URL not in buf.getvalue() + err.getvalue() and 'KEYMATERIAL' not in buf.getvalue() + err.getvalue())
try:
    with contextlib.redirect_stderr(io.StringIO()): S.main(['--reissue', '--directory', 'x.com', '--verify-type', 'phone-call'])
    check('reissue refuses phone-call', False)
except SystemExit as e:
    check('reissue refuses phone-call', e.code != 0)

# static scan: no portal seed / Directory action / password in argv / printing the secret
src = open(os.path.join(HERE, '..', 'job', 'signin_send.py'), encoding='utf-8').read()
js = open(os.path.join(HERE, '..', 'job', 'vault_send.cjs'), encoding='utf-8').read()
check('no portal seed / snapshot / directories call in module', not any(w in src for w in ('upsert_snapshot', 'footprint_snapshot', 'import directories')))
check('the Send body goes on stdin, not argv', "['send', 'create']" in js and 'base64' in js and 'password' not in "['send', 'create']")
check('module never prints url', 'print(url' not in src and 'print(fields' not in src)
check('Send settings in builder', all(s in js for s in ('maxAccessCount: 1', 'hidden: false', 'password: null', 'DAYS = 7')))

# (3) no matching row: no Send is minted, reissue says no-row (exit 1), nothing written
calls.clear(); logs.clear()
tbl = S.StubTable(rows=0)
st = S.issue('SCC', 'nextdoor.com', 'id-check', write=True, table=tbl, runner=runner_ok, env=ENV, log=L, flag='1')
check('no row: no-row, vault never called, no PATCH', st == 'no-row' and calls == [] and not [c for c in tbl.calls if c[0] == 'PATCH'])
class RowVanishes(S.StubTable):
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path, body)); return [{'a': 1}] if method == 'GET' else []
st = S.issue('SCC', 'nextdoor.com', 'id-check', write=True, table=RowVanishes(), runner=runner_ok, env=ENV, log=L, flag='1')
check('PATCH matching 0 rows is no-row, never "written"', st == 'no-row')
check('real PATCH asks for return=representation', 'return=representation' in open(os.path.join(HERE, '..', 'job', 'signin_send.py'), encoding='utf-8').read())
buf = io.StringIO(); real_issue = S.issue
S.issue = lambda *a, **k: 'no-row'
with contextlib.redirect_stdout(buf): rc = S.main(['--reissue', '--directory', 'nextdoor.com', '--verify-type', 'id-check'])
S.issue = real_issue
check('reissue with no row exits 1 and does not say written', rc == 1 and 'written' not in buf.getvalue())

# (1) leak: a vault error reason is allowlisted in Python; raw stderr with secret text never reaches the log
logs.clear()
rn = lambda cmd, **kw: types.SimpleNamespace(returncode=1, stdout='', stderr='send=failed reason=unexpected token h ' + SECRET.lower())
check('unknown reason: None', S.make_signin_send('SCC', 'nextdoor.com', 'id-check', runner=rn, env=ENV, log=L) is None)
check('unknown reason is logged as operation-failed, secret not logged', len(logs) == 1 and 'operation-failed' in logs[0] and SECRET.lower() not in logs[0].lower() and 'unexpected' not in logs[0])
logs.clear()
rn = lambda cmd, **kw: types.SimpleNamespace(returncode=1, stdout='', stderr='send=failed reason=send-no-url')
S.make_signin_send('SCC', 'nextdoor.com', 'id-check', runner=rn, env=ENV, log=L)
check('allowlisted reason is kept', len(logs) == 1 and 'send-no-url' in logs[0])

# (1) leak end to end: real vault_send.cjs against a fake fill helper whose bw returns non-JSON holding the secret
import subprocess, tempfile
FAKE = os.path.join(HERE, 'fixtures', 'fake_fill.cjs')
for mode in ('get-item', 'send-create'):
    env2 = dict(os.environ, FAKE_BW_MODE=mode, FAKE_SECRET=SECRET)
    pr = subprocess.run(['node', os.path.join(HERE, '..', 'job', 'vault_send.cjs'), '--organization', 'o', '--collection', 'c', '--fill-js', FAKE, '--directory', 'nextdoor.com'],
                        capture_output=True, text=True, env=env2, timeout=60)
    check('%s non-JSON: exits nonzero, secret not in stdout/stderr' % mode, pr.returncode == 1 and SECRET not in pr.stdout + pr.stderr and SECRET.lower() not in (pr.stdout + pr.stderr).lower() and 'reason=operation-failed' in pr.stderr)
    logs.clear()
    rn = lambda cmd, **kw: pr
    S.make_signin_send('SCC', 'nextdoor.com', 'id-check', runner=rn, env=ENV, log=L)
    check('%s: Python log has no secret' % mode, len(logs) == 1 and SECRET.lower() not in logs[0].lower() and 'hunter' not in logs[0].lower())

# (2) record_transition behavior with stub portal, verification and runner
import copy, tempfile, shutil, json as _json
os.environ['CE_DIRECTORIES_WRITE'] = '0'   # Directory sink off: this suite never touches it
import transitions as T, portal as P
SRCQ = os.path.join(HERE, 'fixtures', 'test_queue.json')
class FP:
    def __init__(self): self.calls = []
    def latest_snapshot(self, cid): return {'payload': {'found': 1, 'directories': []}}
    def upsert_snapshot(self, cid, day, payload): self.calls.append(('snap', '', None))
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path, body))
        return [{'a': 1}] if method in ('GET', 'PATCH') else None
def park(vt, flag, runner, steps=None):
    d = tempfile.mkdtemp(); qp = os.path.join(d, 'q.json'); shutil.copy(SRCQ, qp)
    q = _json.load(open(qp)); r0 = q['fix_queue'][0]; r0['state'] = 'submitted'; _json.dump(q, open(qp, 'w'))
    if flag is None: os.environ.pop(S.FLAG, None)
    else: os.environ[S.FLAG] = flag
    for k, v in ENV.items(): os.environ[k] = v
    real_run = S.subprocess.run; S.subprocess.run = runner
    fp = FP()
    try:
        kw = {'steps': steps or ['Open the site', 'Upload the document'], 'directory_url': 'https://' + r0['directory'] + '/login'} if vt == 'id-check' else {}
        out = T.record_transition('SCC', r0['id'], 'needs-human', None, 'n', queue_path=qp, today='2026-10-30', portal=fp, verify_type=vt, verification=fp, directories=None, **kw)
    finally:
        S.subprocess.run = real_run; os.environ.pop(S.FLAG, None)
        for k in ENV: os.environ.pop(k, None)
    return out, fp
vcalls_n = [0]
def counting(cmd, **kw): vcalls_n[0] += 1; return runner_ok(cmd, **kw)
out, fp = park('id-check', '1', counting)
pa = [c for c in fp.calls if c[0] == 'PATCH' and c[2] and 'signin_send_url' in c[2]]
check('(a) id-check + flag: vault runs once, one PATCH of the two columns', vcalls_n[0] == 1 and len(pa) == 1 and set(pa[0][2]) == {'signin_send_url', 'signin_send_expires_at'} and out['verification_written'] and not out['errors'])
check('(a) result string carries no URL/key', URL not in repr(out) and 'KEYMATERIAL' not in repr(out))
vcalls_n[0] = 0
out, fp = park('phone-call', '1', counting)
check('(b) phone-call + flag: vault never called, no signin PATCH', vcalls_n[0] == 0 and not [c for c in fp.calls if c[2] and 'signin_send_url' in str(c[2])] and out['verification_written'])
out, fp = park('id-check', None, counting)
check('(c) id-check, flag off: no Send, no vault call', vcalls_n[0] == 0 and 'signin_send' not in out and out['verification_written'])
def boom(cmd, **kw): raise RuntimeError(SECRET)
out, fp = park('id-check', '1', boom)
check('(d) issue raising: queue + verification writes still succeed', out['portal_written'] and out['verification_written'] and json.load(open(SRCQ)) is not None)
check('(d) errors hold only a type name, no secret', all(SECRET not in e for e in out['errors']) and not [c for c in fp.calls if c[2] and 'signin_send_url' in str(c[2])])
def boom2(*a, **k): raise KeyError(SECRET)
real_issue = S.issue; S.issue = boom2
out, fp = park('id-check', '1', counting)
S.issue = real_issue
check('(d) issue() itself raising: writes succeed, errors == type name only', out['portal_written'] and out['verification_written'] and out['errors'] == ['signin_send: KeyError'])

# transitions.py: id-check park with flag on calls issue; phone park does not
import transitions as T
src_t = open(os.path.join(HERE, '..', 'job', 'transitions.py'), encoding='utf-8').read()
check('transitions only calls issue under the flag', 'CE_SIGNIN_SEND_WRITE") == "1"' in src_t and src_t.count('S.issue(') == 1)

print('%d/%d' % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
