# Lesson: a foreign key is a precondition the caller must own (t_9a722352)

Two writers (the park's status upsert, `playbook.py set`) each assumed some earlier step had already put the Directory row in `ce_directories`. For a domain new to the Catalog nobody had, so PostgREST answered 409 after the queue and portal writes had already happened. The second caller even refused with "add the Directory first", which sent a human to insert by hand.

Rule: when a table references another by foreign key, the code that writes the child makes sure the parent exists, through one shared function (`directories.ensure_directory`), insert-only (`ignore-duplicates`, never an overwrite), with a rule-made minimal row and a clear refusal if it cannot. Do not rely on an upstream step or a human.

Test it with a fake that enforces the same FKs and answers 409, run every caller (sink, create-row, playbook set, dry runs), and add a mutation that switches the shared function off and requires the 409 to happen. For a mail matcher, take the real captured mail shapes (sanitized) as fixtures: the failure was a button host the matcher had never seen (sortli.st) and a tracker link that happened to match the path pattern.
