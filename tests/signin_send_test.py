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
check('missing item: no row write', tbl.calls == [])
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
check('write + flag: one PATCH of exactly the two columns', len(tbl.calls) == 1 and tbl.calls[0][0] == 'PATCH' and set(tbl.calls[0][2]) == {'signin_send_url', 'signin_send_expires_at'})
check('PATCH only touches a requires_verification row of this directory', 'directory=eq.nextdoor.com' in tbl.calls[0][1] and 'state=eq.requires_verification' in tbl.calls[0][1])
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

# transitions.py: id-check park with flag on calls issue; phone park does not
import transitions as T
src_t = open(os.path.join(HERE, '..', 'job', 'transitions.py'), encoding='utf-8').read()
check('transitions only calls issue under the flag', 'CE_SIGNIN_SEND_WRITE") == "1"' in src_t and src_t.count('S.issue(') == 1)

print('%d/%d' % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
