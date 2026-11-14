# Playbook write-back rule (t_2cb780c2)

One record: `ce_directory_playbooks` (Directory DB). The Directories tab shows it, the agents run from it. Every directory run ends by keeping it true.

## Rule (text for the citation-submit skill, owned by the citation-submitter profile; Nate carries it in)

End every directory run (check, create, claim, fix, verify) with a playbook update for the task you did, when the steps changed or were proven:

```
python job/playbook.py set --domain <domain> --task <check|create|claim|fix|verify> --file <steps.json> [--dry-run]
```

- The file is `{"steps": [{"text", "url?", "selector?"}], "source": "run <id>", "last_proven_at": "<UTC ISO>"}`. Placeholders only: `{business_name} {login_email} {phone} {website} {vault_item}`. The validator refuses a tenant value, an email, a phone, a 6+ digit run or a secret before any write.
- Set `last_proven_at` ONLY when the run reached its goal (listing found or confirmed absent, account created, claim submitted, fix saved, code accepted). A run that stopped, failed or was blocked sets nothing proven; if it learned the old steps are wrong, set the new steps with `"stale": true` and no `last_proven_at`, so the page shows "Stale: check before trusting".
- A proven set clears `stale` (the row never carries both).
- Never put a value you typed (name, email, phone, code, password) in a step.

## Verify Now agent
The agent has no service key and never writes the playbook. Its prompt (step 8) asks for one last line, `PLAYBOOK-NOTE: ok` or `PLAYBOOK-NOTE: <what changed>`. The trace it logs (PR #107, `verify-traces/promote/*.json`, written only after a clean send) feeds the verify task:

```
python job/playbook.py from-trace --file <promote file> [--send-is-signup] [--proven] [--dry-run]
```

`--proven` stamps `last_proven_at`; the owner passes it only after `result --outcome accepted`. Without it the row is written with no proven date.

## Open item (not in this PR)
Nothing runs `from-trace` automatically. Wiring it into the runner after an accepted result needs a Nate decision, because it adds a DB write to the verify path (fence area).
