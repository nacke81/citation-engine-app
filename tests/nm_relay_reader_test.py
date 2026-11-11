"""mail_scan --mailbox nm-relay / --verify-link (t_04751f6a): reads a JSON-lines relay file; no IMAP, no network, no real mail."""
import contextlib, datetime, io, json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'job'))
os.environ['CE_IDENTITY'] = os.path.join(HERE, 'test_identity.json')
import mail_scan as M

ok = []
def check(name, value):
    ok.append(bool(value)); print(('PASS ' if value else 'FAIL ') + name)

T0 = 1794429857
def iso(sec): return datetime.datetime.fromtimestamp(sec, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
ROW1 = {'id': 'm1', 'from': 'Cylex <noreply@cylex.us.com>', 'subject': 'Verify your email', 'received': iso(T0), 'links': ['https://www.cylex.us.com/verify?t=abc123'], 'codes': ['482913'], 'to': ['listings@example.org']}
ROW2 = {'id': 'm5', 'from': 'Cylex <noreply@cylex.us.com>', 'subject': 'Welcome', 'received': iso(T0 - 7200), 'links': [], 'codes': ['654321']}
now = datetime.datetime.fromtimestamp(T0 + 3600, datetime.timezone.utc)

with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, 'mail', 'relay.jsonl')
    os.makedirs(os.path.dirname(p))
    open(p, 'w', encoding='utf-8').write(json.dumps(ROW1) + '\n' + json.dumps(ROW2) + '\n')
    os.environ['NM_RELAY_FILE'] = p
    msgs = M.read_relay_messages(now=now)
    check('reader returns message dicts (uid, folder, from, subject, date, to, body)', len(msgs) == 2 and msgs[0]['uid'] == 'm1' and msgs[0]['folder'] == 'INBOX' and msgs[0]['to'] == ['listings@example.org'] and msgs[1]['to'] == [])
    check('body rebuilt as code lines + links', msgs[0]['body'] == 'code: 482913\nhttps://www.cylex.us.com/verify?t=abc123')
    hit = M.find_verify('cylex.us', msgs)
    check('verify flow reads the relay mail (newest first: code + link)', hit and hit['code'] == '482913' and hit['url'] == 'https://www.cylex.us.com/verify?t=abc123' and hit['uid'] == 'm1')
    out = []
    rc = M.verify_main(['cylex.us', 'bbb.org'], 30, messages=msgs, out=out.append)
    check('verify_main prints link and code, and "no verification mail" for a Directory with none; exit 0', rc == 0 and '482913' in out[0] and 'verify?t=abc123' in out[0] and out[1] == 'bbb.org | no verification mail')
    check('verify_main exit 1 when nothing found', M.verify_main(['bbb.org'], 30, messages=msgs, out=lambda s: None) == 1)
    rm = [dict(msgs[0], subject='Reset your password', body='code: 777888\nhttps://www.cylex.us.com/reset-password?k=1')]
    check('reset flow also reads relay-shaped mail', M.find_reset('cylex.us', rm)['code'] == '777888')
    check('unsubscribe link is never a verify link', M.find_verify('cylex.us', [dict(msgs[0], body='https://www.cylex.us.com/unsubscribe?x=1')]) is None)
    check('days window drops old relay rows', M.read_relay_messages(now=datetime.datetime.fromtimestamp(T0 + 90 * 86400, datetime.timezone.utc), days=30) == [])
    check('missing file = no mail, not an error', M.read_relay_messages(path=os.path.join(td, 'none.jsonl')) == [])
    open(os.path.join(td, 'bad.jsonl'), 'w').write('not json\n{"x":1}\n[1]\n')
    check('garbage lines skipped', M.read_relay_messages(path=os.path.join(td, 'bad.jsonl')) == [])

    # CLI: the relay file is read, IMAP is never opened
    called = []
    imap0, read0 = M.imaplib.IMAP4_SSL, M.read_messages
    def boom(*a, **k): called.append(a); raise AssertionError('IMAP used')
    def run(args):
        buf = io.StringIO()
        M.imaplib.IMAP4_SSL = boom
        try:
            with contextlib.redirect_stdout(buf): rc = M.main(args)
        finally:
            M.imaplib.IMAP4_SSL = imap0; M.read_messages = read0
        return rc, buf.getvalue()
    rc, txt = run(['--mailbox', 'nm-relay', '--verify-link', '--directory', 'cylex.us', '--days', '3650'])
    check('CLI --mailbox nm-relay --verify-link reads the file, never IMAP', rc == 0 and called == [] and '482913' in txt and 'verify?t=abc123' in txt)
    rc, txt = run(['--mailbox', 'nm-relay', '--presence', '--directory', 'cylex.us', '--days', '3650'])
    check('CLI --mailbox nm-relay --presence reads the file, never IMAP', rc == 0 and called == [] and 'mails from the Directory: 2' in txt)
    try:
        with contextlib.redirect_stderr(io.StringIO()): M.main(['--verify-link'])
        needs_dir = False
    except SystemExit as e:
        needs_dir = e.code == 2
    check('--verify-link without --directory is a usage error', needs_dir)
    check('default mailbox stays IMAP (read_messages restored after nm-relay runs)', M.read_messages is read0)
    del os.environ['NM_RELAY_FILE']

print('%d/%d passed' % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
