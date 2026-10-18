"""
Every number the planner depends on lives here, so we can defend or change
each one in a single place. The README says where each one comes from.
"""

SEED = 42            # same seed -> same scenario every demo
QUEUE_SIZE = 100     # boxes waiting behind the problem box
SIM_HOURS = 8        # how far ahead the comparison looks

# Gate lanes. Half are down when the scenario starts.
LANES = [
    {"id": "L1", "status": "open"},
    {"id": "L2", "status": "open"},
    {"id": "L3", "status": "down", "reason": "OCR portal fault"},
    {"id": "L4", "status": "open"},
    {"id": "L5", "status": "down", "reason": "Scheduled maintenance"},
    {"id": "L6", "status": "down", "reason": "No clerk on shift"},
    {"id": "L7", "status": "open"},
    {"id": "L8", "status": "down", "reason": "Pavement repair"},
]
TRUCKS_PER_LANE_PER_HOUR = 12

# Free capacity at the start (plugs already in use are not counted).
RESOURCES = {"reefer_plugs": 3, "cold_storage": 2, "inspection": 2}

# Demurrage tiers after the last free day, USD per box per day.
# Assumed values in the range LA/LB carriers publish; verify before quoting.
DEMURRAGE_TIERS = [(4, 200), (None, 400)]   # first 4 days $200, then $400

# Typical tare (empty) weights in kg.
TARE_KG = {("dry", 20): 2250, ("dry", 40): 3750, ("reefer", 40): 4600}

# A box counts as loaded if the scale reads this much more than its tare.
LOADED_MARGIN_KG = 1000
# A declared weight this far off the scale reading needs a recheck.
WEIGHT_TOLERANCE = 0.10

# Cargo profiles.
#   set_point  normal reefer setting (C)
#   damage_at  temperature where the cargo starts getting ruined (C)
#   warm_rate  how fast a loaded box warms once it loses power (C per hour, rough)
CARGO = {
    "frozen_seafood": {"label": "Frozen seafood", "set_point": -20, "damage_at": -12, "warm_rate": 1.6},
    "frozen_meat":    {"label": "Frozen meat",    "set_point": -18, "damage_at": -12, "warm_rate": 1.2},
    "vaccines":       {"label": "Vaccines",       "set_point": 5,   "damage_at": 8,   "warm_rate": 2.5},
    "berries":        {"label": "Fresh berries",  "set_point": 1,   "damage_at": 6,   "warm_rate": 1.5},
    "dairy":          {"label": "Dairy",          "set_point": 3,   "damage_at": 8,   "warm_rate": 1.2},
    "flowers":        {"label": "Cut flowers",    "set_point": 1,   "damage_at": 8,   "warm_rate": 1.3},
    "bananas":        {"label": "Bananas",        "set_point": 13,  "damage_at": 18,  "warm_rate": 1.0},
    "chocolate":      {"label": "Chocolate",      "set_point": 16,  "damage_at": 24,  "warm_rate": 0.6},
}
DRY_CARGO = ["Furniture", "Apparel", "Machinery", "Electronics", "Auto parts", "Toys", "Paper"]

# Dual use: critical cargo classes. Same engine, same hard rules in both modes;
# only how much a critical box counts changes.
CRITICAL = {
    "medical": "Medical supplies",
    "relief": "Disaster relief",
    "defense": "Defense-sponsored",
}
CRITICAL_POINTS = {"daily": 15, "crisis": 90}

# Fictional carriers (real ISO 6346 format, made-up owner codes).
CARRIERS = {
    "PMLU": "Pacific Meridian Line",
    "HSTU": "Harbor Star Shipping",
    "BALU": "Blue Anchor Lines",
    "OCLU": "Orient Crest",
}
