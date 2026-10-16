import re
from urllib.parse import quote_plus as qp
import json, os
IDENTITY_PATH = os.environ.get("CE_IDENTITY") or os.path.expandvars("%LOCALAPPDATA%/citation-engine/identity.json")
IDENT = json.load(open(IDENTITY_PATH, encoding="utf-8"))   # identity lives outside the repo; tests point CE_IDENTITY at placeholders
BIZ = IDENT["BIZ"]
# 25 directories in truth-set order
DIRS = ["google.com","maps.apple.com","bing.com","facebook.com","yelp.com","bbb.org","mapquest.com","yellowpages.com","superpages.com",
 "dexknows.com","nextdoor.com","manta.com","merchantcircle.com","hotfrog.com","foursquare.com","chamberofcommerce.com","cybo.com",
 "bizapedia.com","brownbook.net","localstack.com","n49.com","yellowbook.com","yellowbot.com","ezlocal.com","showmelocal.com"]
def S(b): return BIZ[b]
def lc(b): return S(b)["city"].lower().replace(" ","-")
def st_full(b): return {"KY":"kentucky","TN":"tennessee"}[S(b)["st"]]
# method 1: directory's own site search URL
def search_url(d,b):
    x=S(b); n=qp(x["name"]); c=qp(f'{x["city"]}, {x["st"]}'); sn=qp(x["short"])
    return {
     "google.com": f"https://www.google.com/maps/search/{qp(x['name']+' '+x['city']+' '+x['st'])}",
     "maps.apple.com": f"https://maps.apple.com/?q={n}&near={c}",
     "bing.com": f"https://www.bing.com/maps/search?q={qp(x['name']+' '+x['city']+' '+x['st'])}",
     "facebook.com": f"https://www.facebook.com/search/pages?q={n}%20{qp(x['city'])}",
     "yelp.com": f"https://www.yelp.com/search?find_desc={n}&find_loc={c}",
     "bbb.org": f"https://www.bbb.org/search?find_text={n}&find_loc={c}",
     "mapquest.com": f"https://www.mapquest.com/search/results?query={n}&boundingBox=&page=0&q={n}%20{qp(x['city'])}",
     "yellowpages.com": f"https://www.yellowpages.com/search?search_terms={n}&geo_location_terms={c}",
     "superpages.com": f"https://www.superpages.com/search?search_terms={n}&geo_location_terms={c}",
     "dexknows.com": f"https://www.dexknows.com/search?search_terms={n}&geo_location_terms={c}",
     "nextdoor.com": f"https://nextdoor.com/search/?query={n}",
     "manta.com": f"https://www.manta.com/search?search={n}&search_location={c}",
     "merchantcircle.com": f"https://www.merchantcircle.com/search?q={n}&qn={qp(x['city']+' '+x['st'])}",
     "hotfrog.com": f"https://www.hotfrog.com/search/{x['st'].lower()}/{lc(b)}/{qp(x['short'].lower())}",
     "foursquare.com": f"https://foursquare.com/explore?mode=url&near={c}&q={n}",
     "chamberofcommerce.com": f"https://www.chamberofcommerce.com/search?what={n}&where={c}",
     "cybo.com": f"https://www.cybo.com/US/search/?q={n}&l={c}",
     "bizapedia.com": f"https://www.bizapedia.com/search.aspx?q={n}",
     "brownbook.net": f"https://www.brownbook.net/search/{lc(b)}-{x['st'].lower()}/{qp(x['short'].lower())}/",
     "localstack.com": f"https://localstack.com/search?q={n}",
     "n49.com": f"https://www.n49.com/search/?q={n}&where={c}",
     "yellowbook.com": f"https://www.yellowbook.com/s/{qp(x['short'].lower())}/{lc(b)}-{x['st'].lower()}/",
     "yellowbot.com": f"https://www.yellowbot.com/search?q={n}&location={c}",
     "ezlocal.com": f"https://ezlocal.com/search?q={n}&loc={c}",
     "showmelocal.com": f"https://www.showmelocal.com/search.aspx?q={n}&where={c}",
    }[d]
# method 2: URL pattern (slug from name + city), may return several guesses
def pattern_urls(d,b):
    x=S(b); s=x["slug"]; c=lc(b); st=x["st"].lower(); sf=st_full(b); sh=x["short"].lower().replace(" ","-").replace("&","")
    return {
     "google.com": [], "maps.apple.com": [], "bing.com": [],
     "facebook.com": [f"https://www.facebook.com/{x['short'].replace(' ','')}/"],
     "yelp.com": [f"https://www.yelp.com/biz/{s}-{c}", f"https://www.yelp.com/biz/{sh}-{c}"],
     "bbb.org": [],
     "mapquest.com": [f"https://www.mapquest.com/us/{sf}/{s}", f"https://www.mapquest.com/us/{sf}/{sh}"],
     "yellowpages.com": [f"https://www.yellowpages.com/{c}-{st}/{s}"],
     "superpages.com": [f"https://www.superpages.com/{c}-{st}/{s}"],
     "dexknows.com": [f"https://www.dexknows.com/{c}-{st}/{s}"],
     "nextdoor.com": [f"https://nextdoor.com/pages/{s}-{c}-{st}/"],
     "manta.com": [f"https://www.manta.com/c/{s}"],
     "merchantcircle.com": [f"https://www.merchantcircle.com/{s}-{c}-{st}", f"https://www.merchantcircle.com/{s}1-{c}-{st}", f"https://www.merchantcircle.com/{sh}-{c}-{st}"],
     "hotfrog.com": [],
     "foursquare.com": [],
     "chamberofcommerce.com": [],
     "cybo.com": [f"https://www.cybo.com/US-biz/{s}"],
     "bizapedia.com": [],
     "brownbook.net": [],
     "localstack.com": [],
     "n49.com": [],
     "yellowbook.com": [],
     "yellowbot.com": [f"https://www.yellowbot.com/{s}-{c}-{st}.html"],
     "ezlocal.com": [],
     "showmelocal.com": [],
    }[d]
# method 3: phone search URL (one per phone)
def phone_urls(d,b,ph):
    p10=ph; f=f"{ph[:3]}-{ph[3:6]}-{ph[6:]}"
    return {
     "yellowpages.com": f"https://www.yellowpages.com/search?search_terms={p10}",
     "superpages.com": f"https://www.superpages.com/search?search_terms={p10}",
     "dexknows.com": f"https://www.dexknows.com/search?search_terms={p10}",
     "mapquest.com": f"https://www.mapquest.com/search/results?query={p10}",
     "yelp.com": f"https://www.yelp.com/search?find_desc={p10}",
     "manta.com": f"https://www.manta.com/search?search={p10}",
     "merchantcircle.com": f"https://www.merchantcircle.com/search?q={p10}",
     "hotfrog.com": f"https://www.hotfrog.com/search?q={p10}",
     "bbb.org": f"https://www.bbb.org/search?find_text={p10}",
     "chamberofcommerce.com": f"https://www.chamberofcommerce.com/search?what={p10}",
     "n49.com": f"https://www.n49.com/search/?q={f}",
     "yellowbot.com": f"https://www.yellowbot.com/search?q={p10}",
     "facebook.com": f"https://www.facebook.com/search/pages?q={f}",
     "bing.com": f"https://www.bing.com/maps/search?q={p10}",
    }.get(d)
