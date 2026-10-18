"""
Disruptions we can throw at the terminal during the demo. Each twist changes
the state once and stays on until Reset. The planner isn't told anything
special: it just re-plans from whatever the terminal now looks like.
"""

import random

from scenario import relief_boxes

TWISTS = {
    "power_failure": {"title": "Power failure",
                      "effect": "Half the reefer plugs go down"},
    "carrier_down":  {"title": "Carrier system down or hacked",
                      "effect": "Carrier records can't be trusted"},
    "flood":         {"title": "Flood or earthquake",
                      "effect": "Several lanes close at once"},
    "relief_surge":  {"title": "Relief cargo surge",
                      "effect": "Medical and emergency boxes arrive"},
}


def power_failure(state):
    # Every other plugged-in reefer loses power, and so do half the free plugs.
    plugged = sorted((b for b in state["boxes"] if b.get("on_plug")), key=lambda b: b["id"])
    lost = plugged[::2]
    for box in lost:
        box["on_plug"] = False                      # that plug is dead, so it isn't freed
        box["sources"]["reefer"]["powered"] = False
    state["free"]["reefer_plugs"] //= 2
    return f"Power failure: {len(lost)} reefers lost power, free plugs down to {state['free']['reefer_plugs']}"


def carrier_down(state):
    state["untrusted"].append("carrier")
    return "Carrier system down or hacked: planning from scale, customs and reefer data only"


def flood(state):
    open_lanes = [lane for lane in state["lanes"] if lane["status"] == "open"]
    closed = open_lanes[1::2]                       # every other open lane
    for lane in closed:
        lane.update(status="down", reason="Flooded")
    return f"Flood: lanes {', '.join(l['id'] for l in closed)} closed"


def relief_surge(state):
    rng = random.Random(len(state["boxes"]))        # repeatable, like the rest of the scenario
    new = relief_boxes(rng, first_arrival=len(state["boxes"]) + 1)
    state["boxes"].extend(new)
    return f"Relief cargo surge: {len(new)} medical and emergency boxes arrived"


APPLY = {"power_failure": power_failure, "carrier_down": carrier_down,
         "flood": flood, "relief_surge": relief_surge}


def apply(state, name):
    if name not in APPLY or name in state["twists"]:
        return
    state["twists"].append(name)
    state["log"].insert(0, f"Hour {state['clock']}: {APPLY[name](state)}")


def listing(state):
    return [{"id": key, **info, "active": key in state["twists"]} for key, info in TWISTS.items()]
