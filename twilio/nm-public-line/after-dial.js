// Dial action: if the forwarded leg was answered, end. Otherwise go to voicemail.
exports.handler = function (context, event, callback) {
  const twiml = new Twilio.twiml.VoiceResponse();
  console.log('dial_status=' + event.DialCallStatus);
  if (event.DialCallStatus === 'completed' || event.DialCallStatus === 'answered') {
    twiml.hangup();
  } else {
    twiml.redirect({ method: 'POST' }, '/voicemail');
  }
  return callback(null, twiml);
};
