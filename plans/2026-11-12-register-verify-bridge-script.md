# Plan: make the documented Verify Now bridge register command work (t_c814f7b5)

Cites lesson `docs/lessons/2026-11-12-the-stuck-state-needs-its-own-owner.md`: the bridge is the owner of an otherwise unwatched state, so the way to bring that owner back after a rebuild must itself work, not live only in a workspace copy.

Problem: `schtasks /create /xml job\verify_bridge_task.xml` fails ("unable to switch the encoding"): the repo file is UTF-8, schtasks wants UTF-16.

Fix chosen (option 2, one fix): `job/register_verify_bridge.py`.
- Reads the UTF-8 XML, rewrites the declaration to `encoding="UTF-16"`, writes a UTF-16 LE + BOM temp copy, runs `schtasks /create /tn <name> /xml <tmp>`, deletes the temp copy.
- `--name` (default CitationEngineVerifyBridge), `--start-boundary` (override StartBoundary, used for the throwaway proof), `--force` (adds /f; off by default so a live task is never overwritten by accident), `--dry-run` (print the command, run nothing).
- Repo XML stays UTF-8 (diff-friendly, no .gitattributes needed). Description updated to name the script.
- Other task XMLs: only `job/verify_bridge_task.xml` is in the repo (weekly/postcards are .cmd only), so nothing else to fix.

Tests (`tests/register_verify_bridge_test.py`, added to CI): output is FF FE BOM and decodes as UTF-16 with a UTF-16 declaration; start override works and default leaves XML untouched; command has no /f unless --force; temp file removed even when schtasks fails; Description names the script; script never touches the live name when given another.

Evidence after: register under CEVerifyBridgeRegTest (StartBoundary 2030), query, delete. Live task not touched. CI green at head.
No portal write, no Directory, no spend.
