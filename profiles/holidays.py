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
# - A stop of 1-2 nights in one of these cities is something the user likes.
STOPOVER_HUBS = {
    "GYD": "באקו", "TAS": "טשקנט", "AUH": "אבו דאבי", "DXB": "דובאי", "BKK": "בנגקוק",
    "DEL": "דלהי", "SIN": "סינגפור", "KUL": "קואלה לומפור", "HKG": "הונג קונג",
}
# - Prefer nonstop or one connection; two only when there is no reasonable alternative.

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

__all__ = ["BANNED_AIRPORTS", "EXCLUDE_AIRLINES"]
