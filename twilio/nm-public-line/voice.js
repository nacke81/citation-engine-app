// Nacke Media public line (629) 280-2578 inbound voice.
// Mon-Fri 09:00-17:00 America/Chicago: ring FORWARD_TO for ~20 s, caller ID = the business line.
// Outside hours, or no answer/busy/failed: voicemail (<Record>, recording stays on this parent call).
// FORWARD_TO is a Service environment variable only. Never put the number in code or logs.
//
// Verify-arm (t_b4fda6b1): while a citation "Verify Now" phone-call request is armed, skip the
// forward and record straight away so the robot's code lands in a recording.
// Arm signal = Sync document "verify_armed" in Sync service ARM_SYNC_SID, data
// { verify_armed_until: ISO-8601 UTC }. Armed iff now < verify_armed_until AND
// now < doc.date_updated + 15 min (hard cap). Missing doc / any error / >2 s = not armed.

const MAX_ARM_MS = 15 * 60 * 1000;

function openNow(now) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Chicago',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(now);
  const get = (t) => (parts.find((p) => p.type === t) || {}).value;
  const day = get('weekday');
  const minutes = parseInt(get('hour'), 10) * 60 + parseInt(get('minute'), 10);
  const weekday = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'].includes(day);
  return weekday && minutes >= 9 * 60 && minutes < 17 * 60;
}

async function armedNow(context, now) {
  const sid = context.ARM_SYNC_SID;
  if (!sid) return false;
  let timer;
  try {
    const fetchDoc = context
      .getTwilioClient()
      .sync.v1.services(sid)
      .documents('verify_armed')
      .fetch();
    const timeout = new Promise((_, rej) => {
      timer = setTimeout(() => rej(new Error('arm-timeout')), 2000);
    });
    const doc = await Promise.race([fetchDoc, timeout]);
    const until = Date.parse((doc.data || {}).verify_armed_until || '');
    const updated = new Date(doc.dateUpdated || doc.dateCreated).getTime();
    if (!Number.isFinite(until)) return false;
    return now.getTime() < until && now.getTime() < updated + MAX_ARM_MS;
  } catch (e) {
    if (e && e.status !== 404) console.log('arm-check-error ' + (e.message || e));
    return false;
  } finally {
    clearTimeout(timer);
  }
}

exports.openNow = openNow;
exports.armedNow = armedNow;

exports.handler = async function (context, event, callback) {
  const twiml = new Twilio.twiml.VoiceResponse();
  const now = new Date();
  if (await armedNow(context, now)) {
    // No greeting: verification robots start talking on answer. Record on this parent call,
    // same action as /voicemail so the inbox cron picks the recording up the same way.
    console.log('route=verify-armed');
    twiml.record({
      maxLength: 180,
      playBeep: false,
      trim: 'do-not-trim',
      timeout: 15,
      action: '/vm-done',
      method: 'POST',
    });
    twiml.hangup();
    return callback(null, twiml);
  }
  const target = context.FORWARD_TO;
  if (target && openNow(now)) {
    const dial = twiml.dial({
      timeout: 20,
      callerId: event.To,
      answerOnBridge: true,
      action: '/after-dial',
      method: 'POST',
    });
    dial.number(target);
    console.log('route=dial');
  } else {
    console.log(target ? 'route=closed' : 'route=no-target');
    twiml.redirect({ method: 'POST' }, '/voicemail');
  }
  return callback(null, twiml);
};
