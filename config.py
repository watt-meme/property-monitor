# config.py — Property monitor v3.4 configuration
#
# v3.3: SPARQL postcode fix, floorplan AI v2, traffic road penalties, postwar detection.
# v3.4: Audit fixes: dead code removed, layout dedup, detail caching, 429 retry.

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Search areas ---
OTM_LOCATIONS = ["n1", "n5", "n16", "e8", "e9"]

# --- Search filters ---
MIN_BEDROOMS = 3
MAX_PRICE = 2_000_000
MIN_PRICE = 800_000

# --- EPC ---
# =====================================================================
# SCORING WEIGHTS (theoretical max ~105, clamped to 100)
# =====================================================================

# --- VFM: £/sq ft relative to area benchmark (0-25) ---
VFM_MAX = 25
VFM_NO_SQFT = 8  # neutral when unknown

# --- Bedrooms (0-20) ---
BEDS_ABOVE_GROUND_SCORE = {4: 20, 3: 12, 5: 15, 6: 12}

# --- Period / style (0-20) ---
PERIOD_SCORE = {
    "georgian": 20, "regency": 20, "grade ii listed": 20, "grade ii": 18,
    "early victorian": 14, "victorian_stucco": 14,
    "victorian": 10, "late victorian": 10,
    "edwardian": 8,
    "period": 7,
}
PERIOD_DEFAULT = 3
PERIOD_MODERN = 0

STYLE_BONUS = {
    "stock brick": 3, "stucco": 3, "stucco front": 3,
    "listed": 2, "conservation area": 2,
    "tall ceilings": 2, "high ceilings": 2,
}
STYLE_PENALTY = {
    "red brick victorian": -3,
}

# --- Garden (0-10) ---
GARDEN_KEYWORDS = {
    "large garden": 10, "south-facing garden": 10, "south facing garden": 10,
    "south-west facing garden": 10, "south west facing garden": 10,
    "west-facing garden": 8, "west facing garden": 8,
    "private garden": 8, "mature garden": 8, "landscaped garden": 8,
    "walled garden": 8,
    "rear garden": 6,
    "garden": 5,
    "east-facing garden": 4, "east facing garden": 4,
    "patio": 3, "courtyard": 3,
    "north-facing garden": 2, "north facing garden": 2,
}

# --- Micro-location quality (0-20) ---
LOCATION_SCORE = {"premium": 20, "good": 12, "acceptable": 6, "fringe": 2}

# --- Layout quality signals (additive, -20 to +10) ---
LAYOUT_POSITIVE = {
    "double fronted": 5, "double-fronted": 5,
    "through reception": 4, "through lounge": 4, "through sitting": 4,
    "double reception": 3,
    "high ceilings": 3, "tall ceilings": 3, "ceiling height": 3,
    "period features": 3, "original features": 3,
    "cornicing": 2, "sash windows": 2, "shutters": 2,
    "fireplaces": 2, "fireplace": 2, "marble fireplace": 3,
    "cellar": 2, "wine cellar": 2, "bay window": 2,
    "original floorboards": 2, "wooden floors": 1,
    "panelled doors": 1, "dado rail": 1,
}
LAYOUT_NEGATIVE = {
    "basement bedroom": -20, "bedroom in basement": -20,
    "lower ground bedroom": -15, "lower ground floor bedroom": -15,
    "bedroom on lower": -15,
    "kitchen on first floor": -8, "kitchen on the first": -8,
    "bedroom on ground floor": -5,
}

# --- Condition / renovation quantum ---
CONDITION_HEAVY_RENO_KEYWORDS = [
    "unmodernised", "requires complete", "requires full",
    "complete renovation", "full renovation", "blank canvas",
    "in need of full", "complete refurbishment", "total refurbishment",
    "requires updating throughout", "renovation project",
    "development opportunity",
]
CONDITION_NEEDS_WORK_KEYWORDS = [
    "requires modernisation", "in need of updating", "scope to improve",
    "add value", "requires updating", "potential to extend",
    "needs updating", "needs modernisation",
]
CONDITION_GOOD_KEYWORDS = [
    "beautifully presented", "impeccably", "meticulously renovated",
    "recently refurbished", "high specification", "turn-key",
    "immaculate", "exacting standard", "tastefully",
    "sympathetically restored", "expertly designed",
]
CONDITION_PENALTY_PRICE_THRESHOLD = 1_400_000
CONDITION_HEAVY_RENO_PENALTY = -12
CONDITION_NEEDS_WORK_PENALTY = -5
CONDITION_GOOD_BONUS = 5

# =====================================================================
# AREA BENCHMARKS (£/sq ft)
# =====================================================================
AREA_BENCHMARKS = {
    "N1":  {"floor": 850, "ceiling": 1200},
    "N5":  {"floor": 800, "ceiling": 1150},
    "N16": {"floor": 750, "ceiling": 1100},
    "E8":  {"floor": 700, "ceiling": 1100},
    "E9":  {"floor": 600, "ceiling": 1000},
}

# =====================================================================
# MICRO-LOCATION ZONES
# =====================================================================
LOCATION_ZONES = [
    # Premium
    ((51.5355, 51.5440, -0.1120, -0.0960), "Barnsbury", "premium"),
    ((51.5330, 51.5395, -0.1140, -0.1050), "Thornhill Sq / Cloudesley", "premium"),
    ((51.5410, 51.5480, -0.0960, -0.0850), "Canonbury", "premium"),
    ((51.5370, 51.5450, -0.0850, -0.0720), "De Beauvoir Town", "premium"),

    # Good
    ((51.5290, 51.5370, -0.1050, -0.0830), "Angel / Upper St", "good"),
    ((51.5395, 51.5470, -0.1120, -0.0960), "Upper Barnsbury", "good"),
    ((51.5440, 51.5520, -0.0900, -0.0780), "Newington Green", "good"),
    ((51.5380, 51.5460, -0.0720, -0.0550), "London Fields", "good"),
    ((51.5340, 51.5400, -0.0650, -0.0500), "Broadway Market", "good"),
    ((51.5350, 51.5420, -0.0550, -0.0380), "Victoria Park south", "good"),
    ((51.5500, 51.5560, -0.0900, -0.0750), "Stoke Newington Church St", "acceptable"),

    # Acceptable
    ((51.5350, 51.5410, -0.0960, -0.0850), "Angel borders", "acceptable"),
    ((51.5480, 51.5540, -0.1000, -0.0900), "Highbury (south)", "acceptable"),
    ((51.5520, 51.5580, -0.1050, -0.0900), "Highbury Fields", "acceptable"),
    ((51.5450, 51.5520, -0.0780, -0.0650), "Newington Green east", "acceptable"),
    ((51.5420, 51.5500, -0.0650, -0.0500), "Dalston", "acceptable"),
    ((51.5300, 51.5380, -0.0720, -0.0550), "Hackney Central", "acceptable"),
    ((51.5540, 51.5600, -0.0800, -0.0650), "Stoke Newington north", "fringe"),  # downgraded: consistently rejected

    # Fringe
    ((51.5560, 51.5650, -0.1150, -0.0950), "Highbury Hill / Finsbury Pk borders", "fringe"),
    ((51.5440, 51.5530, -0.0500, -0.0300), "Well St / Cassland", "fringe"),
    ((51.5250, 51.5340, -0.0600, -0.0400), "Hackney Wick / Homerton", "fringe"),
    ((51.5580, 51.5670, -0.1000, -0.0800), "Finsbury Park south", "fringe"),
    ((51.5580, 51.5680, -0.0800, -0.0600), "Manor House / Woodberry", "fringe"),
    # Poor — score cap applied via SCORE_CAP, zones retained for labelling
    ((51.5420, 51.5490, -0.0420, -0.0280), "Hackney Wick east", "fringe"),
]

LOCATION_FALLBACK = {
    "N1": ("Islington (unzoned)", "good"),
    "N5": ("Highbury area", "acceptable"),
    "N16": ("Stoke Newington area", "acceptable"),
    "E8": ("Hackney", "acceptable"),
    "E9": ("Hackney Wick area", "fringe"),
}

# =====================================================================
# ADDRESS-BASED OVERRIDES
# =====================================================================
FORCE_EXCLUDE = {
    "ardleigh road": "New development (Newlon Housing Trust)",
    "spencer place": "Modern development (Canonbury)",
    "shrubland road": "Modern / new build (E8)",
    "victorian grove": "Modern / new build despite name (N16)",
    "garden place": "Modern / new build (E8)",
    "amhurst road": "Modern / new build (E8)",
    "cadogan terrace": "Wrong location — Hackney Wick east",
}

FORCE_ALLOW = {
    "brett close": "Manual override: not a new build",
}

SCORE_CAP = {
    "howard road": 45,
    # Manor House / Woodberry zone: Alkham Rd scored 77 but discarded on location.
    # Cap properties in this zone to prevent false positives.
    "alkham road": 55,
    "lampard grove": 55,
    "sylvester path": 50,
}

# Traffic roads — score penalty (not hard exclude).
# Values are negative score deductions. Heavier penalty for major arterials.
# Properties on these roads appear in results with a flag; you decide.
TRAFFIC_ROAD_PENALTIES = {
    # Major arterials (-20)
    "caledonian road": -20,
    "holloway road": -20,
    "kingsland road": -20,
    "essex road": -20,
    "upper street": -20,
    "pentonville road": -20,
    "city road": -20,
    "old street": -20,
    "mare street": -20,
    "green lanes": -20,
    "seven sisters road": -20,
    "stamford hill": -20,
    "hackney road": -20,
    # Secondary arterials (-15)
    "southgate road": -15,
    "balls pond road": -15,
    "stoke newington high street": -15,
    "new north road": -15,
    "dalston lane": -15,
    "graham road": -15,
    "morning lane": -15,
    "lower clapton road": -15,
    "clapton common": -15,
    "de beauvoir road": -15,
    "liverpool road": -15,
    "queensbridge road": -15,
    "highbury grove": -15,
    "highbury hill": -15,
    "blackstock road": -15,
    "amhurst road": -15,
    "pembury road": -15,
    "victoria park road": -15,
    "canonbury road": -15,
    "newington green road": -15,
    "albion road": -15,
    # Minor (-10)
    "shacklewell lane": -10,
    "cassland road": -10,
    "richmond road": -10,
    "whiston road": -10,
    "fonthill road": -10,
    "mildmay grove": -10,
    "howard road": -10,
}
EXCLUDE_KEYWORDS = [
    "maisonette", "converted flat", "ex-local authority",
    "ex-council", "new build", "purpose built",
    "shared ownership", "auction",
]

# Post-war style signals — soft score penalty (applied in scorer.py)
# These appear in the description/features and indicate post-1950 stock.
# Not hard excludes: a "concrete" remark in a Victorian conversion is fine,
# but combined with other signals they should drag the score down.
POSTWAR_STYLE_PENALTIES = {
    "concrete": -8,
    "balcony access": -15,
    "deck access": -20,
    "system built": -25,
    "low rise block": -20,
    "high rise": -25,
    "lift serviced": -15,
    "parking court": -10,
}

# Post-war street name suffixes — mild soft penalty on address.
# NOTE: Only reliable in suburban contexts. Many legitimate Victorian streets
# in E8/N1/N16 end in 'drive', 'walk', 'close' etc.
# Disabled by default: too many false positives on target streets.
# To re-enable selectively, add specific known-postwar street patterns to FORCE_EXCLUDE instead.
POSTWAR_STREET_SUFFIXES = []  # disabled — use FORCE_EXCLUDE for specific modern streets
POSTWAR_STREET_SUFFIX_PENALTY = -8

# =====================================================================
# PATHS
# =====================================================================
ALERTS_DIR = os.path.join(BASE_DIR, "alerts")
STATE_FILE = os.path.join(BASE_DIR, "state.json")
DETAIL_CACHE_FILE = os.path.join(BASE_DIR, "detail_cache.json")
DETAIL_CACHE_MAX_AGE_DAYS = 7
REQUEST_DELAY = 1.5
