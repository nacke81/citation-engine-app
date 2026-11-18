# Plan: tests/verify_agent_test.py must not depend on the host (t_cd0e943e)

Cites lesson `docs/lessons/2026-11-18-two-sources-one-page-must-agree.md` (latest at start): a check must read the same inputs everywhere. Same shape: the prompt check read a host-specific input.

## Finding (base bac19b1)
Not a leak. The "6-digit run" in the sms / phone-call prompt is the path of the running Python (`helper_command()` = `sys.executable`): this PC's interpreter sits under a hash-named dir (`.../environments/<hash>/venv/Scripts/python.exe`) whose hash holds a 6-digit digit run. It repeats in the 9 helper-command lines. No code, no service key, no .env value was in the prompt (probe masked every digit; CODE and SERVICE_ROLE both absent). CI's python path has none.

## Change (test only, assertion unchanged)
1. For the agent happy-path loop, `S.helper_command` is pinned to a fixture path; restored right after. The existing `helper_command is the running interpreter` check still runs on the real function.
2. The predicate is one `prompt_clean(pr)` lambda, same three conditions as before.
3. Mutations: a 6-digit run, the code, or SERVICE_ROLE appended is caught; a 6-digit run through the real `build_prompt` (helper path carrying one) is caught.

Lesson note: it was written after the work (this plan was committed after the edit began; recorded in the card).
