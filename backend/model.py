import csv
from pathlib import Path

from sklearn.tree import DecisionTreeClassifier

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "container_history.csv"

FEATURES = ["is_reefer", "says_empty", "weight_t", "on_hold", "temp_gap", "gate_open", "waiting_h"]


def row_to_features(row):
    current = row["Current Temperature (°C)"]
    required = row["Required Temperature (°C)"]
    temp_gap = float(current) - float(required) if current and required else 0
    return [
        1 if row["Container Type"] == "Refrigerated" else 0,
        1 if row["Carrier Report"] == "Empty" else 0,
        float(row["Actual Weight (kg)"]) / 1000,
        1 if row["Customs Status"] == "Hold" else 0,
        temp_gap,
        1 if row["Gate Status"] == "Open" else 0,
        float(row["Waiting Time (hours)"]),
    ]


def box_to_features(box, clock, lanes_open):
    src = box["sources"]
    reefer = src.get("reefer")
    on_hold = any(h["status"] == "hold" for h in src["customs"]["holds"])
    return [
        1 if box["kind"] == "reefer" else 0,
        1 if src["carrier"]["says"] == "EMPTY" else 0,
        src["scale"]["measured_kg"] / 1000,
        1 if on_hold else 0,
        reefer["temp_c"] - reefer["set_point"] if reefer else 0,
        1 if box["lane"] in lanes_open else 0,
        box.get("waiting_h", 0) + clock,
    ]


def load_rows():
    with open(DATA_FILE, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def train(rows):
    X = [row_to_features(r) for r in rows]
    action_tree = DecisionTreeClassifier(max_depth=5, random_state=0)
    action_tree.fit(X, [r["Recommended Action"] for r in rows])
    risk_tree = DecisionTreeClassifier(max_depth=5, random_state=0)
    risk_tree.fit(X, [r["Risk Level"] for r in rows])
    return action_tree, risk_tree


try:
    ROWS = load_rows()
    ACTION_TREE, RISK_TREE = train(ROWS)
    print(f"Model trained on {len(ROWS)} past decisions")
except Exception as err:
    ROWS, ACTION_TREE, RISK_TREE = [], None, None
    print(f"Model not loaded ({err}). The planner still works without it.")


AGREES_WITH = {
    "Hold for Customs": {"HOLD"},
    "Hold; Restore Cooling & Inspect": {"HOLD", "POWER", "COLD_STORE", "WAIT_COOL"},
    "Restore Cooling & Inspect": {"POWER", "COLD_STORE", "WAIT_COOL"},
    "Inspect Weight Discrepancy": {"REWEIGH", "WAIT_INSPECT", "SAFETY"},
    "Release via Gate": {"RELEASE", "REROUTE"},
    "Reroute to Open Gate": {"REROUTE", "RELEASE"},
    "Prioritize Gate Processing": {"RELEASE", "REROUTE"},
}
RELEASES = {"Release via Gate", "Reroute to Open Gate", "Prioritize Gate Processing"}


def suggest(box, a, actions, clock, lanes_open):
    if ACTION_TREE is None:
        return None
    x = [box_to_features(box, clock, lanes_open)]
    action = ACTION_TREE.predict(x)[0]
    risk = RISK_TREE.predict(x)[0]
    confidence = round(max(ACTION_TREE.predict_proba(x)[0]) * 100)

    planner_types = {act["type"] for act in actions}
    if action in RELEASES and (a["holds"] or a["weight_issue"] or a["record_wrong"]):
        check = "override"
        note = "Rules override: " + ("customs hold is binding" if a["holds"] else "weight must be checked first")
    elif planner_types & AGREES_WITH.get(action, set()):
        check = "agree"
        note = "Agrees with the planner"
    elif planner_types & {"POWER", "COLD_STORE", "WAIT_COOL"}:
        check = "differs"
        note = "Planner also sees the reefer has no power, which the dataset doesn't record"
    elif planner_types & {"DELAY", "NEXT"}:
        check = "differs"
        note = "Planner delays it: lane slots go to more urgent boxes first"
    else:
        check = "differs"
        note = "Planner chose differently"
    return {"action": action, "risk": risk, "confidence": confidence, "check": check, "note": note}
