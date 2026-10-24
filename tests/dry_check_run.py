"""Read-only dry check of the permalink gate over a saved run. No network, no DB, no portal, no writes.
Usage: python tests/dry_check_run.py <rows.jsonl>
Prints found counts per business before and after the gate, and each row that flipped to couldnt_check.
"""
import json, os, sys
from collections import Counter
HERE = os.path.dirname(os.path.abspath(__file__))
import tempfile as _tf; os.environ["CE_RUNS"] = _tf.mkdtemp(prefix="ce-runs-")  # run.py makes dirs on import; never the real runs folder
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import run as jobrun  # noqa: E402
import judge  # noqa: E402
from cfg import DIRS, IDENT  # noqa: E402


def main(path):
    rows = jobrun.load_rows(path)
    unsearch = set(IDENT.get("UNSEARCHABLE", []))
    before = judge.combine(rows, DIRS, unsearch)
    comb, checks = jobrun.build(rows, {}, {})
    nb = Counter(b for (b, d), (r, s) in before.items() if r == "found")
    na = Counter(c["biz"] for c in checks if c["result"] == "found")
    print("found rows per business (before -> after the gate)")
    for b in sorted(set(nb) | set(na)):
        print("  %s: %d -> %d" % (b, nb[b], na[b]))
    print("rows that flipped found -> couldnt_check (no permalink):")
    n = 0
    for c in checks:
        if c.get("_rejected_url") is not None or c.get("note") == "no permalink":
            n += 1
            print("  %s %-22s %-10s rejected=%s (%s)" % (c["biz"], c["directory"], "", c.get("_rejected_url"), c.get("_permalink_reason")))
    print("flipped total:", n)
    print("kept found with unverified host:", [(c["biz"], c["directory"]) for c in checks if c.get("_permalink_unverified")])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
