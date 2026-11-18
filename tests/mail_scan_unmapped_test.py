"""mail_scan: a Directory the listings@ scan cannot see is refused, never counted as 0 mail (t_2b13224d). No IMAP, no network, no real mail."""
import contextlib, io, json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'job'))
os.environ['CE_IDENTITY'] = os.path.join(HERE, 'test_identity.json')
os.environ.setdefault('CE_DIRECTORIES_WRITE', '0')
import os as _fo; _fo.environ["CE_PORTAL_ENV"] = _fo.path.join(_fo.path.dirname(_fo.path.abspath(__file__)), "no-such-portal.env")  # t_2ddc7067: fail closed, never the prod portal
import mail_scan as M

ok = []
def check(name, value, extra=''):
    ok.append(bool(value)); print(('PASS ' if value else 'FAIL ') + name + ((' :: ' + str(extra)[:160]) if not value and extra else ''))

def msg(frm, subj='Please confirm your email', uid=1, body='hello'):
    return {'uid': uid, 'from': frm, 'subject': subj, 'body': body, 'date': '2026-11-10T12:00:00Z', 'folder': 'INBOX', 'to': ['listings@example.org']}

MSGS = [msg('Kentucky Izze <noreply@kentuckyizze.com>', uid=1), msg('Biz <noreply@biz.usaonline.us>', uid=2), msg('Bank <a@bbb.org>', uid=3)]
M.read_messages = lambda **k: MSGS

def cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try: rc = M.main(argv)
        except SystemExit as e: rc = e.code
    return rc, out.getvalue(), err.getvalue()

MODES = {'presence': ['--presence'], 'headers': ['--presence', '--headers'], 'verify-link': ['--verify-link'], 'reset-link': ['--reset-link'], 'approval scan': []}

def refuses(d, mode):
    rc, out, err = cli(MODES[mode] + ['--directory', d])
    return rc not in (0, None) and ('DIRECTORY NOT MAPPED: %s' % d) in err and 'matching mail' not in out and 'mails from the Directory' not in out and d not in out

# 1 unmapped refuses, every mode
for mode in MODES:
    for d in ('kentuckyonline.com', 'nosuch-directory.example'):
        rc, out, err = cli(MODES[mode] + ['--directory', d])
        check('1 %s: unmapped %s -> rc != 0, DIRECTORY NOT MAPPED on stderr, no count line' % (mode, d), refuses(d, mode), (rc, out, err))
rc, out, err = cli(['--presence', '--headers', '--directory', 'bbb.org', '--directory', 'kentuckyonline.com'])
check('1 one mapped + one unmapped: still refuses, prints no count for either', rc == 2 and out == '' and 'NOT MAPPED: kentuckyonline.com' in err, (rc, out, err))
check('1 case/space variants of a mapped name map; nothing else does', M._domain_of(' KentuckyIzze.com ') == 'kentuckyizze.com' and M._domain_of('kentuckyizze.co') is None)

# 2 mapped: the two Directories of the defect scan and count
rc, out, err = cli(['--presence', '--headers', '--directory', 'kentuckyizze.com'])
check('2 kentuckyizze.com is mapped: rc 0, counts its mail (1)', rc == 0 and 'kentuckyizze.com | 1 matching mail(s)' in out, (rc, out, err))
rc, out, err = cli(['--presence', '--headers', '--directory', 'kentuckyonline.us'])
check('2 kentuckyonline.us: the usaonline.us wizard From (alias) is counted', rc == 0 and 'kentuckyonline.us | 1 matching mail(s)' in out and 'from @biz.usaonline.us' in out, (rc, out, err))
check('2 kentuckyizze row does NOT take the usaonline.us alias', M.presence('kentuckyizze.com', [MSGS[1]])[0] == 0)
check('2 kentuckyonline.us row does not take an unrelated sender', M.presence('kentuckyonline.us', [MSGS[2]])[0] == 0)
rc, out, err = cli(['--presence', '--headers', '--directory', 'bbb.org'])
check('2 bbb.org (old map) unchanged', rc == 0 and 'bbb.org | 1 matching mail(s)' in out, (rc, out))
check('2 SCAN_DIRECTORIES (approval set recheck reads) is exactly the old six', M.SCAN_DIRECTORIES == {'bbb.org': 'bbb.org', 'loc8nearme.com': 'loc8nearme.com', 'businessyab.com': 'businessyab.com', 'discoverourtown.com': 'discoverourtown.com', 'cylex.us': 'cylex.us.com', 'cylex.us.com': 'cylex.us.com'}, M.SCAN_DIRECTORIES)

# 3 the guard is unchanged / the alias is not a hole
check('3 alias From with a display-name spoof (usaonline.us text, evil host) is not counted', M.presence('kentuckyonline.us', [msg('usaonline.us <x@evil.example>')])[0] == 0)
check('3 lookalike host usaonline.us.evil.io is not counted', M.presence('kentuckyonline.us', [msg('x@usaonline.us.evil.io')])[0] == 0)
check('3 second @host in the From is not counted', M.presence('kentuckyonline.us', [msg('"a@usaonline.us" <x@evil.example>')])[0] == 0)
saved = dict(M.MAIL_DOMAINS)
M.MAIL_DOMAINS['yellowpages.com'] = {'domain': 'yellowpages.com', 'aliases': (), 'approval': False}
check('3 same-brand From on ANOTHER Catalog domain (yellowpages.net on the yellowpages.com row) is still rejected', M.presence('yellowpages.com', [msg('Y <a@yellowpages.net>')])[0] == 0)
check('3 the real sender on that row is counted', M.presence('yellowpages.com', [msg('Y <a@yellowpages.com>')])[0] == 1)
M.MAIL_DOMAINS.clear(); M.MAIL_DOMAINS.update(saved)

# 4 mutation: restore the silent path (unmapped -> no refusal) and the refusal checks must fail
real = M._unmapped
M._unmapped = lambda directories: []
mut = {m: refuses('kentuckyonline.com', m) for m in MODES}
rc, out, err = cli(['--presence', '--headers', '--directory', 'kentuckyonline.com'])
M._unmapped = real
check('4 mutation (silent None path restored) is DETECTED in every mode', not any(mut.values()), mut)
check('4 under the mutation the old defect line reappears (so the test is measuring the right thing)', 'kentuckyonline.com | 0 matching mail(s)' in out, out)
check('4 restored: refusal back', refuses('kentuckyonline.com', 'headers'))

# 5 data file is the map; a seat adds a Directory with no code edit; a broken file fails closed
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, 'm.json')
    open(p, 'w').write(json.dumps({'directories': [{'directory': 'newdir.example', 'domain': 'newdir.example', 'aliases': ['newdir-mail.example'], 'approval': False}]}))
    got = M.load_mail_domains(p)
    check('5 a data-file row is a mapped Directory (domain + alias)', got['newdir.example']['domain'] == 'newdir.example' and got['newdir.example']['aliases'] == ('newdir-mail.example',))
    for label, body in (('not json', 'nope'), ('empty list', '{"directories": []}'), ('bad host', '{"directories": [{"directory": "a b", "domain": "x.com"}]}'), ('missing key', '{"directories": [{"directory": "x.com"}]}')):
        open(p, 'w').write(body)
        try: M.load_mail_domains(p); raised = False
        except ValueError: raised = True
        check('5 broken data file (%s) raises, never an empty map' % label, raised)
    try: M.load_mail_domains(os.path.join(td, 'gone.json')); raised = False
    except ValueError: raised = True
    check('5 missing data file raises', raised)
check('5 shipped map file lists kentuckyonline.us with alias usaonline.us and kentuckyizze.com', M.MAIL_DOMAINS['kentuckyonline.us']['aliases'] == ('usaonline.us',) and 'kentuckyizze.com' in M.MAIL_DOMAINS)

# 6 nm-relay open-domain mode keeps its own rule (a dotted host maps itself) and still refuses a non-host
M._OPEN_DOMAINS = True
check('6 nm-relay: dotted host opens itself, free text refuses', M._domain_of('n49.com') == 'n49.com' and M._unmapped(['yahoo.com (local.yahoo.com)']) == ['yahoo.com (local.yahoo.com)'])
M._OPEN_DOMAINS = False

print('%d/%d' % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
