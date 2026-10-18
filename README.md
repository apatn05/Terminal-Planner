# Terminal Planner: dual-use container prioritization

> When ports are disrupted, everything gets held. How do we keep the most urgent
> shipments moving? (Ports vertical, with Terminal49)

> One box, four stories. The carrier says it's empty, the scale says it's heavy,
> customs has a hold on it, and the reefer plug says it's warming. A hundred more
> boxes need the same gate, half the lanes are down, and charges are running.

Terminal Planner doesn't hold everything or close the terminal. It **isolates the box
it isn't sure about, protects the cargo that can't wait, obeys every hold, and
keeps everything else moving**, and it explains each decision.

## Dual use: one engine, two modes

**On a normal day, the same engine cuts charges and spoilage. In a disaster, it
triages, so medical supplies leave first, and nothing illegal or unsafe moves.
You don't need a separate crisis system.**

| | Daily operations | Crisis |
|---|---|---|
| Goal | Keep charges and spoilage down | Get critical cargo (medical, relief, defense-sponsored) out first |
| Critical cargo score | +15 | +90 |
| Hard rules (holds, weight, safety) | Same | Same |

The switch is at the top of the dashboard. The operator decides when to flip it.

### Twists

Four one-click disruptions. The planner isn't told anything special; it just
re-plans from what the terminal now looks like.

| Twist | What changes | What the planner does |
|---|---|---|
| Power failure | Half the reefer plugs go down | Rations the remaining plugs and cold storage by time to spoilage |
| Carrier system down or hacked | Carrier records can't be trusted | Ignores them and plans from scale, customs and reefer data only |
| Flood or earthquake | Several lanes close at once | Reroutes clean boxes to the lanes still open, delays what can wait |
| Relief cargo surge | 8 medical and emergency boxes arrive | Ranks them by mode: a small boost in daily ops, first out in a crisis |

## Run it

```bash
pip install -r requirements.txt
python backend/app.py
```

Open **http://127.0.0.1:5001**.

For live ships, get a free key at [aisstream.io](https://aisstream.io), copy
`.env.example` to `.env`, and paste the key in. Without a key everything else
still works.

## The idea in four sentences

1. **Trust is per fact, not per source.** The scale wins on weight, customs on
   release, the reefer controller on temperature, the carrier on booking.
2. **The stories are connected.** The heavy scale reading means the box is loaded,
   so the warming alarm is real. The reefer's -20 °C setting tells us it's frozen
   cargo even with no manifest. "Empty but heavy" also explains the customs hold.
3. **A hold blocks release, not handling.** We still plug the box in, move it out
   of the gate lane and reweigh it, while release stays blocked.
4. **Then the other 100 boxes get the remaining capacity in order of urgency:**
   cargo about to spoil, then weight problems, then boxes whose free time is over.

## What each file does

| File | Job |
|---|---|
| `backend/config.py` | Every number the planner uses: lanes, plugs, cargo temperatures, charge rates |
| `backend/ports.py` | The 14 ports you can switch between (names, map area, customs authority, currency) |
| `backend/scenario.py` | Builds the simulated terminal (seeded, so the demo is identical every time) |
| `backend/planner.py` | **The decision engine:** `assess()` → `score()` → `make_plan()` |
| `backend/simulate.py` | Moves time forward an hour; runs Hold-all vs First-come vs Terminal Planner |
| `backend/twists.py` | The four disruptions you can apply during the demo |
| `backend/model.py` | Decision tree trained on our dataset of 100 past decisions (`data/container_history.csv`) |
| `train_model.py` | Prints the model's accuracy and the rules it learned |
| `backend/live_data.py` | Real data: Port of LA berths and aisstream ships, each with a fallback |
| `backend/app.py` | Flask server: JSON API and serves the dashboard |
| `frontend/app.js` | Draws the dashboard from the API and sends button clicks back |

### How the planner decides (planner.py)

**Hard rules** are yes/no checks and are never traded against a score, in either mode:
- no release while any hold is active
- no release while the weight is in doubt or the record is wrong
- a box that might be loaded never goes on empty-container equipment
- held cargo is never unloaded, so a held box can't use cold storage

**Score** (only decides who gets resources first):

| Situation | Points |
|---|---|
| Critical cargo (daily / crisis) | 15 / 90 |
| Cargo damage in under 2 h / 6 h / later | 100 / 70 / 40 |
| Weight in doubt | 50 |
| Free time over / under 24 h / under 48 h | 30 / 20 / 10 |

Reefer plugs and cold storage go strictly to whichever cargo spoils soonest.
Then, in score order, each box gets: an inspection slot for reweighing; a move out
of the gate lane if it is held; and, if it is clean, a lane (its booked lane, or
rerouted to another open lane). Clean boxes with plenty of free time are delayed
when lanes run out.

Spoilage countdown = (damage temperature − current temperature) ÷ warming rate.

## Global expansion: one engine, 14 ports

The **Port** picker at the top switches between 14 ports (Los Angeles/Long Beach,
Singapore, Rotterdam, Antwerp-Bruges, Hamburg, Felixstowe, New York/New Jersey,
Santos, Jebel Ali, Nhava Sheva, Shanghai, Busan, Hong Kong, Tokyo). Only the
labels change: map and live AIS ships, customs authority, terminal and cold
store names, and the currency charges are shown in (approximate exchange rates).
The planner engine and its hard rules are exactly the same at every port.
AIS coverage varies by port, so some show more live ships than others.

## The model: learning from past decisions

A small **decision tree** (scikit-learn, free, runs on the laptop) learns from our
dataset of 100 past container decisions. It looks at 7 things: reefer or dry,
carrier says empty, weight, customs hold, how far off the temperature is, gate
open, and hours waited. It predicts a recommended action and a risk level.

- **Accuracy:** 95% on rows it hasn't seen (5-fold cross-validation). Run `python train_model.py` to see it and the rules it learned.
- **It only suggests.** Each suggestion is checked against the planner: agrees ✓, rules override ✗ (e.g. it says release but a customs hold is binding), or differs ≠ (e.g. the planner can see a reefer has lost power, which the dataset doesn't record).
- **Limit:** the dataset records decisions, not outcomes, so the model learns what experts chose, not what worked best. With a terminal's real incident history it would learn from that instead.

## Data: what's real and what's simulated

| Data | Source | Status |
|---|---|---|
| Port berth lines | Port of Los Angeles, data.lacity.org (public domain) | **Real** (cached after first load) |
| Ships in San Pedro Bay | aisstream.io WebSocket | **Real, live** (needs free key) |
| Carrier record, scale, customs holds, reefer telemetry | Generated in `scenario.py` | Simulated: no public source exists |
| Lanes, plugs, cold storage, inspection slots, charges | `config.py` | Simulated |

Customs holds use the same shape as Terminal49's `holds_at_pod_terminal`, so real
holds could replace them later. Container IDs use the real ISO 6346 check-digit
formula; carrier names are fictional. Every panel is labeled LIVE, CACHED,
RECORDED, TEST or SIMULATED.

If live data fails during the demo: ships fall back to the last real recording (saved automatically every minute while
live), and the planner never depends on either.

## Assumptions to double-check

- Demurrage: $200/day for the first 4 days past last free day, then $400/day
- Gate lane throughput: 12 trucks per lane per hour
- Cargo damage temperatures and warming rates in `CARGO` (config.py)

## 2-minute demo

1. **The box.** Four cards, four stories. Read the "what is really going on" panel:
   the scale makes the alarm real, the set point tells us the cargo, and a hold
   isn't a freeze. Countdown: 41 minutes.
2. **The decision.** Power, move, heavy equipment only, reweigh, keep the hold,
   fix the record. Six actions instead of "hold it".
3. **The queue.** Vaccines and berries get the other plugs; chocolate waits
   because it has 11 hours. Boxes booked on dead lanes are rerouted.
4. **Disaster hits.** Apply **Flood** and **Relief cargo surge**. Lanes close,
   8 relief boxes join the back of the queue.
5. **Flip to Crisis.** The relief boxes jump to the top. Watch "Critical cargo
   wait" in the comparison drop. The customs hold on the problem box doesn't move.
6. **Power failure** and **Carrier system down or hacked.** The planner rations
   plugs by spoilage time and keeps working without the carrier's records.
   Comparison: holding everything loses 11 cargoes, first-come loses 2 and makes
   3 unsafe moves, Terminal Planner loses none and makes none.
7. **Approve plan · run next hour.** The plan actually runs.
