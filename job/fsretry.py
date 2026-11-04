"""os.replace with a short bounded retry on PermissionError (Windows: Defender/indexer/lingering handle can briefly lock the target).
POSIX never raises here, so behavior is unchanged there. Same logic as transitions._replace_retry."""
import os, time


def replace_retry(src, dst, tries=12, delay=0.05):
    for i in range(tries):
        try:
            os.replace(src, dst); return
        except PermissionError:
            if i == tries - 1: raise
            time.sleep(delay * (i + 1))
