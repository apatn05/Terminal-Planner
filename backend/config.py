SEED = 42
QUEUE_SIZE = 100
SIM_HOURS = 8

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

RESOURCES = {"reefer_plugs": 3, "cold_storage": 2, "inspection": 2}

DEMURRAGE_TIERS = [(4, 200), (None, 400)]

TARE_KG = {("dry", 20): 2250, ("dry", 40): 3750, ("reefer", 40): 4600}

LOADED_MARGIN_KG = 1000
WEIGHT_TOLERANCE = 0.10

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

CRITICAL = {
    "medical": "Medical supplies",
    "relief": "Disaster relief",
    "defense": "Defense-sponsored",
}
CRITICAL_POINTS = {"daily": 15, "crisis": 90}

CARRIERS = {
    "PMLU": "Pacific Meridian Line",
    "HSTU": "Harbor Star Shipping",
    "BALU": "Blue Anchor Lines",
    "OCLU": "Orient Crest",
}
