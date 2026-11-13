# Lesson: "found one part" must not switch off the other source for the missing parts (t_69102cc9)

The NAP comparator read the page's own structured address only when the text showed NO street. A page that showed the street (and nothing else of the address) therefore never had its JSON-LD city / state / ZIP read, and a correct listing stayed `nap-incomplete`.

Rule: when a reader has two sources, a hit in the first source decides only what that source shows. Fill what is genuinely missing from the second source, but only from the same entity (exact name), only when the part both sources share (the street) agrees, and never let the second source overwrite a value the first one showed.

Test it from the real captured page (sanitized to the test identity), with the controls that make the rule safe: same text without markup stays incomplete, wrong structured values mismatch, a wrong visible value beats correct JSON-LD, a different entity (directory HQ) cannot complete it, and a mutation that removes the supplement must fail the real-page test. Prove the bug from the saved page on the old code before touching it.
