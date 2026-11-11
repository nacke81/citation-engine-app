# Killing the child does not end the parent (t_15f7ec86)

`build_chrome.py --stop` killed the Chrome on port 9333. The python that started that Chrome is its parent, so it survived and `--seconds 0` looped on a timer that could never fire. Five trees sat idle for 26 h.

Rule: any long-lived loop must (1) check that the thing it exists for is still alive, (2) have a hard ceiling that a lease can extend but nothing else can, and (3) leave a pidfile so the stop command can name the loop itself, not only its child. Pair every "start" with a "reap" that finds strays by command line and age.
Test the kill path with a fake process list holding the parent AND the child, not only the child.
