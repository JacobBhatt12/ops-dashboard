"""Import small businesses from Overture Maps Places.

Overture Maps (overturemaps.org) is an open, monthly-updated map dataset
built from Meta, Microsoft and other sources, published as GeoParquet on a
public S3 bucket under the CDLA-Permissive-2.0 licence. No API key, no
account, no per-call cost. DuckDB reads only the columns and row groups a
query needs, so pulling one state is a few hundred MB of traffic, not the
whole planet.

Filters applied at the source:
  * inside the state's bounding box AND address region is that state
  * not a branded chain (brand IS NULL)
  * not permanently closed, confidence >= min_confidence
  * has a website or an email (no way to email anyone else)
  * category matches one of the chosen small-business groups
"""
from __future__ import annotations

import os
import re
import urllib.request
from urllib.parse import urlparse

BUCKET_HTTP = "https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com"
FALLBACK_RELEASE = "2026-09-23.1"

# Keyword groups matched against the place's category text. Substring
# matching on purpose: Overture's category names shift between releases
# ("hair_salon" vs "beauty_salon"), and a keyword survives that.
CATEGORY_GROUPS = {
    "home_services": ("Home services", [
        "roof", "plumb", "hvac", "heating", "air_condition", "electrician", "landscap",
        "lawn", "pool", "pest", "cleaning", "painting", "painter", "remodel", "contractor",
        "handyman", "flooring", "fence", "pressure_wash", "junk", "moving", "mover",
        "tree_service", "garage_door", "locksmith", "solar", "gutter", "carpet",
        "window_wash", "irrigation", "paving", "concrete", "masonry", "cabinet",
        "countertop", "home_improvement", "appliance_repair", "septic", "drywall",
    ]),
    "beauty": ("Beauty & salons", [
        "salon", "barber", "nail", "massage", "tattoo", "esthetic", "eyelash", "lash",
        "beauty", "tanning", "makeup", "waxing", "day_spa", "skin_care", "brow",
    ]),
    "fitness": ("Fitness & trainers", [
        "gym", "fitness", "personal_trainer", "trainer", "yoga", "pilates",
        "martial_arts", "boxing", "crossfit", "dance", "karate", "jiu_jitsu",
    ]),
    "health": ("Health & wellness", [
        "dentist", "dental", "orthodont", "chiropract", "physical_therap", "medical_spa",
        "med_spa", "optometr", "acupunct", "counsel", "psychotherap", "nutrition",
        "wellness", "physiotherap", "podiatr", "dermatolog",
    ]),
    "auto": ("Auto services", [
        "auto_repair", "auto_body", "car_wash", "detailing", "tire_", "tires", "mechanic",
        "towing", "auto_glass", "oil_change", "transmission",
    ]),
    "pets": ("Pets", ["pet_groom", "pet_sit", "dog_walk", "dog_train", "veterinar", "pet_board", "kennel"]),
    "pro_services": ("Professional services", [
        "lawyer", "attorney", "law_firm", "accountant", "accounting", "tax_", "insurance",
        "photograph", "videograph", "wedding", "event_plan", "florist", "notary",
        "bookkeep", "financial_advis", "mortgage", "real_estate",
    ]),
    "food": ("Food & drink", [
        "restaurant", "cafe", "coffee", "bakery", "catering", "food_truck", "dessert",
        "ice_cream", "juice", "bar_", "brewery", "pizza",
    ]),
    "retail": ("Local retail", [
        "boutique", "clothing", "jewelry", "gift_shop", "furniture", "bike", "bicycle",
        "flower", "thrift", "antique", "bridal",
    ]),
}

# Never import these even if a keyword matches.
EXCLUDE = [
    "charging", "atm", "gas_station", "government", "school", "university", "church",
    "hospital", "park", "parking", "post_office", "bank", "credit_union", "airport",
    "hotel", "motel", "apartment", "library", "police", "fire_station", "cemetery",
]

# Website domains that are not the business's own site.
SOCIAL_DOMAINS = (
    "facebook.com", "fb.com", "instagram.com", "yelp.com", "google.com", "goo.gl",
    "linkedin.com", "twitter.com", "x.com", "tiktok.com", "youtube.com", "nextdoor.com",
    "bbb.org", "yellowpages.com", "angi.com", "homeadvisor.com", "thumbtack.com",
    "booksy.com", "vagaro.com", "styleseat.com", "mindbodyonline.com", "square.site",
    "doordash.com", "ubereats.com", "grubhub.com", "opentable.com", "toasttab.com",
)

# Generous bounding boxes (lon_min, lat_min, lon_max, lat_max). The region
# filter does the exact cut; the box only lets DuckDB skip row groups.
STATE_BBOX = {
    "AL": (-88.5, 30.1, -84.9, 35.0), "AK": (-180.0, 51.0, -129.0, 71.5),
    "AZ": (-114.9, 31.3, -109.0, 37.0), "AR": (-94.7, 33.0, -89.6, 36.5),
    "CA": (-124.5, 32.5, -114.1, 42.0), "CO": (-109.1, 37.0, -102.0, 41.0),
    "CT": (-73.8, 40.9, -71.8, 42.1), "DE": (-75.8, 38.4, -75.0, 39.9),
    "DC": (-77.2, 38.8, -76.9, 39.0), "FL": (-87.7, 24.4, -80.0, 31.0),
    "GA": (-85.7, 30.3, -80.8, 35.0), "HI": (-160.3, 18.9, -154.8, 22.3),
    "ID": (-117.3, 41.9, -111.0, 49.0), "IL": (-91.6, 36.9, -87.0, 42.5),
    "IN": (-88.1, 37.7, -84.8, 41.8), "IA": (-96.7, 40.3, -90.1, 43.5),
    "KS": (-102.1, 36.9, -94.6, 40.0), "KY": (-89.6, 36.5, -81.9, 39.2),
    "LA": (-94.1, 28.9, -88.8, 33.0), "ME": (-71.1, 43.0, -66.9, 47.5),
    "MD": (-79.5, 37.9, -75.0, 39.8), "MA": (-73.5, 41.2, -69.9, 42.9),
    "MI": (-90.5, 41.7, -82.1, 48.3), "MN": (-97.3, 43.5, -89.5, 49.4),
    "MS": (-91.7, 30.1, -88.1, 35.0), "MO": (-95.8, 35.9, -89.1, 40.6),
    "MT": (-116.1, 44.3, -104.0, 49.0), "NE": (-104.1, 40.0, -95.3, 43.0),
    "NV": (-120.0, 35.0, -114.0, 42.0), "NH": (-72.6, 42.7, -70.6, 45.3),
    "NJ": (-75.6, 38.9, -73.9, 41.4), "NM": (-109.1, 31.3, -103.0, 37.0),
    "NY": (-79.8, 40.5, -71.8, 45.0), "NC": (-84.3, 33.8, -75.4, 36.6),
    "ND": (-104.1, 45.9, -96.5, 49.0), "OH": (-84.8, 38.4, -80.5, 42.0),
    "OK": (-103.0, 33.6, -94.4, 37.0), "OR": (-124.6, 41.9, -116.4, 46.3),
    "PA": (-80.5, 39.7, -74.7, 42.3), "RI": (-71.9, 41.1, -71.1, 42.0),
    "SC": (-83.4, 32.0, -78.5, 35.2), "SD": (-104.1, 42.5, -96.4, 45.9),
    "TN": (-90.3, 35.0, -81.6, 36.7), "TX": (-106.7, 25.8, -93.5, 36.5),
    "UT": (-114.1, 37.0, -109.0, 42.0), "VT": (-73.4, 42.7, -71.5, 45.0),
    "VA": (-83.7, 36.5, -75.2, 39.5), "WA": (-124.8, 45.5, -116.9, 49.0),
    "WV": (-82.6, 37.2, -77.7, 40.6), "WI": (-92.9, 42.5, -86.8, 47.1),
    "WY": (-111.1, 41.0, -104.1, 45.0),
}
PAD = 0.3


def latest_release(timeout=20) -> str:
    """Newest release folder on the public bucket (anonymous S3 list)."""
    url = f"{BUCKET_HTTP}/?list-type=2&prefix=release/&delimiter=/"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        xml = resp.read().decode("utf-8", "replace")
    found = re.findall(r"<Prefix>release/([^/<]+)/</Prefix>", xml)
    found = [f for f in found if re.match(r"^\d{4}-\d{2}-\d{2}", f)]
    if not found:
        raise RuntimeError("No Overture releases listed on the bucket")
    return sorted(found)[-1]


def normalize_website(url: str | None) -> tuple[str | None, str | None]:
    """Return (url_with_scheme, bare_domain) or (None, None)."""
    if not url:
        return None, None
    u = url.strip()
    if not u:
        return None, None
    if not re.match(r"^https?://", u, re.I):
        u = "http://" + u
    try:
        host = (urlparse(u).hostname or "").lower()
    except ValueError:
        return None, None
    if not host or "." not in host:
        return None, None
    if host.startswith("www."):
        host = host[4:]
    return u, host


def is_social(domain: str | None) -> bool:
    return bool(domain) and any(domain == d or domain.endswith("." + d) for d in SOCIAL_DOMAINS)


def _keyword_regex(groups: list[str]) -> str:
    words = []
    for g in groups:
        if g in CATEGORY_GROUPS:
            words += CATEGORY_GROUPS[g][1]
    if not words:
        raise ValueError("Pick at least one business category")
    return "(" + "|".join(re.escape(w) for w in sorted(set(words))) + ")"


def clean_email(e: str | None) -> str | None:
    if not e:
        return None
    e = e.strip().lower().removeprefix("mailto:")
    return e if re.match(r"^[^@\s]+@[^@\s]+\.[a-z]{2,24}$", e) else None


def _connect():
    try:
        import duckdb
    except ImportError as e:
        raise RuntimeError("duckdb is not installed. Run: ./venv/bin/pip install duckdb") from e
    con = duckdb.connect()
    if os.environ.get("LEADFINDER_OVERTURE_PATH"):
        return con  # local test file, no S3
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region='us-west-2';")
    return con


def fetch_state(state: str, groups: list[str], *, release: str, min_confidence=0.5,
                log=print) -> list[dict]:
    """Query one state. Returns cleaned rows ready for LeadStore.insert_many."""
    state = state.upper()
    if state not in STATE_BBOX:
        raise ValueError(f"Unknown state code {state}")
    x0, y0, x1, y1 = STATE_BBOX[state]
    x0, y0, x1, y1 = x0 - PAD, y0 - PAD, x1 + PAD, y1 + PAD
    kw = _keyword_regex(groups)
    # Word-bounded so "atm" doesn't knock out "water_treatment".
    ex = "(^|[_ ])(" + "|".join(EXCLUDE) + ")([_ ]|$)"
    path = os.environ.get("LEADFINDER_OVERTURE_PATH") or \
        f"s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*"

    # Newer releases carry taxonomy/basic_category; older ones only
    # categories. Try the new schema first, fall back if the column is absent.
    cat_exprs = [
        "lower(coalesce(taxonomy.primary, '') || ' ' || coalesce(basic_category, ''))",
        "lower(coalesce(categories.primary, ''))",
    ]
    con = _connect()
    last_err = None
    for cat in cat_exprs:
        sql = f"""
        SELECT id, names.primary AS name, {cat} AS cat,
               websites[1] AS website, emails[1] AS email, phones[1] AS phone,
               socials, addresses[1].freeform AS street, addresses[1].locality AS city,
               addresses[1].postcode AS postcode
        FROM read_parquet('{path}', hive_partitioning=1)
        WHERE bbox.xmin BETWEEN {x0} AND {x1}
          AND bbox.ymin BETWEEN {y0} AND {y1}
          AND addresses[1].country = 'US'
          AND upper(addresses[1].region) IN ('{state}', 'US-{state}')
          AND brand IS NULL
          AND coalesce(confidence, 0) >= {float(min_confidence)}
          AND (websites IS NOT NULL OR emails IS NOT NULL)
          AND regexp_matches({cat}, '{kw}')
          AND NOT regexp_matches({cat}, '{ex}')
        """
        status_filter = "AND coalesce(operating_status, 'open') <> 'permanently_closed'"
        for attempt_sql in (sql + status_filter, sql):
            try:
                log(f"  querying Overture {release} for {state}...")
                rows = con.execute(attempt_sql).fetchall()
                return _clean(rows, state)
            except Exception as e:  # BinderException for missing columns, etc.
                last_err = e
                if "operating_status" in str(e) or "Binder" in type(e).__name__ or "column" in str(e).lower():
                    continue
                raise
    raise RuntimeError(f"Overture query failed: {last_err}")


def _clean(rows, state) -> list[dict]:
    out = []
    for oid, name, cat, website, email, phone, socials, street, city, postcode in rows:
        if not name:
            continue
        url, domain = normalize_website(website)
        email = clean_email(email)
        if not url and not email:
            continue
        out.append({
            "overture_id": oid,
            "name": str(name).strip()[:200],
            "category": ((cat or "").split() or [""])[0][:80],
            "website": url,
            "domain": domain,
            "phone": phone,
            "email": email,
            "socials": list(socials or []),
            "street": street,
            "city": city,
            "state": state,
            "postcode": postcode,
        })
    return out
