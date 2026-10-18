from copy import deepcopy

import planner
from config import CARGO, DEMURRAGE_TIERS, SIM_HOURS


def daily_rate(days_over):
    for days, rate in DEMURRAGE_TIERS:
        if days is None or days_over < days:
            return rate
    return DEMURRAGE_TIERS[-1][1]


def hourly_charge(box, clock):
    hours_over = clock - box["lfd_h"]
    return daily_rate(hours_over / 24) / 24 if hours_over > 0 else 0.0


def accrued_charges(box, until):
    end = box.get("released_at", until)
    return sum(hourly_charge(box, h) for h in range(int(box["lfd_h"]), int(end)))


def _free_held_resources(state, box):
    if box.get("on_plug"):
        box["on_plug"] = False
        state["free"]["reefer_plugs"] += 1
    if box["location"] == "cold_storage":
        state["free"]["cold_storage"] += 1


def apply_actions(state, plan):
    unsafe = 0
    for item in plan:
        box = item["box"]
        for action in item["actions"]:
            kind = action["type"]
            unsafe += action.get("unsafe", 0)
            if kind == "POWER":
                box["sources"]["reefer"]["powered"] = True
                box["on_plug"] = True
                state["free"]["reefer_plugs"] -= 1
                if box["location"] == "gate":
                    box["location"] = "reefer_rack"
            elif kind == "COLD_STORE":
                _free_held_resources(state, box)
                box["location"] = "cold_storage"
                state["free"]["cold_storage"] -= 1
            elif kind == "MOVE":
                box["location"] = "hold_area"
            elif kind == "REWEIGH" and not box.get("inspecting"):
                box["inspecting"] = True
                state["free"]["inspection"] -= 1
            elif kind in ("RELEASE", "REROUTE"):
                _free_held_resources(state, box)
                box["location"] = "released"
                box["released_at"] = state["clock"]
    return unsafe


def pass_one_hour(state):
    spoiled = 0
    clock = state["clock"]
    for box in state["boxes"]:
        if box["location"] == "released":
            continue
        src = box["sources"]

        if box.get("inspecting"):
            box["inspecting"] = False
            box["weight_checked"] = True
            state["free"]["inspection"] += 1

        customs = src["customs"]
        if customs["clears_at"] is not None and customs["clears_at"] <= clock + 1:
            for hold in customs["holds"]:
                hold["status"] = "released"

        reefer = src.get("reefer")
        profile = CARGO.get(box["truth"]["cargo"])
        if reefer and profile and box["truth"]["loaded"]:
            if box["location"] == "cold_storage" or (reefer["powered"] and reefer["unit_ok"]):
                reefer["temp_c"] = round(max(reefer["set_point"], reefer["temp_c"] - 3.0), 1)
            else:
                rate = profile["warm_rate"] * (0.5 if reefer["powered"] else 1.0)
                reefer["temp_c"] = round(reefer["temp_c"] + rate, 1)
            if reefer["temp_c"] >= profile["damage_at"] and not box.get("damaged"):
                box["damaged"] = True
                spoiled += 1

        for name in ("carrier", "scale", "customs", "reefer"):
            if name in src:
                src[name]["age_min"] += 60
    state["clock"] += 1
    return spoiled


def fifo_plan(state):
    slots = sum(planner.lane_capacity(state).values())
    plugs = state["free"]["reefer_plugs"]
    plan = []
    for box in sorted(state["boxes"], key=lambda b: b["arrival"]):
        if box["location"] == "released" or slots == 0:
            continue
        src = box["sources"]
        holds = [h for h in src["customs"]["holds"] if h["status"] == "hold"]
        if box["location"] == "hold_area" and holds:
            continue
        slots -= 1
        says_empty = src["carrier"]["says"] == "EMPTY"
        loaded = box["truth"]["loaded"]
        reefer = src.get("reefer")
        actions = []
        if holds:
            actions.append({"type": "MOVE", "unsafe": int(says_empty and loaded)})
            if reefer and not reefer["powered"] and not says_empty and plugs > 0:
                plugs -= 1
                actions.append({"type": "POWER"})
        else:
            a = planner.assess(box)
            actions.append({"type": "RELEASE", "unsafe": int(a["weight_issue"] is not None)})
        plan.append({"box": box, "actions": actions})
    return plan


def run(state, strategy, hours=SIM_HOURS):
    sim = deepcopy(state)
    start_clock = sim["clock"]
    result = {"released": 0, "spoiled": 0, "charges": 0.0, "unsafe": 0}
    for _ in range(hours):
        if strategy == "planner":
            plan = planner.make_plan(sim)
        elif strategy == "fifo":
            plan = fifo_plan(sim)
        else:
            plan = []
        result["unsafe"] += apply_actions(sim, plan)
        result["charges"] += sum(hourly_charge(b, sim["clock"]) for b in sim["boxes"]
                                 if b["location"] != "released")
        result["spoiled"] += pass_one_hour(sim)
    result["released"] = sum(1 for b in sim["boxes"]
                             if b["location"] == "released" and b.get("released_at", -1) >= start_clock)
    result["waiting"] = sum(1 for b in sim["boxes"] if b["location"] != "released")
    result["charges"] = round(result["charges"])

    waits = [(b["released_at"] - start_clock + 1) if b["location"] == "released" else hours
             for b in sim["boxes"] if b.get("critical")]
    result["critical_wait"] = round(sum(waits) / len(waits), 1) if waits else None
    return result


def compare(state):
    return {name: run(state, name) for name in ("hold_all", "fifo", "planner")}


def advance(state):
    plan = planner.make_plan(state)
    apply_actions(state, plan)
    spoiled = pass_one_hour(state)
    done = sum(1 for item in plan for a in item["actions"] if a["type"] in ("RELEASE", "REROUTE"))
    state["log"].insert(0, f"Hour {state['clock']}: released {done} boxes"
                           + (f", {spoiled} cargo lost" if spoiled else ""))
    return state
