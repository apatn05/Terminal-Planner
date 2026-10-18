from ports import PORTS
from config import (CARGO, CRITICAL, CRITICAL_POINTS, LOADED_MARGIN_KG, QUEUE_SIZE,
                    TRUCKS_PER_LANE_PER_HOUR, WEIGHT_TOLERANCE)

TRUST = {
    "carrier": "booking and identity",
    "scale": "weight",
    "customs": "release",
    "reefer": "temperature",
}


def fmt_hours(hours):
    if hours is None:
        return ""
    minutes = int(round(hours * 60))
    if minutes < 60:
        return f"{minutes} min"
    h, m = divmod(minutes, 60)
    return f"{h} h {m:02d} min" if h < 10 and m else f"{h} h"


def guess_cargo_from_set_point(set_point):
    return min(CARGO, key=lambda c: abs(CARGO[c]["set_point"] - set_point))


def assess(box, untrusted=()):
    src = box["sources"]
    carrier, scale, reefer = src["carrier"], src.get("scale"), src.get("reefer")
    carrier_ok = "carrier" not in untrusted
    cargo = box["cargo"] if carrier_ok or box.get("critical") else None
    a = {"cargo": cargo, "cargo_guessed": False, "weight_issue": None,
         "hours_left": None, "cooling_fix": None, "cooling_given": None, "damaged": False,
         "carrier_ok": carrier_ok}

    if scale:
        a["net_kg"] = scale["measured_kg"] - box["tare_kg"]
        a["loaded"] = a["net_kg"] > LOADED_MARGIN_KG
        if carrier_ok and not box.get("weight_checked"):
            if carrier["says"] == "EMPTY" and a["loaded"]:
                a["weight_issue"] = "empty_but_heavy"
            elif carrier["says"] == "FULL" and carrier["declared_kg"]:
                off_by = abs(a["net_kg"] - carrier["declared_kg"]) / carrier["declared_kg"]
                if off_by > WEIGHT_TOLERANCE:
                    a["weight_issue"] = "mismatch"
    else:
        a["loaded"] = carrier["says"] == "FULL" if carrier_ok else True
    a["record_wrong"] = carrier_ok and carrier["says"] == "EMPTY" and a["loaded"]

    a["holds"] = [h for h in src["customs"]["holds"] if h["status"] == "hold"]

    if reefer and a["loaded"]:
        if a["cargo"] is None:
            a["cargo"] = guess_cargo_from_set_point(reefer["set_point"])
            a["cargo_guessed"] = True
        profile = CARGO.get(a["cargo"])
        cooling = box["location"] == "cold_storage" or (reefer["powered"] and reefer["unit_ok"])
        if profile and not cooling:
            rate = profile["warm_rate"] * (0.5 if reefer["powered"] else 1.0)
            a["hours_left"] = max(0.0, (profile["damage_at"] - reefer["temp_c"]) / rate)
            a["damaged"] = reefer["temp_c"] >= profile["damage_at"]
            a["cooling_fix"] = "plug" if reefer["unit_ok"] else "cold_storage"
    return a


def score(box, a, clock, mode="daily"):
    reasons = []
    if box.get("critical"):
        label = CRITICAL[box["critical"]]
        note = "crisis priority" if mode == "crisis" else "critical cargo"
        reasons.append((CRITICAL_POINTS[mode], f"{label}, {note}"))
    if a["hours_left"] is not None and not a["damaged"]:
        h = a["hours_left"]
        points = 100 if h < 2 else 70 if h < 6 else 40
        reasons.append((points, f"Cargo damage in about {fmt_hours(h)}"))
    if a["weight_issue"]:
        reasons.append((50, "Weight in doubt"))
    free_h = box["lfd_h"] - clock
    if free_h <= 0:
        reasons.append((30, "Free time over, charges running"))
    elif free_h < 24:
        reasons.append((20, f"Free time ends in {fmt_hours(free_h)}"))
    elif free_h < 48:
        reasons.append((10, f"Free time ends in {int(free_h)} h"))
    return sum(p for p, _ in reasons), [text for _, text in reasons]


def lane_capacity(state):
    return {lane["id"]: TRUCKS_PER_LANE_PER_HOUR for lane in state["lanes"] if lane["status"] == "open"}


def pick_lane(box, lanes_left):
    if lanes_left.get(box["lane"], 0) > 0:
        lane = box["lane"]
    else:
        lane = max(lanes_left, key=lanes_left.get, default=None)
        if lane is None or lanes_left[lane] == 0:
            return None
    lanes_left[lane] -= 1
    return lane


def act(kind, text, why, who):
    return {"type": kind, "text": text, "why": why, "who": who}


def decide(box, a, clock, free, lanes_left, port):
    actions = []
    cargo_label = CARGO[a["cargo"]]["label"] if a["cargo"] in CARGO else a["cargo"]

    if a["cooling_fix"]:
        left = fmt_hours(a["hours_left"])
        if a["damaged"]:
            actions.append(act("ESCALATE", "Cargo past its safe temperature",
                               "Survey the cargo and tell the owner", "Reefer tech"))
        elif a["cooling_given"] == "plug":
            actions.append(act("POWER", f"Plug in now at the {port['terminal']} powered reefer stack",
                               f"{cargo_label} reaches damage temperature in {left}", "Reefer tech"))
        elif a["cooling_given"] == "cold_storage":
            reason = "Refrigeration unit has failed" if a["cooling_fix"] == "cold_storage" \
                else "No reefer plug free"
            actions.append(act("COLD_STORE", f"Move cargo to {port['cold_store']}",
                               f"{reason}; {cargo_label.lower()} has {left} left", "Cold store"))
        else:
            actions.append(act("WAIT_COOL", "Next in line for a plug",
                               f"Every plug and cold slot went to boxes at higher risk; "
                               f"{cargo_label.lower()} is safe for about {left}", "Reefer tech"))

    if a["holds"] and box["location"] == "gate":
        actions.append(act("MOVE", "Move out of the gate lane to the exam staging area",
                           "Frees the lane for boxes that can actually leave", "Yard ops"))

    if a["record_wrong"]:
        actions.append(act("SAFETY", "Heavy equipment only",
                           f"Recorded as empty but the scale shows about {a['net_kg']:,} kg of cargo. "
                           "An empty handler could drop it", "Yard ops"))
    if a["weight_issue"]:
        if box.get("inspecting"):
            actions.append(act("REWEIGH", "Reweigh in progress", "Results due this hour", "Inspection"))
        elif free["inspection"] > 0:
            free["inspection"] -= 1
            actions.append(act("REWEIGH", "Reweigh on a second scale at the terminal",
                               "Confirm the reading before anyone relies on it", "Inspection"))
        else:
            actions.append(act("WAIT_INSPECT", "Queued for reweigh",
                               "Both inspection slots are taken by more urgent boxes", "Inspection"))

    if a["holds"]:
        names = ", ".join(h["description"] for h in a["holds"])
        actions.append(act("HOLD", "Keep release blocked", f"Active: {names}", "Customs broker"))

    if a["record_wrong"]:
        actions.append(act("RECORD", "Ask the carrier to correct the empty record",
                           "Send the scale ticket to the carrier and the customs broker", "Planner"))

    blocked = (a["holds"] or a["weight_issue"] or a["record_wrong"]
               or (a["cooling_fix"] and not a["damaged"]))
    leaving = False
    if not blocked:
        lane = pick_lane(box, lanes_left)
        free_h = box["lfd_h"] - clock
        if lane:
            leaving = True
            if lane == box["lane"]:
                actions.append(act("RELEASE", f"Release via open gate lane {lane}",
                                   "Clean box: no holds, weight checks out", "Gate"))
            else:
                actions.append(act("REROUTE", f"Reroute to open gate lane {lane} (booked {box['lane']} is down)",
                                   "Clean box: no holds, weight checks out", "Gate"))
            actions[-1]["lane"] = lane
        elif free_h > 48:
            actions.append(act("DELAY", "Delay, can wait",
                               f"{int(free_h)} h of free time left; lane slots go to urgent boxes", "Gate"))
        else:
            actions.append(act("NEXT", "Release next hour",
                               "No lane slot left this hour", "Gate"))

    reefer = box["sources"].get("reefer")
    if reefer and a["loaded"] and not a["cooling_fix"] and not leaving:
        actions.append(act("MONITOR", "Keep on power and watch",
                           f"Cooling: {reefer['temp_c']} °C, set to {reefer['set_point']} °C",
                           "Reefer tech"))
    return actions


TIERS = {1: "P1 Critical", 2: "P2 High", 3: "P3 Standard", 4: "P4 Can wait"}


def ticket_tier(box, a, clock, mode):
    free_h = box["lfd_h"] - clock
    if (a["hours_left"] is not None and not a["damaged"]) or (box.get("critical") and mode == "crisis"):
        return 1
    if a["cargo"] in CARGO or a["weight_issue"] or a["record_wrong"] or box.get("critical") or free_h < 24:
        return 2
    if free_h > 48 and not a["holds"]:
        return 4
    return 3


def assign_cooling(items, free):
    warming = [i for i in items if i["a"]["cooling_fix"] and not i["a"]["damaged"]]
    for item in sorted(warming, key=lambda i: i["a"]["hours_left"]):
        a = item["a"]
        if a["cooling_fix"] == "plug" and free["reefer_plugs"] > 0:
            free["reefer_plugs"] -= 1
            a["cooling_given"] = "plug"
        elif free["cold_storage"] > 0 and not a["holds"]:
            free["cold_storage"] -= 1
            a["cooling_given"] = "cold_storage"


def make_plan(state):
    clock = state["clock"]
    free = dict(state["free"])
    lanes_left = lane_capacity(state)
    port = PORTS[state["port"]]

    items = []
    for box in state["boxes"]:
        if box["location"] == "released":
            continue
        a = assess(box, state["untrusted"])
        points, reasons = score(box, a, clock, state["mode"])
        items.append({"box": box, "a": a, "score": points, "reasons": reasons})

    items.sort(key=lambda item: (-item["score"], item["box"]["arrival"]))
    assign_cooling(items, free)
    for rank, item in enumerate(items, start=1):
        item["rank"] = rank
        item["tier"] = ticket_tier(item["box"], item["a"], clock, state["mode"])
        item["actions"] = decide(item["box"], item["a"], clock, free, lanes_left, port)
    return items


def explain_problem_box(box, a):
    src = box["sources"]
    scale, reefer = src["scale"], src["reefer"]
    story = []
    if not a["carrier_ok"]:
        story.append("The carrier system is down or may be compromised, so we ignore its records. "
                     f"The scale still shows about {a['net_kg']:,} kg of cargo, and we act on that.")
    elif box.get("weight_checked") and a["record_wrong"]:
        story.append(f"The reweigh confirmed it: about {a['net_kg']:,} kg of cargo. The carrier's "
                     "empty record is wrong, and stays dangerous until they correct it.")
    elif a["record_wrong"]:
        story.append(f"The scale read {scale['measured_kg']:,} kg. Minus the {box['tare_kg']:,} kg "
                     f"empty weight, that is about {a['net_kg']:,} kg of cargo. The carrier's "
                     "empty record is days old, so for weight we trust the scale.")
    if a["cargo_guessed"]:
        story.append(f"There is no manifest we can use, but the reefer is set to {reefer['set_point']} °C, a "
                     f"frozen-cargo setting. We treat it as {CARGO[a['cargo']]['label'].lower()} "
                     "until someone shows otherwise.")
    if a["hours_left"] is not None:
        story.append(f"Because it is loaded, the warming alarm is real: {reefer['temp_c']} °C now, "
                     f"cargo damage at about {CARGO[a['cargo']]['damage_at']} °C in roughly "
                     f"{fmt_hours(a['hours_left'])}. This is the box that can't wait.")
    elif reefer["powered"] and reefer["temp_c"] > reefer["set_point"] + 0.5:
        story.append(f"It is plugged in and cooling: {reefer['temp_c']} °C, heading back to "
                     f"{reefer['set_point']} °C.")
    elif reefer["powered"]:
        story.append(f"It is plugged in and holding at {reefer['temp_c']} °C. The cargo is safe.")
    if a["holds"]:
        story.append("A box declared empty that weighs this much is exactly what customs flags, "
                     "so the hold makes sense. A hold blocks release, not handling: we can still "
                     "plug it in, move it and reweigh it.")
    if box["location"] == "gate":
        story.append(f"Moving it out of the gate lane lets the {QUEUE_SIZE} boxes behind it keep flowing.")
    return story


def explain_box(box, a, clock):
    src = box["sources"]
    reefer = src.get("reefer")
    story = []
    if box.get("critical"):
        story.append(f"{CRITICAL[box['critical']]} cargo: it moves to the front in a crisis.")

    if not a["carrier_ok"]:
        story.append(f"The carrier system isn't trusted right now, so we go by the scale: "
                     f"about {a['net_kg']:,} kg of cargo.")
    elif a["weight_issue"]:
        story.append(f"The carrier declared {src['carrier']['declared_kg']:,} kg of cargo, but the scale "
                     f"shows about {a['net_kg']:,} kg. It gets reweighed before anyone relies on it.")
    else:
        story.append(f"The weight checks out: about {a['net_kg']:,} kg of cargo, as declared.")

    if reefer and a["cargo"] in CARGO:
        profile = CARGO[a["cargo"]]
        if a["hours_left"] is not None:
            reason = "its refrigeration unit has failed" if not reefer["unit_ok"] else "it has no power"
            story.append(f"It carries {profile['label'].lower()} and {reason}: {reefer['temp_c']} °C now, "
                         f"damage at {profile['damage_at']} °C in about {fmt_hours(a['hours_left'])}.")
        else:
            story.append(f"It carries {profile['label'].lower()} and is cooling at {reefer['temp_c']} °C "
                         f"(set to {reefer['set_point']} °C).")
    elif not reefer:
        story.append("It's a dry box, so temperature isn't a concern.")

    if a["holds"]:
        names = ", ".join(h["description"] for h in a["holds"])
        story.append(f"Active hold: {names}. Release is blocked until it clears; handling is still allowed.")
    else:
        story.append("No customs holds.")

    free_h = box["lfd_h"] - clock
    if free_h <= 0:
        story.append(f"Its free time ran out {fmt_hours(-free_h)} ago, so charges are running.")
    else:
        story.append(f"Free time ends in {fmt_hours(free_h)}.")
    return story
