"""Read-and-clear for client-submitted postcard codes.

The portal stores a code the client types in citation_postcard_code, a table only the
service role can reach. consume() calls the SECURITY DEFINER function consume_postcard_code,
which deletes the row and returns the code in one statement, so a code can be used once and
is gone afterwards. The engine enters the returned value at the Directory and drops it.

Rules this module holds:
  * The code is never logged, printed, written to a queue file, a run log, history, or
    Activities. It is returned to the caller in memory and nowhere else.
  * Errors name the verification id only (Portal._scrub also masks the service key).
  * A code that is missing or already used returns None; the caller treats that as
    "client has not sent it yet" and does not retry-loop.
"""
import re

RPC_PATH = "rpc/consume_postcard_code"
_CODE_RE = re.compile(r"^[A-Za-z0-9]{4,12}$")


class PostcardCodeError(Exception):
    pass


def consume(portal, verification_id):
    """Return the postcard code once and clear it, or None if none is waiting."""
    if not verification_id or not isinstance(verification_id, str):
        raise PostcardCodeError("verification id required")
    try:
        got = portal.call("POST", RPC_PATH, {"p_verification_id": verification_id})
    except Exception as e:  # PortalWriteError text is already scrubbed of the key and carries no body
        raise PostcardCodeError("consume_postcard_code failed for %s: %s" % (verification_id, type(e).__name__))
    if got in (None, ""):
        return None
    if not isinstance(got, str) or not _CODE_RE.match(got):
        raise PostcardCodeError("consume_postcard_code returned an unexpected shape for %s" % verification_id)
    return got
