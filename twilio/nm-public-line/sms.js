// nm-public-line /sms: push each inbound SMS to Telegram instantly, reply with empty TwiML.
// TG_TOKEN and TG_CHAT come from Function env vars. Nothing here logs them.
const https = require('https');

function post(token, payload) {
  return new Promise((resolve) => {
    const body = JSON.stringify(payload);
    const req = https.request({
      hostname: 'api.telegram.org',
      path: `/bot${token}/sendMessage`,
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
      timeout: 7000,
    }, (res) => { res.resume(); res.on('end', () => resolve(res.statusCode)); });
    req.on('timeout', () => { req.destroy(); resolve('timeout'); });
    req.on('error', () => resolve('error'));
    req.write(body);
    req.end();
  });
}

exports.handler = async function (context, event, callback) {
  const twiml = new Twilio.twiml.MessagingResponse();
  const from = String(event.From || 'unknown');
  const text = String(event.Body || '');
  const media = parseInt(event.NumMedia || '0', 10);
  const lines = ['NM public line text', `from: ${from}`, `body: ${text}`];
  if (media > 0) lines.push(`media: ${media} attachment(s), see Twilio console`);
  lines.push(`sid: ${event.MessageSid || ''}`);
  if (context.TG_TOKEN && context.TG_CHAT) {
    const status = await post(context.TG_TOKEN, {
      chat_id: context.TG_CHAT,
      text: lines.join('\n'),
      disable_web_page_preview: true,
    });
    console.log(`tg ${event.MessageSid || ''} ${status}`);
  } else {
    console.log('tg skipped: env missing');
  }
  return callback(null, twiml);
};
