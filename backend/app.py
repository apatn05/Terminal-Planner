"""
Terminal planner web server. Run:  python backend/app.py   then open http://127.0.0.1:5001
"""

import os
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

import live_data
import model
import planner
import simulate
import twists
from config import CARGO, CRITICAL, LOADED_MARGIN_KG, WEIGHT_TOLERANCE
from ports import PORTS
from scenario import build_scenario

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"


def load_env_file():
    """Read KEY=value lines from .env so nobody has to fight with shell exports."""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


load_env_file()
app = Flask(__name__, static_folder=str(FRONTEND), static_url_path="")
state = build_scenario()
ships = live_data.ShipFeed(os.environ.get("AISSTREAM_API_KEY", ""), state["port"], PORTS[state["port"]]["box"])


def source_cards(box, a):
    """The four stories, each with what it says and what we trust it for."""
    src = box["sources"]
    carrier, scale, customs, reefer = src["carrier"], src["scale"], src["customs"], src["reefer"]
    holds = a["holds"]
    cargo = CARGO.get(a["cargo"], {})
    if not a["carrier_ok"]:
        carrier_card = {"name": "carrier", "title": "Carrier record", "says": "UNTRUSTED",
                        "detail": "Carrier system down or hacked; ignored for now",
                        "age_min": carrier["age_min"], "conflict": True,
                        "trust": "nothing right now", "untrusted": True}
    else:
        carrier_card = {"name": "carrier", "title": "Carrier record", "says": carrier["says"],
                        "detail": "Contradicted by the reweigh"
                                  if box.get("weight_checked") and a["record_wrong"]
                                  else carrier.get("note", ""),
                        "age_min": carrier["age_min"],
                        "conflict": a["record_wrong"], "trust": planner.TRUST["carrier"]}
    carrier_card["verdict"] = ("Ignored: system not trusted" if not a["carrier_ok"]
                               else "Paperwork, outvoted" if a["record_wrong"] else "Trusted")
    return [
        carrier_card,
        {"name": "scale", "title": "Terminal scale", "says": f"{scale['measured_kg']:,} kg",
         "detail": f"{scale['scale_id']}" + (" · confirmed by reweigh" if box.get("weight_checked") else ""),
         "weight_check": weight_check(box, a),
         "age_min": scale["age_min"], "conflict": a["record_wrong"],
         "trust": planner.TRUST["scale"], "verdict": "Trusted: physical reading"},
        {"name": "customs", "title": f"Customs · {PORTS[state['port']]['customs']}",
         "says": "HOLD" if holds else "CLEAR",
         "detail": ", ".join(h["description"] for h in holds) or "No active holds",
         "age_min": customs["age_min"], "conflict": bool(holds), "trust": planner.TRUST["customs"],
         "verdict": "Binding: cannot release" if holds else "Clear to release"},
        {"name": "reefer", "title": "Reefer plug",
         "says": f"{reefer['temp_c']:+.1f} °C",
         "detail": f"Set to {reefer['set_point']} °C · "
                   + ("cooling" if reefer["powered"] and reefer["unit_ok"] else "no power, warming"),
         "age_min": reefer["age_min"], "conflict": a["hours_left"] is not None,
         "damage_at": cargo.get("damage_at"), "trust": planner.TRUST["reefer"],
         "verdict": "Trusted: cargo is perishable" if a["loaded"] else "Trusted"},
    ]


def weight_check(box, a):
    """Slide 10: tare + declared cargo = expected, compared with what the scale measured."""
    carrier = box["sources"]["carrier"]
    declared = carrier["declared_kg"] if a["carrier_ok"] else None
    measured = box["sources"]["scale"]["measured_kg"]
    if declared is None:
        return {"text": f"Carrier data ignored, so no expected weight. Scale: {measured:,} kg", "ok": None}
    expected = box["tare_kg"] + declared
    gap = measured - expected
    ok = abs(gap) <= WEIGHT_TOLERANCE * max(expected, 1) if declared else abs(gap) <= LOADED_MARGIN_KG
    return {"text": f"Tare {box['tare_kg']:,} + declared {declared:,} = expected {expected:,} kg · "
                    f"measured {measured:,} · gap {gap:+,} kg",
            "ok": ok,
            "result": f"Within ±{int(WEIGHT_TOLERANCE * 100)}%: pass" if ok
                      else f"Outside ±{int(WEIGHT_TOLERANCE * 100)}%: flag"}


def problem_ticket(box, a, item):
    """The slide 12 priority ticket, filled in from live state."""
    reefer, scale = box["sources"]["reefer"], box["sources"]["scale"]
    actions = {x["type"] for x in item["actions"]}
    if "POWER" in actions:
        route = f"{PORTS[state['port']]['terminal']} powered reefer stack, plug in now"
    elif reefer["powered"] and reefer["unit_ok"]:
        route = "On a powered reefer plug, cooling"
    else:
        route = "Waiting for the next free plug"
    if a["record_wrong"]:
        weight = f"Declared empty, scale reads {scale['measured_kg'] / 1000:.1f} t: mismatch flagged"
    else:
        weight = f"Scale reads {scale['measured_kg'] / 1000:.1f} t"
    holds = ", ".join(h["description"] for h in a["holds"])
    return {
        "tier": planner.TIERS[item["tier"]],
        "need": f"Reefer, setpoint {reefer['set_point']} °C",
        "route": route,
        "weight": weight,
        "customs": f"Hold ({holds}), exam first in queue" if holds else "Cleared",
        "action": "Inspect fast. Do not release." if a["holds"] else "Release when weight and cooling check out.",
    }


# Pipeline stages in display order.
PIPELINE = ["Discharged", "Docs pending", "Under review", "On hold", "Cleared", "Released"]


def container_status(box, a):
    """Derive the container's current pipeline stage from its live fields."""
    if box["location"] == "released":
        return "Released"
    if a["holds"]:
        return "On hold"
    # All holds have been lifted (holds list in source is non-empty but none active).
    src_holds = box["sources"]["customs"]["holds"]
    if src_holds and not a["holds"]:
        return "Cleared"
    if box.get("inspecting") or box.get("weight_checked"):
        return "Under review"
    return "Discharged"


def queue_row(item, clock):
    box, a = item["box"], item["a"]
    flags = []
    if a["hours_left"] is not None:
        flags.append("warming")
    if a["holds"]:
        flags.append("hold")
    if a["weight_issue"]:
        flags.append("weight")
    if box.get("critical"):
        flags.append("critical")
    cargo = CARGO[a["cargo"]]["label"] if a["cargo"] in CARGO else (a["cargo"] or "Unknown")
    return {
        "rank": item["rank"], "tier": item["tier"], "id": box["id"], "arrival": box["arrival"],
        "kind": box["kind"], "size": box["size"], "cargo": cargo,
        "cargo_guessed": a["cargo_guessed"], "perishable": a["cargo"] in CARGO,
        "location": box["location"], "score": item["score"], "reasons": item["reasons"],
        "flags": flags, "hours_left": a["hours_left"], "damaged": a["damaged"],
        "free_h": box["lfd_h"] - clock,
        "charges": round(simulate.accrued_charges(box, clock)),
        "actions": item["actions"], "problem": box.get("problem", False),
        "critical": CRITICAL.get(box.get("critical")),
        "model": item.get("model"),
        "status": container_status(box, a),
    }


def summary(plan):
    clock = state["clock"]
    lanes = planner.lane_capacity(state)
    in_terminal = [b for b in state["boxes"] if b["location"] != "released"]
    return {
        "in_terminal": len(in_terminal),
        "critical_cargo": sum(1 for b in in_terminal if b.get("critical")),
        "critical": sum(1 for item in plan
                        if item["a"]["weight_issue"] or (item["a"]["hours_left"] or 99) < 6),
        "lanes_open": len(lanes), "lanes_total": len(state["lanes"]),
        "gate_per_hour": sum(lanes.values()),
        "plugs_free": state["free"]["reefer_plugs"],
        "cold_free": state["free"]["cold_storage"],
        "inspection_free": state["free"]["inspection"],
        "charges_total": round(sum(simulate.accrued_charges(b, clock) for b in state["boxes"])),
        "charges_per_hour": round(sum(simulate.hourly_charge(b, clock) for b in in_terminal)),
    }


@app.get("/")
def index():
    return send_from_directory(FRONTEND, "index.html")


@app.get("/api/state")
def get_state():
    plan = planner.make_plan(state)
    # The model's suggestion for every box, checked against what the planner decided.
    lanes_open = {lane["id"] for lane in state["lanes"] if lane["status"] == "open"}
    for item in plan:
        item["model"] = model.suggest(item["box"], item["a"], item["actions"], state["clock"], lanes_open)
    problem = next((item for item in plan if item["box"].get("problem")), None)
    payload = {
        "clock": state["clock"], "started_at": state["started_at"],
        "mode": state["mode"], "twists": twists.listing(state),
        "port": {"id": state["port"], **PORTS[state["port"]]},
        "ports": [{"id": key, "name": p["name"], "country": p["country"]} for key, p in PORTS.items()],
        "lanes": state["lanes"], "log": state["log"][:8],
        "summary": summary(plan),
        "queue": [queue_row(item, state["clock"]) for item in plan],
        "comparison": simulate.compare(state),
        "model_rows": len(model.ROWS),
    }
    if problem:
        box, a = problem["box"], problem["a"]
        payload["problem"] = {
            "id": box["id"], "carrier": box["carrier"], "lane": box["lane"],
            "location": box["location"], "size": box["size"], "rank": problem["rank"],
            "hours_left": a["hours_left"],
            "sources": source_cards(box, a),
            "story": planner.explain_problem_box(box, a),
            "actions": problem["actions"],
            "ticket": problem_ticket(box, a, problem),
            "model": problem["model"],
            "status": container_status(box, a),
            "pipeline": PIPELINE,
        }
    return jsonify(payload)


@app.post("/api/next-hour")
def next_hour():
    simulate.advance(state)
    return get_state()


@app.post("/api/lanes/<lane_id>/toggle")
def toggle_lane(lane_id):
    for lane in state["lanes"]:
        if lane["id"] == lane_id:
            if lane["status"] == "open":
                lane.update(status="down", reason="Closed by planner")
            else:
                lane.update(status="open", reason="")
    return get_state()


@app.post("/api/mode/<mode>")
def set_mode(mode):
    # The dual-use switch: same engine, same hard rules, different priorities.
    if mode in ("daily", "crisis") and mode != state["mode"]:
        state["mode"] = mode
        label = "Crisis mode" if mode == "crisis" else "Daily operations"
        state["log"].insert(0, f"Hour {state['clock']}: switched to {label}")
    return get_state()


@app.post("/api/twists/<name>")
def apply_twist(name):
    twists.apply(state, name)
    return get_state()


@app.post("/api/port/<port_id>")
def set_port(port_id):
    # Twist 2, global expansion: same engine and rules, another port's names, map and ships.
    if port_id in PORTS and port_id != state["port"]:
        state["port"] = port_id
        ships.set_port(port_id, PORTS[port_id]["box"])
        state["log"].insert(0, f"Hour {state['clock']}: switched to {PORTS[port_id]['name']}")
    return get_state()


@app.post("/api/reset")
def reset():
    port = state["port"]            # keep the port the user picked
    state.clear()
    state.update(build_scenario())
    state["port"] = port
    return get_state()


@app.get("/api/ships")
def get_ships():
    return jsonify(ships.snapshot())


@app.get("/api/berths")
def get_berths():
    return jsonify(live_data.get_berths())


if __name__ == "__main__":
    # Not 5000: on macOS, AirPlay Receiver also listens there and Safari can end up talking to it.
    port = int(os.environ.get("PORT", 5001))
    ships.start()
    print(f"Terminal planner running at http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
