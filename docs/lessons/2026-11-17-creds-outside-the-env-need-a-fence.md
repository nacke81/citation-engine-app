# Lesson: creds read from a pointer file are invisible to CI, so fence the pointer, not the process env (t_2ddc7067)

Two tests passed in CI for weeks while a local run called `B.main(...)`, which builds the real portal client from `CE_PORTAL_ENV` or the pointer file to the prod `.env.prod.local`, and sent a real `POST rpc/claim_code_request`. CI has no pointer file, so it never saw it. It is the same class as the Directory DB fixture rows (t_be2150cd): a secret outside the process env makes "green in CI" say nothing about a local run.

Rule: for every credential that is not read from the process env, set the pointer to a path that does not exist before the first import of the code that reads it, in every test file, and add an ast scan to CI that names the files that do not. Prove it with a network trap (log + refuse non-loopback) over the whole CI list, not only the two files found: the count at head must be 0.
