"""Strip Google API keys from saved HTML fixtures (t_6df6203a).

Run after saving a page into tests/fixtures/:  python tests/fixture_scrub.py tests/fixtures/<page>.html
Third-party pages embed their own browser keys (Maps/Places); this repo is public, so none may be committed."""
import re, sys

PATTERN = re.compile(r"AIza[0-9A-Za-z_-]{35}")
PLACEHOLDER = "REDACTED_GOOGLE_KEY"


def scrub(text):
    return PATTERN.sub(PLACEHOLDER, text)


def write_fixture(path, text, newline=None):
    """The one way a builder writes a fixture: scrub first, then write. Returns the scrubbed text."""
    out = scrub(text)
    with open(path, "w", encoding="utf-8", newline=newline) as f:
        f.write(out)
    return out


def main(paths):
    for p in paths:
        with open(p, encoding="utf-8", newline="") as f:
            t = f.read()
        n = len(PATTERN.findall(t))
        if n:
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(scrub(t))
        print("%s: %d key(s) redacted" % (p, n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
