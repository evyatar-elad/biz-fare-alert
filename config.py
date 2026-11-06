"""Settings for the business class deal scanner. Edit here to add/remove destinations."""

# Origins. LCA (Larnaca) needs a separate positioning flight from TLV,
# so its prices are compared after adding POSITIONING_USD.
ORIGINS = ["TLV", "LCA"]
POSITIONING_USD = 150  # rough round trip TLV-LCA in economy

# Destination regions. "dur" is the probe stay length in days (see CLAUDE.md:
# the stay length is a probe, not a choice. Price barely depends on it).
# "cap" = always alert if the round trip business price (USD) is at or below it.
REGIONS = {
    "europe": {"dur": 7, "cap": 650},   # 6/11: normal business mins are ~$700-1,100 (Athens ~$470)
    "near":   {"dur": 7, "cap": 650},    # Gulf, Caucasus, North Africa
    "asia":   {"dur": 14, "cap": 1700},
    "far":    {"dur": 14, "cap": 2200},  # Oceania, Africa south of Sahara, Latin America, Canada
}

# Destinations whose NORMAL business price is already near the regional cap get their
# own cap (measured 6/11): Athens ~$470, Mumbai ~$1,700, Delhi ~$1,880.
CAP_OVERRIDE = {"ATH": 380, "BOM": 1350, "DEL": 1400}

# code: (name in Hebrew, region, priority). priority=True -> scanned more often.
DESTINATIONS = {
    # Europe
    "LHR": ("לונדון", "europe", False),
    "CDG": ("פריז", "europe", False),
    "FCO": ("רומא", "europe", False),
    "MXP": ("מילאנו", "europe", False),
    "BCN": ("ברצלונה", "europe", False),
    "MAD": ("מדריד", "europe", False),
    "LIS": ("ליסבון", "europe", False),
    "AMS": ("אמסטרדם", "europe", False),
    "FRA": ("פרנקפורט", "europe", False),
    "MUC": ("מינכן", "europe", False),
    "BER": ("ברלין", "europe", False),
    "ZRH": ("ציריך", "europe", False),
    "GVA": ("ז'נבה", "europe", False),
    "VIE": ("וינה", "europe", False),
    "PRG": ("פראג", "europe", False),
    "BUD": ("בודפשט", "europe", False),
    "WAW": ("ורשה", "europe", False),
    "ATH": ("אתונה", "europe", False),
    "CPH": ("קופנהגן", "europe", False),
    "ARN": ("סטוקהולם", "europe", False),
    "OSL": ("אוסלו", "europe", False),
    "HEL": ("הלסינקי", "europe", False),
    "DUB": ("דבלין", "europe", False),
    "BRU": ("בריסל", "europe", False),
    "NCE": ("ניס", "europe", False),
    "VCE": ("ונציה", "europe", False),
    # Near
    "DXB": ("דובאי", "near", False),
    "AUH": ("אבו דאבי", "near", False),
    "GYD": ("באקו", "near", False),
    "TBS": ("טביליסי", "near", False),
    "EVN": ("ירוואן", "near", False),
    "CAI": ("קהיר", "near", False),
    "CMN": ("קזבלנקה", "near", False),
    "RAK": ("מרקש", "near", False),
    # Asia
    "SGN": ("הו צ'י מין", "asia", True),
    "HAN": ("האנוי", "asia", True),
    "DAD": ("דה נאנג", "asia", True),
    "DPS": ("באלי", "asia", True),
    "BKK": ("בנגקוק", "asia", False),
    "HKT": ("פוקט", "asia", False),
    "SIN": ("סינגפור", "asia", False),
    "KUL": ("קואלה לומפור", "asia", False),
    "HKG": ("הונג קונג", "asia", False),
    "PEK": ("בייג'ינג", "asia", False),
    "PVG": ("שנגחאי", "asia", False),
    "NRT": ("טוקיו", "asia", False),
    "KIX": ("אוסקה", "asia", False),
    "ICN": ("סיאול", "asia", False),
    "TPE": ("טאיוואן (טאיפיי)", "asia", True),
    "MNL": ("מנילה", "asia", False),
    "DEL": ("דלהי", "asia", True),
    "BOM": ("מומבאי", "asia", True),
    "GOI": ("גואה", "asia", True),
    "CMB": ("קולומבו", "asia", False),
    "MLE": ("מלדיביים", "asia", False),
    "SEZ": ("סיישל", "asia", False),
    "MRU": ("מאוריציוס", "asia", False),
    # Far
    "SYD": ("סידני", "far", False),
    "MEL": ("מלבורן", "far", False),
    "AKL": ("אוקלנד", "far", False),
    "JNB": ("יוהנסבורג", "far", False),
    "CPT": ("קייפטאון", "far", False),
    "NBO": ("ניירובי", "far", False),
    "ZNZ": ("זנזיבר", "far", False),
    "GRU": ("סאו פאולו", "far", False),
    "EZE": ("בואנוס איירס", "far", False),
    "MEX": ("מקסיקו סיטי", "far", False),
    "LIM": ("לימה", "far", False),
    "YYZ": ("טורונטו", "far", False),
}

# From LCA: only priority destinations (Google has almost no cached LCA business
# prices, so every date costs a request).
LCA_ONLY_PRIORITY = True

# Search window: Google Flights calendar covers ~305 days ahead, 61 days per call.
# Measured 5/11/2026: the calendar is full only ~100 days ahead (Google has cached
# prices there). Further out it returns just the requested start date. So beyond
# DENSE_DAYS we ask for one "anchor" date every FAR_STEP_DAYS days, and the anchors
# move by one day every day, so over a few scans every date (and every weekday,
# some airlines fly only on certain days) gets checked.
WINDOW_DAYS = 61
DENSE_DAYS = 100
FAR_STEP_DAYS = 7
HORIZON_DAYS = 300
START_OFFSET_DAYS = 2

# How often each task is due (hours).
DUE_HOURS = {"priority": 24, "normal": 48, "LCA": 96}
FAR_DUE_FACTOR = 1.5  # far (anchor) dates are checked a bit less often

# A route with this many empty results in a row (no flights at all, even with
# connections; ~31 windows = one full sweep of a destination) becomes "dormant"
# and is checked only every DORMANT_DUE_HOURS. It wakes up by itself once results
# appear (e.g. a new route launches).
DORMANT_AFTER_EMPTY = 40
DORMANT_DUE_HOURS = 24 * 10

# Nearby cities: a deal to one often allows "open jaw" (in to one, back from the other)
# for about the same price. Mentioned in the email.
SISTER_CITIES = [
    {"NRT", "KIX"}, {"SGN", "HAN", "DAD"}, {"DEL", "BOM", "GOI"}, {"BKK", "HKT"},
    {"SYD", "MEL"}, {"JNB", "CPT"}, {"PEK", "PVG"}, {"SIN", "KUL"}, {"NBO", "ZNZ"},
    {"RAK", "CMN"}, {"GRU", "EZE"},
]

# Hubs whose airline sells good connections east, but Google Flights does NOT show
# the through itinerary (found 6/11: Uzbekistan Airways TLV-TAS and TAS-BKK each
# appear on Google, TLV-TAS-BKK does not; their own site shows captcha to bots).
# Idea: price both legs on Google (that airline only) and add them up per date.
# Tested 6/11 with fli: Google returns HY flight 302 TLV-TAS WITHOUT a price
# (also with country IL), no HY business at all, and empty HY calendars. So it
# does not work today and HUBS is disabled. Code paths stay (they are no-ops).
HUBS: dict = {}
HUBS_DISABLED = {
    "TAS": {"airline": "HY", "name": "Uzbekistan Airways",
            "site": "https://www.uzairways.com/en",
            "dests": ["BKK", "KUL", "SIN", "DEL", "BOM", "ICN", "NRT", "PEK", "PVG", "HKG",
                      "SGN", "HAN", "DPS", "MLE", "CMB"]},
}
HUB_MAX_AGE_DAYS = 4  # both legs must have been priced within this many days

# Second source: Kiwi.com public MCP (kiwi.py). One request = cheapest business round
# trip leaving within a KIWI_WINDOW_DAYS window, any stay within KIWI_NIGHTS.
KIWI_ENABLED = True
KIWI_WINDOW_DAYS = 30
KIWI_NIGHTS = {"europe": (3, 10), "near": (3, 10), "asia": (7, 21), "far": (7, 21)}
KIWI_PACE_SECONDS = 10
DORMANT_AFTER_EMPTY_KIWI = 10  # ~one full sweep of monthly windows
KIWI_DUE_HOURS = {"priority": 24, "normal": 48}
# Airlines Google misses: also searched on Kiwi on their own (so a promo shows even
# when another airline is cheaper overall).
KIWI_AIRLINE_FOCUS = {
    "HY": ["BKK", "KUL", "SIN", "DEL", "BOM", "ICN", "NRT", "PEK", "PVG", "HKG",
           "SGN", "HAN", "DPS", "MLE", "CMB"],   # Uzbekistan Airways via Tashkent
}

HUB_SITES = {"HY": ("Uzbekistan Airways", "https://www.uzairways.com/en")}

# Destinations searched only as nonstop from Israel (no connection via third countries).
NONSTOP_ONLY = {"CAI"}

# Hubs worth highlighting for flights east (good business products / promos).
HIGHLIGHT_HUBS = {"GYD": "באקו", "TAS": "טשקנט"}

# Safety for an Israeli traveller: never route via Turkey or hostile / no-entry
# countries. Airlines excluded in the search itself:
EXCLUDE_AIRLINES = [
    "TK", "PC", "XQ",              # Turkish Airlines, Pegasus, SunExpress (via Turkey)
    "QR",                          # Qatar Airways (via Doha)
    "SV", "XY", "F3",              # Saudia, flynas, flyadeal
    "KU", "J9",                    # Kuwait Airways, Jazeera
    "ME", "IR", "W5", "EP", "IA",  # MEA (Lebanon), Iran Air, Mahan, Iran Aseman, Iraqi
    "PK", "AH",                    # PIA (Pakistan), Air Algerie
]
# Layover airports that drop a deal if the detail check shows them.
BANNED_AIRPORTS = {
    "IST", "SAW", "AYT", "ESB", "ADB",          # Turkey
    "DOH",                                      # Qatar
    "RUH", "JED", "DMM", "MED",                 # Saudi Arabia
    "KWI", "BEY", "BGW", "BSR", "EBL", "NJF",   # Kuwait, Lebanon, Iraq
    "IKA", "THR", "MHD", "DAM", "ALP",          # Iran, Syria
    "SAH", "ADE", "KHI", "LHE", "ISB", "ALG",   # Yemen, Pakistan, Algeria
}

# Deal rule: price at least this fraction below the reference price.
DROP = 0.35
# Seconds between requests to Google. Slow on purpose: ~20 quick calls got HTTP 429.
PACE_SECONDS = 30
# After a 429/block, do not search again for this long.
BACKOFF_HOURS = 4
# Detail lookups (airline, stops) per run.
MAX_DETAIL_LOOKUPS = 2  # each one is several requests to Google
# Economy price for the same dates, shown next to each deal (one request per deal).
MAX_ECONOMY_LOOKUPS = 4
# Business at most this many times the economy price = note it as a reason too.
BIZ_TO_ECO_RATIO = 1.6
# Do not re-alert the same route and month unless the price dropped by this much.
REALERT_DROP = 0.07
REALERT_DAYS = 14
