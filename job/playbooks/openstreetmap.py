"""openstreetmap.org node-create playbook, scripted from batch 11 (t_cc3bafef, 2026-10-26): a node placed at the client's verified GBP pin, NAP tags only.

Creates ONE node through the OSM API 0.6 (changeset -> node -> close) instead of the iD editor:
  * Tags are NAP only: office=consulting, name, addr:housenumber, addr:street, addr:city, addr:state, addr:postcode, phone, website. Nothing else.
  * lat/lng are REQUIRED INPUTS (the exact pin read from the verified Google Business Profile). They are never defaulted, geocoded, interpolated or guessed;
    a missing, non-numeric or out-of-range value stops the run. A residential address with no building node is NOT pinned on a street-interpolated point.
  * Auth: a bearer token from the env var OSM_ACCESS_TOKEN (OAuth2, scope write_api) created by hand for the existing account (vault item `<client> - <site>`).
    It is read at call time, sent only to api.openstreetmap.org, and never printed or returned. Account creation and the email confirm stay manual.
  * Changeset comment: "survey/owner" (Mike ruling 10/26). Changeset is closed even when the node call fails.
  * Dry run builds the exact XML bodies and makes no request. --live is refused here (a Directory write needs a Nate card).
Every network edge is injectable (`http`), so tests make no call.

  python job/playbooks/openstreetmap.py --dry-run --lat 38.1234567 --lng -85.1234567 --housenumber 100 --street "Example Drive" --city Exampleton --state KY --postcode 40000 --phone "+1 502 555 0101" --website https://alder.example --name "Alder Care Consulting & Solutions"
"""
import os, re, sys
from xml.sax.saxutils import quoteattr

API = "https://api.openstreetmap.org"
COMMENT = "survey/owner"
CREATED_BY = "citation-engine playbook"
TAG_ORDER = ("office", "name", "addr:housenumber", "addr:street", "addr:city", "addr:state", "addr:postcode", "phone", "website")
STEPS = ("validate", "open_changeset", "create_node", "close_changeset", "read_back")


class PlaybookError(Exception):
    pass


def check_coord(lat, lng):
    """lat/lng must be given by the caller as numbers. No default, no rounding, no guess."""
    for nm, v, lim in (("lat", lat, 90.0), ("lng", lng, 180.0)):
        if v is None or isinstance(v, bool) or (isinstance(v, str) and not v.strip()): raise PlaybookError("%s is required (exact pin from the verified GBP); it is never guessed" % nm)
        try: f = float(v)
        except (TypeError, ValueError): raise PlaybookError("%s is not a number: %r" % (nm, v))
        if f != f or abs(f) > lim: raise PlaybookError("%s %r is out of range" % (nm, v))
        if f == 0.0: raise PlaybookError("%s is 0: that is the null-island placeholder, not a pin" % nm)
    return float(lat), float(lng)


def nap_tags(*, name, housenumber, street, city, state, postcode, phone, website):
    tags = {"office": "consulting", "name": name, "addr:housenumber": housenumber, "addr:street": street, "addr:city": city, "addr:state": state, "addr:postcode": postcode, "phone": phone, "website": website}
    for k, v in tags.items():
        if not (v or "").strip(): raise PlaybookError("tag %s is empty; NAP comes from the approved identity" % k)
    if not re.match(r"^https://[^\s/]+", tags["website"]): raise PlaybookError("website must start with https://")
    if not re.match(r"^\+1[ \d]{10,14}$", tags["phone"]): raise PlaybookError("phone tag must be international: '+1 502 555 0101'")
    assert tuple(tags) == TAG_ORDER
    return tags


def _tag_xml(tags): return "".join("<tag k=%s v=%s/>" % (quoteattr(k), quoteattr(v)) for k, v in tags.items())


def changeset_xml(): return "<osm><changeset>%s</changeset></osm>" % _tag_xml({"comment": COMMENT, "created_by": CREATED_BY})


def node_xml(changeset_id, lat, lng, tags):
    return '<osm><node changeset="%d" lat="%.7f" lon="%.7f">%s</node></osm>' % (int(changeset_id), lat, lng, _tag_xml(tags))


def token(env=None):
    t = (os.environ if env is None else env).get("OSM_ACCESS_TOKEN")
    if not t: raise PlaybookError("OSM_ACCESS_TOKEN is not set")
    return t


def plan(*, lat, lng, **nap):
    """Dry-run output: what would be sent. No request, no token read."""
    la, lo = check_coord(lat, lng)
    tags = nap_tags(**nap)
    return {"steps": list(STEPS), "api": API, "changeset": changeset_xml(), "node": node_xml(0, la, lo, tags), "tags": tags, "lat": la, "lng": lo}


def run(http, *, lat, lng, env=None, **nap):
    """http(method, url, body, headers) -> (status, text). Returns {changeset, node_id, url, tags}. Raises PlaybookError; always tries to close the changeset."""
    la, lo = check_coord(lat, lng)
    tags = nap_tags(**nap)
    h = {"Authorization": "Bearer " + token(env), "Content-Type": "text/xml"}
    st, cs = http("PUT", API + "/api/0.6/changeset/create", changeset_xml(), h)
    if st != 200 or not cs.strip().isdigit(): raise PlaybookError("changeset create failed (HTTP %s)" % st)
    try:
        st, nid = http("PUT", API + "/api/0.6/node/create", node_xml(int(cs), la, lo, tags), h)
        if st != 200 or not nid.strip().isdigit(): raise PlaybookError("node create failed (HTTP %s)" % st)
    finally:
        http("PUT", API + "/api/0.6/changeset/%s/close" % cs.strip(), "", h)
    return {"changeset": int(cs), "node_id": int(nid), "url": "https://www.openstreetmap.org/node/%d" % int(nid), "tags": tags}


def read_back(http, node_id):
    """Public read of the stored tags (no auth). Returns the tag dict, or raises."""
    import json
    st, txt = http("GET", API + "/api/0.6/node/%d.json" % int(node_id), None, {})
    if st != 200: raise PlaybookError("read back failed (HTTP %s)" % st)
    return json.loads(txt)["elements"][0].get("tags") or {}


def main(argv=None):
    import argparse
    a = argparse.ArgumentParser(description="openstreetmap.org node-create playbook (API 0.6, NAP tags only)")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true"); g.add_argument("--live", action="store_true")
    for k in ("lat", "lng", "name", "housenumber", "street", "city", "state", "postcode", "phone", "website"): a.add_argument("--" + k, default=None)
    n = a.parse_args(argv)
    if n.live: raise SystemExit("--live needs a Nate card (writes to OpenStreetMap); wire it in the calling scratch file (run(http, ...)).")
    try:
        p = plan(lat=n.lat, lng=n.lng, name=n.name or "", housenumber=n.housenumber or "", street=n.street or "", city=n.city or "", state=n.state or "", postcode=n.postcode or "", phone=n.phone or "", website=n.website or "")
    except PlaybookError as e:
        print("REFUSED: %s" % e); return 2
    print("steps: %s\napi: %s\nchangeset comment: %s\npin: %.7f, %.7f\nnode: %s" % (" -> ".join(p["steps"]), p["api"], COMMENT, p["lat"], p["lng"], p["node"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
