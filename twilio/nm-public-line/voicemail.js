// Voicemail on the parent call. Same greeting as the old twimlet. Recording attaches to this call,
// so the nacke-media inbox cron (Calls To=629 -> Recordings) picks it up.
exports.handler = function (context, event, callback) {
  const twiml = new Twilio.twiml.VoiceResponse();
  twiml.say('Nacke Media. Leave a message.');
  twiml.record({
    maxLength: 180,
    playBeep: true,
    trim: 'trim-silence',
    timeout: 5,
    action: '/vm-done',
    method: 'POST',
  });
  twiml.hangup();
  return callback(null, twiml);
};
