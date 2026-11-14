# A generic prompt must read which step is the send, not assume it

Round 3 of the signup prompt wrote "The Sign up click already sent the code. Do NOT click any other send..." because Thumbtack's Sign up click IS the send. Alignable's Sign Up click only creates the account; the send is a later "Verify with SMS/Text" click. The generic line read as a ban on the real send, and Mike's click would have failed on our own prompt.

Lessons:
- When a template states a fact about one site, it is a site fact. Put it on the playbook (`send: true` on the step) and have the template read it.
- Validate the marker where it is written (`playbook.py set`: exactly one marked step when send_is_signup is true) and again where it is read (the run fails closed before the agent if the stored row has none).
- Test the template against two real shapes (send on the signup click, send on a later click). One site passing proves nothing about the other.
- A machine-written replacement (a trace) cannot carry a human mark, so it must not overwrite a marked playbook.
