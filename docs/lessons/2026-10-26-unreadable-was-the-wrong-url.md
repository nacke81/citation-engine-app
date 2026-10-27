# Lesson 2026-10-26: "page not readable" was mostly the wrong URL, not a weak reader

Card t_3ac43137. Of the six rows batch 13 could not read, the real-Chrome reader rendered all six fine; four were pointed at an owner view, an add form or a login redirect, and two Directories (localsolution, listyourbusiness) had a public search that listed us but no search builder. Fixing the reader alone would have left them "not readable".

- Before blaming the reader, print what URL it was given and what the rendered page says (login? 404? add form?). A rendered page with no listing is a verdict (`not-public`), not an error.
- A generic "looks like search" URL filter can reject a Directory's real listing path (listyourbusiness lists under /category/). Give such a Directory an explicit permalink pattern and an exemption.
- Store the URL the Directory shows at submit time; recovering it later costs a search per row.
