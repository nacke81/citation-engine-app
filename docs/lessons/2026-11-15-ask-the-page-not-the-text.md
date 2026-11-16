# Lesson: when text classification keeps leaking, ask the page (t_00a83602)

Evidence: four review rounds on `landed()` (PR #127) still passed "Press the button to send your verification code", "Choose how to get...", "Sending verification code..." and refused "A 6-digit code is on its way". Each regex fix opened the next phrasing family.

Rules:
- A gate over agent-quoted text decides only when nothing better is readable. When the tenant's browser can be read (CDP, read-only), the DOM decides: a visible, enabled code input = landed; a read page with none = refused, whatever the text says.
- Fail open only on "cannot see" (no session, no Playwright, any probe error), never on "saw none". Log which one happened.
- Put the selector rules in pure functions over a plain snapshot so each rule has a fixture and a mutation, with no browser in CI. Set a no-CDP env in the shared fakes so no suite ever touches a real Chrome.
- A split character in a regex (`/`) needs its own test string, or removing it passes silently.
