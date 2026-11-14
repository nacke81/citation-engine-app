# Lesson: a backfill from old notes is a claim, not proof (t_2cb780c2)

Turning ~100 vault notes into playbook rows is easy to do wrong in two quiet ways.

- **Prose is not steps, and prose carries tenant data.** The first pass kept any sentence with an action word and produced narrative ("Search form is..."), a client's listing id inside a url (`?ypid=...`, `/company/<id>`), and an area code in a sentence with no full phone. Rules that held: only a sentence that STARTS with an action verb becomes a step; a url loses its query and any 5+ digit id drops the url; the sha256 denylist (`tests/denylist.json`) is checked on every word of 3+ characters; a hit DROPS the sentence, it is never scrubbed into a guess. Only two scrubs are allowed (vault item name, identity phone) and both are tested.
- **A backfill must never write `last_proven_at`.** That column means a run reached its goal. A note from 10/26 saying "rejected no-fit" is stale the day we read it, so every row from a stale note (including the ones built from the Directory fields) carries a `stale` flag and the old text is labelled "Old note, not a verified step".
- **Existing rows win.** The backfill reads the stored (domain, task) pairs first and skips them, so it can never overwrite thumbtack's live verify row.
- A hard-coded vault path tripped the repo leak check (the path holds a tenant token). Configuration that names a tenant lives in an env var or an argument, never in the repo.
- Python implicit string concatenation binds tighter than `+`: `"a" "b" + X + "c" "d" % dict` applies `%` to the last literal only. Put new prompt text in as a `%(name)s` placeholder.
- A prompt that says "you cannot write it" is the honest shape when the agent has no service key: the write-back is a recorded note plus an owner-run `from-trace --proven`, not an instruction the agent cannot follow.
