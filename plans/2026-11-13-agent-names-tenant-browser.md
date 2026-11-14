# Plan: the verify agent prompt names the tenant's browser (t_45fe02d4)

Cites lesson `docs/lessons/2026-11-13-one-source-for-the-steps.md`: one record, not two copies. Here the tenant -> (profile, port) pair lives in ONE table (`TENANT_BROWSER` in job/verify_send.py); the prompt text, the Chrome start and the port check all read it.

Problem: prompt step 1 says "the one browser session this run reserved" but the agent path reserves none; a fresh browser hits reCAPTCHA on Alignable and the v3 playbook STOPs.

1. `TENANT_BROWSER = {"NM": ("nm-chrome-profile", 9334), "SCC": ("build-profile", 9333)}`; `tenant_browser(biz)` -> (profile dir under %LOCALAPPDATA%/citation-engine, port, cdp url). Unknown tenant raises (fail closed).
2. Prompt step 1 (sign-in and signup variants): "Use ONLY the browser at http://127.0.0.1:<port> (already open). Do not open another browser."
3. `Runtime.agent_browser(tenant)`: port listening -> its process command line must carry `--user-data-dir=<this tenant's profile>`, else refuse (BrowserError); listening with the right profile -> reuse, leave it running; not listening -> OwnedChrome(profile, port), closed at the end (profile kept).
4. `_agent_send` opens it BEFORE launch_agent; any browser failure = `failed/send_failed`, no agent. Fence, cap, tenant lock unchanged.
5. Tests in tests/verify_agent_test.py: NM prompt names 9334 not 9333, SCC the reverse, signup variant too; port held by another profile refused with no agent; reuse leaves it open; started browser closed on every exit; a mutation swaps the profiles and the test must fail.

No send, no portal write, no deploy. After merge: re-render dry runs a25e00ff and 61ccf904.
