"""
Builds the simulated terminal: the problem box, 100 more boxes, lanes and
free resources. Seeded, so the demo is identical every run.

Each box keeps what every source *says* under box["sources"]. The planner
only ever reads those. box["truth"] is what is really inside, and only the
simulation uses it, to score how well each strategy did.
"""

import random
from copy import deepcopy
from datetime import datetime

from ports import DEFAULT_PORT
from config import (CARGO, CARRIERS, DRY_CARGO, LANES, QUEUE_SIZE,
                    RESOURCES, SEED, TARE_KG)


def _letter_values():
    # ISO 6346 letter values: A=10, B=12 ... skipping multiples of 11.
    values, n = {}, 10
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if n % 11 == 0:
            n += 1
        values[letter] = n
        n += 1
    return values


LETTERS = _letter_values()


def container_id(owner, serial):
    """Owner code + 6-digit serial + the real ISO 6346 check digit."""
    body = f"{owner}{serial:06d}"
    total = sum((LETTERS[c] if c.isalpha() else int(c)) * 2 ** i
                for i, c in enumerate(body))
    return body + str(total % 11 % 10)


def problem_box():
    """One box, four stories."""
    tare = TARE_KG[("reefer", 40)]
    return {
        "id": container_id("OCLU", 318206),
        "carrier": CARRIERS["OCLU"],
        "kind": "reefer", "size": 40, "tare_kg": tare,
        "cargo": None,                 # carrier says empty, so no manifest
        "arrival": 1,                  # it is the box at the front of the gate
        "lane": "L3",                  # its appointment lane is down
        "lfd_h": 20,                   # free time ends in 20 hours
        "location": "gate",
        "problem": True,
        "sources": {
            "carrier": {"says": "EMPTY", "declared_kg": 0, "age_min": 3 * 24 * 60,
                        "note": "Empty return, per carrier EDI"},
            "scale": {"measured_kg": 23480, "scale_id": "Gate scale 2", "age_min": 12},
            "customs": {"holds": [{"name": "customs", "status": "hold",
                                   "description": "Customs exam hold"}],
                        "age_min": 125, "clears_at": None},
            "reefer": {"set_point": -20, "temp_c": -13.1, "powered": False,
                       "unit_ok": True, "age_min": 2,
                       "note": "Unplugged during transfer from the vessel"},
        },
        "truth": {"loaded": True, "cargo": "frozen_seafood"},
    }


def random_box(rng, arrival):
    owner = rng.choice(list(CARRIERS))
    is_reefer = rng.random() < 0.22
    kind = "reefer" if is_reefer else "dry"
    size = 40 if is_reefer else rng.choice([20, 40, 40])
    tare = TARE_KG[(kind, size)] + rng.randint(-80, 80)

    if is_reefer:
        cargo = rng.choice(list(CARGO))
        declared = rng.randint(15000, 25000)
    else:
        cargo = rng.choice(DRY_CARGO)
        declared = rng.randint(6000, 19000 if size == 20 else 24000)

    # Spread of free-time deadlines: some already over, most within 3 days.
    bucket = rng.random()
    if bucket < 0.15:
        lfd_h = rng.randint(-60, -2)
    elif bucket < 0.40:
        lfd_h = rng.randint(2, 24)
    elif bucket < 0.75:
        lfd_h = rng.randint(25, 72)
    else:
        lfd_h = rng.randint(73, 120)

    measured = tare + declared + rng.randint(-250, 250)
    box = {
        "id": container_id(owner, rng.randint(100000, 999999)),
        "carrier": CARRIERS[owner],
        "kind": kind, "size": size, "tare_kg": tare,
        "cargo": cargo,
        "arrival": arrival,
        "lane": rng.choice([lane["id"] for lane in LANES]),
        "lfd_h": lfd_h,
        "location": "gate",
        "sources": {
            "carrier": {"says": "FULL", "declared_kg": declared,
                        "age_min": rng.randint(1, 5) * 24 * 60},
            "scale": {"measured_kg": measured,
                      "scale_id": f"Gate scale {rng.randint(1, 3)}",
                      "age_min": rng.randint(5, 90)},
            "customs": {"holds": [], "age_min": rng.randint(30, 600), "clears_at": None},
        },
        "truth": {"loaded": True, "cargo": cargo},
    }
    if is_reefer:
        # Most reefers are already sitting on a plug and behaving.
        profile = CARGO[cargo]
        box["location"] = "reefer_rack"
        box["on_plug"] = True
        box["sources"]["reefer"] = {
            "set_point": profile["set_point"],
            "temp_c": round(profile["set_point"] + rng.uniform(-0.4, 0.4), 1),
            "powered": True, "unit_ok": True, "age_min": rng.randint(1, 10),
        }
    return box


def plant_exceptions(rng, boxes):
    """Add the realistic messes: unplugged reefers, a broken unit, holds, bad weights."""
    dry = [b for b in boxes if b["kind"] == "dry" and not b.get("problem")]
    reefers = [b for b in boxes if b["kind"] == "reefer" and not b.get("problem")]

    # Reefers just discharged and still waiting for a plug, from urgent to relaxed.
    waiting = [("vaccines", 5.0, 88), ("berries", 2.5, 70),
               ("dairy", 4.0, 52), ("chocolate", 17.0, 9)]
    for box, (cargo, temp, arrival) in zip(reefers, waiting):
        box.update(cargo=cargo, arrival=arrival, location="gate", on_plug=False)
        box["truth"]["cargo"] = cargo
        box["sources"]["reefer"].update(set_point=CARGO[cargo]["set_point"],
                                        temp_c=temp, powered=False)

    # One reefer whose own refrigeration unit has failed: a plug won't help.
    broken = reefers[4]
    broken.update(cargo="frozen_meat")
    broken["truth"]["cargo"] = "frozen_meat"
    broken["sources"]["reefer"].update(set_point=-18, temp_c=-16.0, unit_ok=False,
                                       note="Compressor alarm")

    # Holds, shaped like Terminal49's holds_at_pod_terminal records.
    holds = [("customs", "Customs exam hold", 3), ("customs", "Customs document review", None),
             ("USDA", "USDA inspection hold", 5), ("freight", "Freight charges unpaid", 2),
             ("TMF", "Traffic mitigation fee unpaid", 1)]
    for box, (name, description, clears_at) in zip(rng.sample(dry, len(holds)), holds):
        box["sources"]["customs"]["holds"] = [
            {"name": name, "status": "hold", "description": description}]
        box["sources"]["customs"]["clears_at"] = clears_at

    # Two boxes whose declared weight is well off the scale reading.
    clean = [b for b in dry if not b["sources"]["customs"]["holds"]]
    mismatched = rng.sample(clean, 2)
    for box in mismatched:
        scale = box["sources"]["scale"]
        scale["measured_kg"] = int(scale["measured_kg"] * 1.18)

    # A few critical boxes already in the queue on a normal day.
    others = [b for b in clean if b not in mismatched]
    for box, (kind, cargo) in zip(rng.sample(others, 3), [("medical", "Medical supplies"),
                                                          ("relief", "Generators"),
                                                          ("defense", "Defense cargo")]):
        box.update(critical=kind, cargo=cargo)
        box["truth"]["cargo"] = cargo


def relief_boxes(rng, first_arrival, count=8):
    """The 'relief cargo surge' twist: medical and emergency boxes just off a ship."""
    kinds = [("medical", "Medical supplies"), ("relief", "Drinking water"),
             ("medical", "Field hospital kits"), ("relief", "Generators")]
    boxes = []
    for i in range(count):
        box = random_box(rng, first_arrival + i)
        while box["kind"] != "dry":                 # keep the surge simple: dry boxes only
            box = random_box(rng, first_arrival + i)
        kind, cargo = kinds[i % len(kinds)]
        box.update(critical=kind, cargo=cargo, lfd_h=96, waiting_h=0)
        box["truth"]["cargo"] = cargo
        box["sources"]["customs"]["holds"] = []
        box["sources"]["scale"]["measured_kg"] = box["tare_kg"] + box["sources"]["carrier"]["declared_kg"]
        boxes.append(box)
    return boxes


def build_scenario(seed=SEED):
    rng = random.Random(seed)
    boxes = [problem_box()]
    boxes += [random_box(rng, arrival) for arrival in range(2, QUEUE_SIZE + 2)]
    plant_exceptions(rng, boxes)
    # Planting moved some boxes in the queue, so renumber 1..N.
    boxes.sort(key=lambda b: (b["arrival"], b["id"]))
    for position, box in enumerate(boxes, start=1):
        box["arrival"] = position
        # Hours already waited, like the dataset's "Waiting Time" column (own seed per box,
        # so it doesn't change the rest of the scenario).
        box["waiting_h"] = random.Random(box["id"]).randint(1, 22)
    return {
        "clock": 0,                                   # hours since the scenario started
        "started_at": datetime.now().replace(second=0, microsecond=0).isoformat(),
        "boxes": boxes,
        "lanes": deepcopy(LANES),
        "free": dict(RESOURCES),
        "port": DEFAULT_PORT,   # which port's names, map and ships to show
        "mode": "daily",        # "daily" or "crisis": the dual-use switch
        "twists": [],           # twists applied so far
        "untrusted": [],        # sources the planner must ignore right now
        "log": [],
    }
