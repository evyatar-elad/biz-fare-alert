"""Profile "holidays - economy": settings only (the code is holiday_cal.py / holiday_scanner.py).

Defined with the user 11/11/2026 (see CLAUDE.md, "מערכת שנייה"):
economy round trips from Tel Aviv for one traveller over the Tishrei holidays and Passover.
Not only deals: always show the cheapest price found for each holiday and destination.
Price decides; the preferences below are shown next to each option, they never hide prices.
"""
from config import BANNED_AIRPORTS, EXCLUDE_AIRLINES  # same safety rules as the business bot

NAME = "חגים - תיירים"
ORIGIN = "TLV"
CABIN = "ECONOMY"

# code: (Hebrew name, country). Tokyo has two airports; Google needs each one separately.
DESTINATIONS = {
    "SGN": ("הו צ'י מין", "וייטנאם"),
    "HAN": ("האנוי", "וייטנאם"),
    "DAD": ("דה נאנג", "וייטנאם"),
    "DPS": ("באלי", "אינדונזיה"),
    "DEL": ("דלהי", "הודו"),
    "BOM": ("מומבאי", "הודו"),
    "GOI": ("גואה", "הודו"),
    "BKK": ("בנגקוק", "תאילנד"),
    "HKT": ("פוקט", "תאילנד"),
    "NRT": ("טוקיו נריטה", "יפן"),
    "HND": ("טוקיו הנדה", "יפן"),
    "KIX": ("אוסקה", "יפן"),
}

# Trip length in nights. MAIN = what is shown first; FLEX = also scanned, shown only when
# the price is exceptional (user: "for an exceptional price I'll bend the min/max a bit").
NIGHTS_MAIN = (14, 21)
NIGHTS_FLEX = (12, 24)
# Kiwi returns ~15 itineraries per request, so each departure date is searched in these
# nights chunks (more cells of the date x nights matrix get a price).
KIWI_NIGHT_CHUNKS = [(12, 17), (18, 24)]

# Departure windows, relative to the holiday (see holiday_cal.windows()).
# Tishrei: from a few days before erev Rosh Hashana up to the first days of Chol Hamoed Sukkot.
TISHREI_DEP_BEFORE_EREV_RH = 7
TISHREI_DEP_AFTER_EREV_SUKKOT = 3
# Passover: any trip that can contain the holiday week, up to a few days after the Seder.
PESACH_DEP_SLACK = 2
PESACH_DEP_AFTER_EREV = 4

# Alerts: a new lowest price for a holiday and destination, or a drop of this much
# since the previous check. No price cap (the user wants the cheapest, not only deals).
DROP_ALERT = 0.10
# Business shown on the side "for a peek" when below this round trip price.
BIZ_PEEK_MAX = 2000

# Routing preferences (shown, never filtering):
# - Connections through Europe to the East = second priority (many more flight hours).
#   Larnaca is next door, not "via Europe".
EUROPE_AIRPORTS = {
    "VIE", "FRA", "MUC", "ZRH", "GVA", "FCO", "MXP", "LIN", "VCE", "CDG", "ORY", "AMS",
    "LHR", "LGW", "STN", "LTN", "MAN", "ATH", "WAW", "KRK", "BUD", "PRG", "BER", "DUS",
    "HAM", "CPH", "HEL", "ARN", "OSL", "BRU", "MAD", "BCN", "LIS", "DUB", "OTP", "SOF",
    "BEG", "ZAG", "LJU", "RIX", "VNO", "TLL", "NCE", "MRS", "LYS", "NAP", "BGY", "CIA",
    "BLQ", "STR", "CGN", "EIN", "CRL", "BTS", "KUN", "TBS", "SKG",
}
# Kiwi accepts at most 200 characters of excluded airports, so the "without Europe" search
# excludes the main European hubs only (results are still flagged with the full list above).
EUROPE_HUBS_KIWI = ["VIE", "FRA", "MUC", "ZRH", "FCO", "MXP", "CDG", "AMS", "LHR", "ATH", "WAW",
                    "BUD", "PRG", "BER", "CPH", "HEL", "ARN", "BRU", "MAD", "BCN", "LIS", "OTP"]
# Better than the airport list (12/11): Kiwi also takes countries to never connect in.
EUROPE_COUNTRIES = "AT,BE,BG,CH,CZ,DE,DK,EE,ES,FI,FR,GB,GR,HR,HU,IE,IT,LT,LU,LV,MT,NL,NO,PL,PT,RO,RS,SE,SI,SK"
BANNED_COUNTRIES = "TR,QA,SA,KW,LB,IQ,IR,SY,YE,PK,DZ"
# "Short" search: at most one connection and at most this many hours per direction
# (Kiwi max_fly_duration). Found 12/11: without it Kiwi returns 20-40 hour routes first;
# with 16h for Bangkok it returns El Al nonstop $1,220 and Uzbekistan via Tashkent $1,227.
FAST_HOURS = {"DEL": 12, "BOM": 12, "GOI": 14, "BKK": 16, "HKT": 17, "SGN": 18, "HAN": 18, "DAD": 19,
              "DPS": 21, "TYO": 21, "KIX": 21}
# Hebrew names for connection airports (and destinations), so routes read as cities.
AIRPORT_NAMES = {
    "ATH": "אתונה", "SIN": "סינגפור", "ADD": "אדיס אבבה", "GYD": "באקו", "DXB": "דובאי", "AUH": "אבו דאבי",
    "SHJ": "שארג'ה", "ZRH": "ציריך", "VIE": "וינה", "FCO": "רומא", "MXP": "מילאנו", "MUC": "מינכן",
    "FRA": "פרנקפורט", "BUD": "בודפשט", "WAW": "ורשה", "OTP": "בוקרשט", "PRG": "פראג", "AMS": "אמסטרדם",
    "CDG": "פריז", "LHR": "לונדון", "IST": "איסטנבול", "DEL": "דלהי", "BOM": "מומבאי", "BKK": "בנגקוק",
    "DMK": "בנגקוק (דון מואנג)", "KUL": "קואלה לומפור", "MNL": "מנילה", "ICN": "סיאול", "PVG": "שנגחאי",
    "PEK": "בייג'ינג", "PKX": "בייג'ינג", "HKG": "הונג קונג", "TAS": "טשקנט", "CMB": "קולומבו",
    "AMM": "עמאן", "CAI": "קהיר", "LCA": "לרנקה", "MCT": "מוסקט", "BAH": "בחריין", "TPE": "טאיפיי",
    "CAN": "גואנגז'ו", "SGN": "הו צ'י מין", "HAN": "האנוי", "DAD": "דה נאנג", "DPS": "באלי", "GOI": "גואה",
    "GOX": "גואה", "HKT": "פוקט", "NRT": "טוקיו (נריטה)", "HND": "טוקיו (הנדה)", "KIX": "אוסקה",
    "TYO": "טוקיו", "CGK": "ג'קרטה", "KTM": "קטמנדו", "BLR": "בנגלור", "MAA": "צ'נאי", "CCU": "קולקטה",
    "HYD": "היידראבאד", "COK": "קוצ'ין", "CNX": "צ'יאנג מאי", "TLV": "תל אביב", "ALA": "אלמטי",
    "NQZ": "אסטנה", "TBS": "טביליסי", "EVN": "ירוואן", "SKD": "סמרקנד", "KWI": "כווית", "RUH": "ריאד",
}
# - A stop of 1-2 nights in one of these cities is something the user likes.
STOPOVER_HUBS = {
    "GYD": "באקו", "TAS": "טשקנט", "AUH": "אבו דאבי", "DXB": "דובאי", "BKK": "בנגקוק",
    "DEL": "דלהי", "SIN": "סינגפור", "KUL": "קואלה לומפור", "HKG": "הונג קונג",
}
# - Prefer nonstop or one connection; two only when there is no reasonable alternative.

# Stopovers on ONE ticket (12/11): the user's Azerbaijan Airlines ticket to China had a night
# in Baku out and two nights back, all one ticket (safer: a cancelled flight cancels the whole
# trip together). Kiwi does not return such itineraries; Google's multi-city search does
# (tested: TLV-GYD-DEL with a night out and two nights back = one J2 ticket, $959).
# Each plan: (hub, nights at the hub on the way out, nights at the hub on the way back).
# Google multi-city searches are slow (several requests each): at most this many per run,
# so the Kiwi sweep keeps moving (12/11: a run spent most of its time on them).
MULTI_PER_RUN = 12
STOPOVER_PLANS = [("GYD", 1, 2), ("TAS", 1, 1), ("AUH", 1, 1), ("DXB", 1, 1)]
STOPOVER_EXTRA = {"DPS": [("BKK", 1, 1), ("SIN", 1, 1)], "HKT": [("BKK", 0, 2)], "GOI": [("BOM", 1, 1)],
                  "DAD": [("BKK", 1, 1)], "TYO": [("ICN", 1, 1)], "KIX": [("ICN", 1, 1)]}

# Open jaw = a bonus next to the round trips, never instead of them:
# fly into one city and back from another.
OPEN_JAW = [
    ("KIX", "NRT"), ("KIX", "HND"), ("NRT", "KIX"), ("HND", "KIX"),
    ("HAN", "SGN"), ("SGN", "HAN"), ("HAN", "DAD"), ("DAD", "SGN"),
    ("BKK", "HKT"), ("HKT", "BKK"),
    ("DEL", "BOM"), ("BOM", "DEL"), ("DEL", "GOI"), ("GOI", "DEL"),
]

# Pace: separate workflow and runner from the business bot, so Google's rate limit is
# counted separately. Same slow pace that works for the business bot.
PACE_SECONDS = 30
BACKOFF_HOURS = 4
KIWI_PACE_SECONDS = 10
# How far ahead each source can see (days). Holidays further out wait until a source sees them.
GOOGLE_HORIZON_DAYS = 330
KIWI_HORIZON_DAYS = 365



# Google Flights calendar: on/off and extra arguments (set after the 12/11 diagnosis).
GOOGLE_ENABLED = True
GOOGLE_EXTRA_ARGS: list[str] = []

__all__ = ["BANNED_AIRPORTS", "EXCLUDE_AIRLINES"]
