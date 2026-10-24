"""Writes the saved-HTML fixtures for tests/resolver_test.py into tests/fixtures/resolver/. Placeholder identity only (tests/test_identity.json).
One search page and one listing page per in-scope Directory, shaped after what Edith saw (2026-10-22). No live traffic. Run: python tests/build_resolver_fixtures.py
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fixtures", "resolver")
os.makedirs(OUT, exist_ok=True)

FILL = " ".join("Local business information, hours, maps, reviews and directions for the area. " for _ in range(12))
NAME, STREET, CITY, PHONE = "Alder Care Consulting &amp; Solutions", "100 Example Dr", "Exampleton, KY 40000", "(502) 555-0101"
DECOY, DSTREET, DPHONE = "Pine Hollow Cleaning Services", "9 Other Rd", "(502) 555-0177"

HOSTS = {
    "yellowpages.com": dict(card="https://www.yellowpages.com/exampleton-ky/mip/alder-care-consltng-solutions-123456789", decoy="https://www.yellowpages.com/exampleton-ky/mip/pine-hollow-cleaning-111111111",
                           search_title="Results for alder in Exampleton, KY", listing_title="Alder Care Consltng-Solutions - Exampleton, KY 40000", nxt="https://www.yellowpages.com/search?search_terms=alder&geo_location_terms=Exampleton%2C+KY&page=2", pname="Alder Care Consltng-Solutions"),
    "superpages.com": dict(card="https://www.superpages.com/exampleton-ky/bpp/alder-care-consltng-solutions-123456789", decoy="https://www.superpages.com/exampleton-ky/bpp/pine-hollow-cleaning-111111111",
                          search_title="Results for alder in Exampleton, KY", listing_title="Alder Care Consltng-Solutions - Exampleton, KY 40000", nxt="", pname="Alder Care Consltng-Solutions"),
    "dexknows.com": dict(card="https://www.dexknows.com/exampleton-ky/bp/alder-care-consltng-solutions-123456789", decoy="https://www.dexknows.com/exampleton-ky/bp/pine-hollow-cleaning-111111111",
                        search_title="Results for alder in Exampleton, KY", listing_title="Alder Care Consltng-Solutions - Exampleton, KY 40000", nxt="", pname="Alder Care Consltng-Solutions"),
    "google.com": dict(card="https://www.google.com/maps/place/Alder+Care+Consulting+%26+Solutions/@1.5,1.5,17z/data=!3m1!4b1", decoy="https://www.google.com/maps/place/Pine+Hollow+Cleaning/@2.5,2.5,17z/data=!3m1!4b1",
                      search_title="Alder Care Consulting Exampleton KY - Google Maps", listing_title="Alder Care Consulting &amp; Solutions - Google Maps", nxt="", pname="Alder Care Consulting &amp; Solutions"),
    "merchantcircle.com": dict(card="https://www.merchantcircle.com/alder-care-consulting-solutions-exampleton-ky", decoy="https://www.merchantcircle.com/ky-exampleton/health-and-beauty/care-providers/assisted-living",
                              search_title="Results for alder near Exampleton, KY", listing_title="Map and Directions to Alder Care Consulting &amp; Solutions in Exampleton, KY 40000", nxt="", pname="Alder Care Consulting &amp; Solutions"),
    "hotfrog.com": dict(card="https://www.hotfrog.com/company/AJxxxxxxxxxxxxxxxxxxxx/alder-care-consulting-solutions/exampleton/hospice-home-health-care", decoy="https://www.hotfrog.com/company/AJyyyyyyyyyyyyyyyyyyyy/pine-hollow-cleaning/exampleton/cleaning",
                       search_title="Top 1 Best alder in Exampleton, KY - Hotfrog", listing_title="Alder Care Consulting &amp; Solutions - Hotfrog US Business Directory", nxt="", pname="Alder Care Consulting &amp; Solutions"),
    "n49.com": dict(card="https://www.n49.com/biz/1234567/alder-care-consulting-solutions-exampleton/", decoy="https://www.n49.com/biz/7654321/pine-hollow-cleaning-exampleton/",
                   search_title="1 results for: Alder Care in Exampleton", listing_title="Alder Care Consulting &amp; Solutions - Exampleton, KY - n49", nxt="", pname="Alder Care Consulting &amp; Solutions"),
    "yellowbot.com": dict(card="https://www.yellowbot.com/alder-care-consulting-solutions-exampleton-ky.html", decoy="https://www.yellowbot.com/pine-hollow-cleaning-exampleton-ky.html",
                         search_title="Results for alder near Exampleton, KY", listing_title="Alder Care Consulting &amp; Solutions - Exampleton, KY - YellowBot", nxt="", pname="Alder Care Consulting &amp; Solutions"),
    "cybo.com": dict(card="https://www.cybo.com/US-biz/alder-care-consulting-solutions", decoy="https://www.cybo.com/US/exampleton/",
                    search_title="Businesses in Exampleton, Kentucky - Cybo", listing_title="Alder Care Consulting &amp; Solutions - Cybo", nxt="", pname="Alder Care Consulting &amp; Solutions"),
}


def li(href, name, street, phone):
    return '<li class="card"><h2><a href="%s">%s</a></h2><p>%s</p><p>%s</p><p>%s</p></li>' % (href, name, street, CITY, phone)


def search_html(h):
    cards = li(h["decoy"], DECOY, DSTREET, DPHONE) + li(h["card"], h["pname"], STREET, PHONE)
    nxt = '<a href="%s">Next</a>' % h["nxt"] if h["nxt"] else ""
    return "<html><head><title>%s</title></head><body><h1>%s</h1><ul>%s</ul>%s<p>%s</p></body></html>" % (h["search_title"], h["search_title"], cards, nxt, FILL)


def listing_html(h):
    return "<html><head><title>%s</title></head><body><h1>%s</h1><p>%s</p><p>%s</p><p>Phone %s</p><p>%s</p></body></html>" % (
        h["listing_title"], h["pname"], STREET, CITY, PHONE, FILL)


if __name__ == "__main__":
    for d, h in HOSTS.items():
        k = d.split(".")[0]
        open(os.path.join(OUT, "%s-search.html" % k), "w", encoding="utf-8", newline="\n").write(search_html(h))
        open(os.path.join(OUT, "%s-listing.html" % k), "w", encoding="utf-8", newline="\n").write(listing_html(h))
    print("wrote", len(HOSTS) * 2, "fixtures to", OUT)
