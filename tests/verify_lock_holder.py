"""Helper for tests/verify_bridge_test.py: takes the per-tenant send lock, prints HELD, then sleeps until it is killed.
Proves the OS drops the lock when a send run dies without any cleanup. Usage: python tests/verify_lock_holder.py <client_id>"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import os as _fo; _fo.environ["CE_PORTAL_ENV"] = _fo.path.join(_fo.path.dirname(_fo.path.abspath(__file__)), "no-such-portal.env")  # t_2ddc7067: fail closed, never the prod portal
import verify_bridge as B

with B.tenant_lock(sys.argv[1]) as got:
    print("HELD" if got else "BUSY", flush=True)
    if got:
        time.sleep(120)
