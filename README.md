# Terminal Planner

Dual-use container prioritization for the terminal planner. Built for the Ports
track (Terminal49) at the InnovateLA / USC Viterbi dual-use hackathon.

The prompt we picked: *"When ports are disrupted, everything gets held. How do we
keep the most urgent shipments moving?"*

And the box that comes with it: the carrier says it's empty, the scale says it's
heavy, customs has a hold on it, and the reefer says it's warming. Meanwhile 100
other boxes need the same gate, half the lanes are down and charges keep adding up.

Our answer is to not hold everything. Terminal Planner isolates the one box it
isn't sure about, protects the cargo that can't wait, follows every hold, and
keeps the rest moving. Every decision comes with a reason you can read.

## Dual use

The same engine runs on a normal day and in a disaster. Day to day it cuts
charges and spoilage. In a crisis it triages, so medical supplies go first, and
it still won't make an illegal or unsafe move. You don't need a separate crisis system.

| | Daily operations | Crisis |
|---|---|---|
| Goal | Keep charges and spoilage down | Get critical cargo (medical, relief, defense) out first |
| Critical cargo score | +15 | +90 |
| Hard rules (holds, weight, safety) | Same | Same |

The operator flips the switch at the top of the dashboard. We deliberately
didn't automate that part.

### Twists

There are four disruptions you can trigger with one click. The planner isn't told
anything special. It just re-plans from what the terminal looks like now.

| Twist | What changes | What the planner does |
|---|---|---|
| Power failure | Half the reefer plugs go down | Gives the remaining plugs and cold storage to whatever spoils first |
| Carrier system down or hacked | Carrier records can't be trusted | Ignores them and uses scale, customs and reefer data only |
| Flood or earthquake | Several lanes close at once | Reroutes clean boxes to open lanes, delays what can wait |
| Relief cargo surge | 8 medical/emergency boxes arrive | Small boost in daily mode, first out in crisis mode |

## Running it

```bash
pip install -r requirements.txt
python backend/app.py
```

Then open http://127.0.0.1:5001. We use port 5001 because on a Mac, 5000 is
taken by AirPlay.

Live ships are optional. Get a free key from [aisstream.io](https://aisstream.io),
copy `.env.example` to `.env` and paste the key in. Without a key everything else
still works.

## The main idea

1. **Trust each fact, not each source.** The scale is right about weight, customs
   about release, the reefer about temperature and the carrier about the booking.
2. **The four stories explain each other.** The box is heavy, so it's loaded, so the
   warming alarm is real. A -20 °C set point means frozen cargo even without a
   manifest. And "empty but heavy" is probably why customs flagged it.
3. **A hold blocks release, not handling.** We can still plug it in, move it out
   of the gate lane and reweigh it while the hold stays in place.
4. **Everything else gets what's left, most urgent first:** cargo about to spoil,
   then weight problems, then boxes past their free time.

## Files

| File | What it does |
|---|---|
| `backend/config.py` | All the numbers: lanes, plugs, cargo temperatures, charge rates |
| `backend/ports.py` | The 14 ports (name, map area, customs authority, currency) |
| `backend/scenario.py` | Builds the simulated terminal. It's seeded, so the demo is the same every run |
| `backend/planner.py` | The decision engine: `assess()` → `score()` → `make_plan()` |
| `backend/simulate.py` | Steps time forward an hour; compares Hold all vs First come vs Terminal Planner |
| `backend/twists.py` | The four disruptions |
| `backend/model.py` | Decision tree trained on `data/container_history.csv` (100 past decisions) |
| `train_model.py` | Prints the model's accuracy and the rules it learned |
| `backend/live_data.py` | Real data: Port of LA berths and aisstream ships, both with fallbacks |
| `backend/app.py` | Flask server. JSON API plus the dashboard |
| `frontend/app.js` | Draws the dashboard and sends button clicks to the API |

The container status pipeline (Unloaded → Docs pending → … → Released) was built
with IBM Bob.

### How the planner decides

Hard rules are plain yes/no checks. A score can never outweigh them, in either mode:
- nothing is released while a hold is active
- nothing is released while the weight is in doubt or the record is wrong
- a box that might be loaded never goes on empty-container equipment
- held cargo can't be unloaded, so a held box doesn't get cold storage

The score only decides who gets resources first:

| Situation | Points |
|---|---|
| Critical cargo (daily / crisis) | 15 / 90 |
| Cargo damaged in under 2 h / under 6 h / later | 100 / 70 / 40 |
| Weight in doubt | 50 |
| Free time over / under 24 h / under 48 h | 30 / 20 / 10 |

Plugs and cold storage don't use the score. They go to whichever cargo spoils
soonest. After that, boxes go in score order: an inspection slot if it needs
reweighing, a move out of the gate lane if it's held, and a lane if it's clean
(its booked lane, or another open one). When lanes run out, clean boxes with
plenty of free time get delayed.

Spoilage countdown = (damage temperature − current temperature) ÷ warming rate.

## Global expansion

The Port dropdown switches between 14 ports: Los Angeles/Long Beach, Singapore,
Rotterdam, Antwerp-Bruges, Hamburg, Felixstowe, New York/New Jersey, Santos,
Jebel Ali, Nhava Sheva, Shanghai, Busan, Hong Kong and Tokyo.

What changes is the map, the live AIS ships, the customs authority, the terminal
and cold store names, and the currency (approximate exchange rates). The engine
and hard rules don't change at all. Note that AIS coverage isn't the same
everywhere, so some ports show a lot more ships than others.

## The model

It's a small scikit-learn decision tree that runs locally on a laptop. It learns
from a dataset of 100 past container decisions using 7 inputs: reefer or dry,
whether the carrier says empty, weight, customs hold, how far off the temperature
is, whether the gate is open, and hours waited. It predicts an action and a risk level.

- **Accuracy:** 95% on unseen rows (5-fold cross-validation). Run
  `python train_model.py` to see it along with the rules it learned.
- **It only suggests.** Every suggestion gets checked against the planner:
  agrees ✓, overridden by a rule ✗ (say it wants to release but there's a customs
  hold), or differs ≠ (say the planner can see a reefer lost power, which isn't
  in the dataset).
- **Limitation:** the dataset records decisions, not outcomes. So the model learns
  what people chose, not what actually worked best. With a terminal's real
  incident history it could learn from outcomes instead.

## What's real vs simulated

| Data | Source | Status |
|---|---|---|
| Port berth lines | Port of Los Angeles, data.lacity.org (public domain) | Real (cached after first load) |
| Ships in the port area | aisstream.io WebSocket | Real, live (needs free key) |
| Carrier record, scale, customs holds, reefer readings | Generated in `scenario.py` | Simulated, since there's no public source |
| Lanes, plugs, cold storage, inspection slots, charges | `config.py` | Simulated |

Customs holds use the same format as Terminal49's `holds_at_pod_terminal`, so real
holds could be plugged in later. Container IDs use the real ISO 6346 check digit,
but the carrier names are made up. Every panel is labeled LIVE, CACHED, RECORDED,
TEST or SIMULATED so it's clear which is which.

If live data drops during the demo, ships fall back to the last real recording
(it saves every minute while live). The planner doesn't depend on either.

## Assumptions we'd want to check with a real terminal

- Demurrage: $200/day for the first 4 days past last free day, then $400/day
- Gate throughput: 12 trucks per lane per hour
- Cargo damage temperatures and warming rates (`CARGO` in config.py)

## Demo (about 2 minutes)

1. **The box.** Four cards, four stories. The "What is really going on" panel
   ties them together: the scale makes the alarm real, the set point gives away
   the cargo, and a hold isn't a freeze. 41 minutes on the countdown.
2. **The decision.** Power, move, heavy equipment only, reweigh, keep the hold,
   fix the record. That's six actions instead of just "hold it".
3. **The queue.** Vaccines and berries get the other plugs. Chocolate waits since
   it has 11 hours. Boxes booked on dead lanes get rerouted.
4. **Disaster.** Apply Flood and Relief cargo surge. Lanes close and 8 relief
   boxes join the back of the queue.
5. **Switch to Crisis.** The relief boxes jump to the top and critical cargo wait
   drops in the comparison. The customs hold on the problem box stays put.
6. **Power failure + carrier down.** The planner rations plugs by spoilage time
   and keeps going without carrier records. Final comparison: holding everything
   loses 11 cargoes, first come loses 2 and makes 3 unsafe moves, Terminal
   Planner loses none and makes none.
7. **Approve plan.** It runs the next hour for real.
