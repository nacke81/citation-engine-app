# Lesson: on a public repo, the secret check must run before the push, not only in CI (t_6df6203a)

The first fix put the Google-key guard only in CI. CI runs after a push, and on a public repo the push is the leak. The check agents run before pushing (`leak_check.py`) passed with the real key present. Put every secret shape in the pre-push check, plant a control for it, and route every save path through the scrub so the key never reaches disk.
