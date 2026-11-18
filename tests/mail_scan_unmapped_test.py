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

_TD = tempfile.mkdtemp()
FIXTURE_Q = os.path.join(_TD, 'queue.json')   # a test never reads the live queue: every call passes --queue
def _row(i, d, state='submitted'): return {'id': i, 'directory': d, 'state': state}
open(FIXTURE_Q, 'w').write(json.dumps({'fix_queue': [_row('fix-bbb', 'bbb.org')], 'create_rows': [_row('create-us-business', 'us-business.info'), _row('create-localstar', 'localstar.org')]}))

def cli(argv, queue=FIXTURE_Q):
    if queue and '--queue' not in argv: argv = list(argv) + ['--queue', queue]
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

# 7 the queue derives the map: a queue-row Directory with no data-file row maps to itself
MSGS[:] = MSGS + [msg('US Biz <noreply@us-business.info>', uid=4)]
rc, out, err = cli(['--presence', '--headers', '--directory', 'us-business.info'])
check('7 queue-row Directory with no data-file row (us-business.info) is mapped and counted', rc == 0 and 'us-business.info | 1 matching mail(s)' in out, (rc, out, err))
rc, out, err = cli(['--verify-link', '--directory', 'localstar.org'])
check('7 verify-link on a queue-row Directory (localstar.org) does not refuse', 'NOT MAPPED' not in err, (rc, out, err))
rc, out, err = cli(['--presence', '--directory', 'kentuckyonline.com'])
check('7 a name in neither the queue nor the data file still refuses, and the message names the data file', rc == 2 and 'DIRECTORY NOT MAPPED: kentuckyonline.com (not a queue row directory and not in config/mail_domains.json)' in err and out == '', (rc, out, err))
check('7 queue set does not leak past the run', M._QUEUE_DIRS == frozenset())
# data-file row overrides a queue row
check('7 data-file row wins: cylex.us -> cylex.us.com with a queue row of the same name', M._domain_of('cylex.us') == 'cylex.us.com')
# unreadable queue: data file only, said on stderr, mapped data-file Directory still works, queue-only one refuses
gone = os.path.join(_TD, 'gone.json')
rc, out, err = cli(['--presence', '--directory', 'kentuckyizze.com', '--queue', gone])
check('7 unreadable queue: data-file Directory still counts, stderr says the queue was not read', rc == 0 and 'kentuckyizze.com | mails from the Directory: 1' in out and 'QUEUE NOT READ' in err, (rc, out, err))
rc, out, err = cli(['--presence', '--directory', 'us-business.info', '--queue', gone])
check('7 unreadable queue: a queue-only Directory refuses', rc == 2 and 'DIRECTORY NOT MAPPED: us-business.info' in err and 'matching mail' not in out, (rc, out, err))
rc, out, err = cli(['--queue', gone])
check('7 unreadable queue: approval scan returns 2, no crash', rc == 2 and 'QUEUE NOT READ' in err, (rc, out, err))
# mutation: remove the queue derivation -> the queue-row checks must fail
realq = M._load_queue_dirs
M._load_queue_dirs = lambda path: (realq(path)[0], frozenset())
rc, out, err = cli(['--presence', '--headers', '--directory', 'us-business.info'])
M._load_queue_dirs = realq
check('7 mutation (queue derivation removed) is DETECTED: us-business.info refuses', rc == 2 and 'NOT MAPPED: us-business.info' in err)
rc, out, err = cli(['--presence', '--headers', '--directory', 'us-business.info'])
check('7 restored: queue derivation back', rc == 0 and 'us-business.info | 1' in out, (rc, out, err))

# 8 kentuckyizze.com is a white-label of The Local Core: its mail comes from notify.thelocalcore.com
check('8 kentuckyizze.com alias is thelocalcore.com in the data file', M.MAIL_DOMAINS['kentuckyizze.com']['aliases'] == ('thelocalcore.com',))
check('8 From x@notify.thelocalcore.com on the kentuckyizze.com row is counted', M.presence('kentuckyizze.com', [msg('Local Core <x@notify.thelocalcore.com>', body='Confirm your email')])[0] == 1)
check('8 lookalike host thelocalcore.com.evil.io is rejected', M.presence('kentuckyizze.com', [msg('x@thelocalcore.com.evil.io')])[0] == 0)
check('8 lookalike prefix host notthelocalcore.com is rejected', M.presence('kentuckyizze.com', [msg('x@notthelocalcore.com')])[0] == 0)
check('8 the Local Core alias does not leak to the kentuckyonline.us row', M.presence('kentuckyonline.us', [msg('x@notify.thelocalcore.com')])[0] == 0)

# 9 (t_19510826) a shared alias sender across two Directory rows is refused at load, never guessed
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, 'm.json')
    def rows_json(*rows): return json.dumps({'directories': [{'directory': d, 'domain': d, 'aliases': list(al), 'approval': False} for d, al in rows]})
    for label, rows in (('same alias', (('kentuckyonline.us', ['usaonline.us']), ('ohioonline.us', ['usaonline.us']))),
                        ('alias host under the other row alias', (('kentuckyonline.us', ['usaonline.us']), ('ohioonline.us', ['mail.usaonline.us']))),
                        ('alias host over the other row alias', (('kentuckyonline.us', ['mail.usaonline.us']), ('ohioonline.us', ['usaonline.us'])))):
        open(p, 'w').write(rows_json(*rows))
        try: M.load_mail_domains(p); err9 = ''
        except ValueError as e: err9 = str(e)
        check('9 %s on two rows raises, message names both rows' % label, err9 and rows[0][0] in err9 and rows[1][0] in err9, err9)
    def rows_dom(*rows): return json.dumps({'directories': [{'directory': d, 'domain': dom, 'aliases': list(al), 'approval': False} for d, dom, al in rows]})
    for label, rows in (('alias equal to the other row domain', (('kentuckyonline.us', 'kentuckyonline.us', ['usaonline.us']), ('usaonline.us', 'usaonline.us', []))),
                        ('alias under the other row domain', (('kentuckyonline.us', 'kentuckyonline.us', ['mail.usaonline.us']), ('usaonline.us', 'usaonline.us', []))),
                        ('alias over the other row domain', (('kentuckyonline.us', 'kentuckyonline.us', ['usaonline.us']), ('ky.usaonline.us', 'ky.usaonline.us', [])))):
        open(p, 'w').write(rows_dom(*rows))
        try: M.load_mail_domains(p); err9 = ''
        except ValueError as e: err9 = str(e)
        check('9 %s raises, message names both rows' % label, err9 and rows[0][0] in err9 and rows[1][0] in err9, err9)
    for r1, a1, r2, a2 in (('kentuckyizze.com', 'notify.thelocalcore.com', 'tennesseeizze.com', 'thelocalcore.com'), ('kentuckyonline.us', 'usaonline.us', 'northcarolinaonline.us', 'usaonline.us')):
        open(p, 'w').write(rows_json((r1, [a1]), (r2, [a2])))
        try: M.load_mail_domains(p); err9 = ''
        except ValueError as e: err9 = str(e)
        check('9 long-name pair %s / %s: full message names both rows (not cut at 100)' % (r1, r2), r1 in err9 and r2 in err9 and len(err9) > 100, err9)
    open(p, 'w').write(rows_dom(('kentuckyonline.us', 'kentuckyonline.us', ['usaonline.us']), ('ohioonline.us', 'ohioonline.us', [])))
    check('9 a row with an alias and an unrelated other row still loads', len(M.load_mail_domains(p)) == 2)
    open(p, 'w').write(rows_json(('kentuckyonline.us', ['usaonline.us']), ('kentuckyizze.com', ['thelocalcore.com']), ('cylex.us', []), ('cylex.us.com', [])))
    check('9 distinct aliases, and rows with no alias, still load', len(M.load_mail_domains(p)) == 4)
check('9 the shipped map file has no shared alias (it loads)', M.load_mail_domains() == M.MAIL_DOMAINS)

# 10 (t_19510826) test gaps: the second-@ check, find_verify without a raw-name fallback, a non-host queue directory never self-maps
check('10 From <a@usaonline.us> (b@evil.io) on kentuckyonline.us is rejected (second @host)', M.presence('kentuckyonline.us', [msg('<a@usaonline.us> (b@evil.io)')])[0] == 0)
check('10 control: the plain alias From is counted', M.presence('kentuckyonline.us', [msg('<a@usaonline.us>')])[0] == 1)
VMSG = [msg('Kentucky Online <noreply@kentuckyonline.com>', body='Please confirm your email: https://kentuckyonline.com/verify?token=abc123')]
check('10 find_verify("kentuckyonline.com") directly is None (no raw-name fallback)', M.find_verify('kentuckyonline.com', VMSG) is None)
check('10 control: find_verify on a mapped Directory still finds its link', (M.find_verify('kentuckyizze.com', [msg('Kentucky Izze <noreply@kentuckyizze.com>', body='Please confirm your email: https://kentuckyizze.com/verify?token=abc123')]) or {}).get('url', '').startswith('https://kentuckyizze.com/verify'))
NOTHOST = 'yahoo.com (local.yahoo.com)'
q9 = os.path.join(_TD, 'nothost_queue.json')
open(q9, 'w').write(json.dumps({'fix_queue': [_row('fix-yahoo', NOTHOST)], 'create_rows': []}))
rc, out, err = cli(['--presence', '--directory', NOTHOST], queue=q9)
check('10 a queue row whose directory is not a bare host does not self-map (refused, rc 2)', rc == 2 and 'DIRECTORY NOT MAPPED' in err and 'matching mail' not in out, (rc, out, err))

print('%d/%d' % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
