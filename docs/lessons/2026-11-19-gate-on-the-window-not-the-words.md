# Lesson: when a regex cannot tell a robot from a customer, gate on WHEN the call happened, and keep that fact where the reader can still see it (t_282b646e)

call_code.py read a transcript and printed a code after a cue word. Two review rounds tuned the cue regex, and "the gate pin is 4455" (a customer voicemail) still became a code line. No wording rule can tell the Directory's robot from a customer; the only difference is WHEN the call came in: the robot calls while a Verify Now phone-call request is out.

Rules:
- Gate on the structural fact (the call started inside an armed window), not on more wording. Outside the window nothing is transcribed and nothing is printed.
- The live signal (the Twilio Sync doc) is deleted the moment the request ends, which is before the 2-minute cron reads the recording. A gate that reads only the live signal would drop every real code. Keep a local window log (ids and times only) written at arm time and closed at disarm time, and read that.
- A failed disarm must leave the window open to its `until`: that is what the line really does, and a log that claimed it closed would hide a recording the line still made.
- The log may only NARROW what is reported. Add the contradiction case next to the match case: inside the window, a transcript with no code cue still prints nothing.
- A byte-for-byte copy of deployed source can hold identifiers the leak check bans (the line's published number and the business name in a header comment). Do not edit the copy and do not skip the directory: tolerate exactly those three hashes there, and keep a planted control that still fails inside that directory.
