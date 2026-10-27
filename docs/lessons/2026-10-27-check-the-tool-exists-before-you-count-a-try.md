# Lesson 2026-10-27: check the tool exists before you count a try

Card t_6b1e01ff. Batch 14 lost one of three CapSolver tries to a missing `CAPSOLVER_CLI` env var: the call returned "no output", and the log counted it as try 1.

- Put every precondition check (tool path, credentials, mailbox env) BEFORE the line that spends or counts an attempt. A cap that counts setup failures punishes the row for a problem the row does not have.
- A set-but-wrong env var is an error, not a cue to fall back silently to another file: the operator should fix the variable.
- A report that cannot read its source (mailbox env missing) must say "not read", never "none found". "None" reads as a verdict about the Directory.
- Before adding a parser rule for a masked or prose value (phone "(270) 841-2*** show", street in an About sentence), require the other fields of the same value to agree (city, state, zip, visible digits). A looser regex turns a wrong value into a match.
