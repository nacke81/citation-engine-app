"""NM listings relay (t_04751f6a): no network, no gog, no real mail, no send. gog is a fake that records every argv."""
import base64, io, json, os, sys, tempfile, contextlib, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'job'))
os.environ['CE_IDENTITY'] = os.path.join(HERE, 'test_identity.json')
import nm_listings_relay as R, mail_scan as M

ok = []
def check(name, value):
    ok.append(bool(value)); print(('PASS ' if value else 'FAIL ') + name)

def b64(s): return base64.urlsafe_b64encode(s.encode()).decode()
def msg(mid, to, body, frm='Cylex <noreply@cylex.us.com>', subj='Verify your email', labels=('INBOX',), hdr='To', ms=1794429857000):
    return {'id': mid, 'labelIds': list(labels), 'internalDate': str(ms),
            'payload': {'headers': [{'name': 'From', 'value': frm}, {'name': hdr, 'value': to}, {'name': 'Subject', 'value': subj}],
                        'mimeType': 'multipart/alternative', 'parts': [{'mimeType': 'text/plain', 'body': {'data': b64(body)}}]}}

MINE = msg('m1', 'listings@nackemedia.com', 'Your code: 482913\nVerify: https://www.cylex.us.com/verify?t=abc123\nhttps://www.cylex.us.com/unsubscribe?x=1')
DECOY = msg('m2', 'mike@nackemedia.com', 'Bank code 111222 https://bank.example/secret')
DECOY2 = msg('m3', 'Someone <other@nackemedia.com>', 'x 999888')
SENT = msg('m4', 'listings@nackemedia.com', 'we sent this 123456', labels=('SENT',))
BCC = msg('m5', '"Listings" <Listings@NackeMedia.com>', 'pin 654321', hdr='Delivered-To', ms=1794429857000 - 7200000)

class FakeGog:
    def __init__(self, threads): self.threads, self.calls = threads, []
    def __call__(self, argv):
        self.calls.append(argv)
        if argv[3:5] == ['gmail', 'search']: return {'threads': [{'id': 't%d' % i} for i in range(len(self.threads))]}
        if argv[3:6] == ['gmail', 'thread', 'get']: return {'thread': {'messages': self.threads[int(argv[6][1:])]}}
        raise AssertionError('unexpected gog call %r' % argv)

# --- scope guard: the query
for bad in ['in:inbox', 'to:listings@nackemedia.com OR from:bank@example.com', 'to:listings@nackemedia.com -from:a@b.c', 'from:bob@x.com to:listings@nackemedia.com',
            'to:mike@nackemedia.com', 'to:listings@nackemedia.com {a b}', 'to:listings@nackemedia.com (x)', 'to:listings@nackemedia.com in:anywhere', '', 'newer_than:2d',
            'to:listings@nackemedia.com label:inbox', 'to:listings@nackemedia.com.evil.com']:
    g = FakeGog([[MINE]])
    err = io.StringIO()
    with contextlib.redirect_stderr(err): rc = R.main(['--dry', '--query', bad], gog=g, out=lambda s: None)
    check('refused %r: rc 2, gog never called' % bad, rc == 2 and g.calls == [] and 'REFUSED' in err.getvalue())
check('default query is pinned', R.DEFAULT_QUERY.startswith('to:listings@nackemedia.com') and R.check_query(R.DEFAULT_QUERY) == R.DEFAULT_QUERY)
check('newer_than may narrow', R.check_query('to:listings@nackemedia.com newer_than:1d') == 'to:listings@nackemedia.com newer_than:1d')

# --- read-only argv: only search + thread get, account pinned
g = FakeGog([[MINE, DECOY]])
recs, skipped = R.collect(R.DEFAULT_QUERY, g)
verbs = {tuple(c[3:5]) if c[3:5] == ['gmail', 'search'] else tuple(c[3:6]) for c in g.calls}
check('only gmail search + gmail thread get', verbs == {('gmail', 'search'), ('gmail', 'thread', 'get')})
check('account pinned to mike@nackemedia.com on every call', all(c[:3] == ['gog', '-a', 'mike@nackemedia.com'] for c in g.calls))
check('no send/forward/draft/modify/label word in any argv', not any(w in a.lower() for c in g.calls for a in c[3:] for w in ('send', 'forward', 'draft', 'modify', 'label', 'trash', 'delete')))
check('search argv carries the pinned query', g.calls[0][5] == R.DEFAULT_QUERY)
try: R.gog_argv('gmail', 'send', '--to', 'x'); sent = True
except R.QueryRefused: sent = False
check('gog_argv refuses a send verb', not sent)
try: R.gog_argv('gmail', 'drafts', 'create'); d = True
except R.QueryRefused: d = False
check('gog_argv refuses drafts', not d)

# --- second guard: message-level To check, even if Gmail returned the decoys
check('decoys (mike@, other@) dropped, listings@ kept', [r['id'] for r in recs] == ['m1'] and skipped == 1)
recs2, sk2 = R.collect(R.DEFAULT_QUERY, FakeGog([[MINE, DECOY, DECOY2, SENT, BCC]]))
check('SENT dropped, case-insensitive Delivered-To kept, two decoys dropped', [r['id'] for r in recs2] == ['m1', 'm5'] and sk2 == 3)
check('lookalike address is not listings@', not R.addressed_to_target(msg('x', 'listings@nackemedia.com.evil.com', 'x')) and not R.addressed_to_target(msg('x', 'xlistings@nackemedia.com', 'x')))

# --- record shape + extraction
r = recs[0]
check('record keys', list(r) == ['id', 'from', 'subject', 'received', 'links', 'codes'])
check('code and verify link extracted, unsubscribe dropped', r['codes'] == ['482913'] and r['links'] == ['https://www.cylex.us.com/verify?t=abc123'])
check('received is UTC ISO from internalDate', r['received'] == datetime.datetime.fromtimestamp(1794429857, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
check('decoy text never in the record', 'bank' not in json.dumps(recs) and '111222' not in json.dumps(recs))

# --- file: write, dedupe, dry
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, 'mail', 'nm-listings.jsonl')
    out = []
    rc = R.main(['--out', p], gog=FakeGog([[MINE, DECOY]]), out=out.append)
    rows = [json.loads(l) for l in open(p, encoding='utf-8')]
    check('first run writes one row', rc == 0 and len(rows) == 1 and rows[0]['id'] == 'm1')
    R.main(['--out', p], gog=FakeGog([[MINE, DECOY]]), out=out.append)
    check('second run dedupes by id', len(open(p, encoding='utf-8').read().splitlines()) == 1)
    R.main(['--out', p], gog=FakeGog([[MINE, BCC]]), out=out.append)
    check('new id appended', len(open(p, encoding='utf-8').read().splitlines()) == 2)
    q = os.path.join(td, 'dry.jsonl'); dry = []
    rc = R.main(['--dry', '--out', q], gog=FakeGog([[MINE, DECOY]]), out=dry.append)
    txt = '\n'.join(dry)
    check('dry writes nothing', rc == 0 and not os.path.exists(q))
    check('dry prints only the listings@ message and counts, never a code or link', 'm1' in txt and 'm2' not in txt and '482913' not in txt and 'http' not in txt and 'links=1 codes=1' in txt)
    z = []
    rc = R.main(['--dry'], gog=FakeGog([]), out=z.append)
    check('zero mail is a clean count of 0', rc == 0 and 'messages=0' in z[0])
    class Boom:
        def __call__(self, argv): raise RuntimeError('gog rc=1: auth')
    err = io.StringIO()
    with contextlib.redirect_stderr(err): rc = R.main(['--dry'], gog=Boom(), out=lambda s: None)
    check('gog failure exits 2 with a message', rc == 2 and 'RELAY FAILED' in err.getvalue())

    # --- the engine reader
    os.environ['NM_RELAY_FILE'] = p
    now = datetime.datetime.fromtimestamp(1794429857 + 3600, datetime.timezone.utc)
    msgs = M.read_relay_messages(now=now)
    check('reader returns message dicts with to=listings@nackemedia.com', len(msgs) == 2 and msgs[0]['to'] == ['listings@nackemedia.com'] and msgs[0]['uid'] == 'm1' and msgs[0]['folder'] == 'INBOX')
    hit = M.find_verify('cylex.us', msgs)
    check('verify flow reads the relay mail (code + link)', hit and hit['code'] == '482913' and hit['url'] == 'https://www.cylex.us.com/verify?t=abc123')
    out = []
    M.verify_main(['cylex.us'], 30, messages=msgs, out=out.append)
    check('verify_main prints the link and code from the relay mail', '482913' in out[0] and 'verify?t=abc123' in out[0])
    rm = [dict(msgs[0], subject='Reset your password', body='code: 777888\nhttps://www.cylex.us.com/reset-password?k=1')]
    check('reset flow also reads relay-shaped mail', M.find_reset('cylex.us', rm)['code'] == '777888')
    check('a mail from another Directory is not cylex verify mail', M.find_verify('bbb.org', msgs) is None)
    old = M.read_relay_messages(now=datetime.datetime.fromtimestamp(1794429857 + 90 * 86400, datetime.timezone.utc), days=30)
    check('days window drops old relay rows', old == [])
    check('missing file = no mail, not an error', M.read_relay_messages(path=os.path.join(td, 'none.jsonl')) == [])
    open(os.path.join(td, 'bad.jsonl'), 'w').write('not json\n{"x":1}\n')
    check('garbage lines skipped', M.read_relay_messages(path=os.path.join(td, 'bad.jsonl')) == [])
    # CLI: --mailbox nm-relay --presence reads the file, never IMAP
    called = []
    M_imap = M.imaplib.IMAP4_SSL
    M.imaplib.IMAP4_SSL = lambda *a, **k: called.append(a) or (_ for _ in ()).throw(AssertionError('IMAP used'))
    saved = M.read_messages
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf): rc = M.main(['--mailbox', 'nm-relay', '--verify-link', '--directory', 'cylex.us'])
    finally:
        M.imaplib.IMAP4_SSL = M_imap; M.read_messages = saved
    check('CLI --mailbox nm-relay --verify-link reads the relay file and never opens IMAP', rc == 0 and called == [] and '482913' in buf.getvalue() and 'verify?t=abc123' in buf.getvalue())
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf): rc = M.main(['--mailbox', 'nm-relay', '--presence', '--directory', 'cylex.us'])
    finally:
        M.imaplib.IMAP4_SSL = M_imap; M.read_messages = saved
    check('CLI --mailbox nm-relay --presence reads the relay file', rc == 0 and called == [] and 'mails from the Directory: 2' in buf.getvalue())
    del os.environ['NM_RELAY_FILE']

check('default mailbox is still listings (IMAP) in the parser', 'nm-relay' in open(os.path.join(HERE, '..', 'job', 'mail_scan.py'), encoding='utf-8').read())
print('%d/%d passed' % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
