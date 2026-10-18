"""
Real, public data from outside the terminal fence.

  berths  Port of Los Angeles berth lines, data.lacity.org (public domain)
  ships   aisstream.io live AIS over WebSocket (free key, server side only)

Every fetch has a fallback, and every result says where it came from
(live / cached / recorded / unavailable) so the UI can label it.
"""

import asyncio
import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


# ---- Berths ----------------------------------------------------------------

BERTHS_URL = "https://data.lacity.org/api/views/9r7y-tdse/rows.json?accessType=DOWNLOAD"
BERTHS_CACHE = DATA_DIR / "berths.json"


def _parse_lines(geom):
    """Berth geometry arrives as GeoJSON or WKT text. Return [[lat, lon], ...] lines."""
    if isinstance(geom, dict):
        coords = geom.get("coordinates", [])
        if geom.get("type") == "LineString":
            coords = [coords]
        lines = [[[lat, lon] for lon, lat, *_ in line] for line in coords]
    elif isinstance(geom, str):
        lines = []
        for part in re.findall(r"\(([^()]+)\)", geom):
            pairs = [p.split() for p in part.split(",")]
            lines.append([[float(p[1]), float(p[0])] for p in pairs if len(p) >= 2])
    else:
        return []
    # Keep only real lat/lon (guards against projected coordinates sneaking in).
    return [l for l in lines if l and all(abs(lat) <= 90 and abs(lon) <= 180 for lat, lon in l)]


def get_berths():
    if BERTHS_CACHE.exists():
        return {"source": "cached", "berths": json.loads(BERTHS_CACHE.read_text())}
    try:
        raw = requests.get(BERTHS_URL, timeout=25).json()
        fields = [c["fieldName"] for c in raw["meta"]["view"]["columns"]]
        geom_i, num_i = fields.index("the_geom"), fields.index("berth_num")
        berths = []
        for row in raw["data"]:
            lines = _parse_lines(row[geom_i])
            if lines:
                berths.append({"berth": row[num_i], "lines": lines})
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return {"source": "unavailable", "berths": []}
    BERTHS_CACHE.write_text(json.dumps(berths))
    return {"source": "live", "berths": berths}


# ---- Ships -----------------------------------------------------------------

AIS_URL = "wss://stream.aisstream.io/v0/stream"
NAV_STATUS = {0: "Under way", 1: "At anchor", 2: "Not under command", 3: "Restricted",
              5: "Moored", 8: "Sailing"}


def ship_type(code):
    if 70 <= code <= 79:
        return "Cargo"
    if 80 <= code <= 89:
        return "Tanker"
    if code in (31, 32, 52):
        return "Tug"
    if 60 <= code <= 69:
        return "Passenger"
    return "Other"


class ShipFeed:
    """Keeps a live picture of ships around the selected port, fed by a background thread."""

    def __init__(self, api_key, port_id, box):
        self.api_key = api_key
        self.port_id, self.box = port_id, box
        self.ships = {}
        self.status = "no_key" if not api_key else "connecting"
        self.lock = threading.Lock()
        self._last_save = 0
        self._loop = self._ws = None

    def set_port(self, port_id, box):
        """Watch a different port: forget the old ships and reconnect with the new area."""
        with self.lock:
            self.port_id, self.box = port_id, box
            self.ships.clear()
            self._last_save = time.time()      # don't overwrite the new port's recording with nothing
            if self.api_key:
                self.status = "connecting"
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)

    def _cache_file(self):
        # One recording per port, so a fallback never shows the wrong harbour.
        name = "ships_recorded.json" if self.port_id == "la_lb" else f"ships_recorded_{self.port_id}.json"
        return DATA_DIR / name

    def start(self):
        if self.api_key:
            threading.Thread(target=lambda: asyncio.run(self._run()), daemon=True).start()

    async def _run(self):
        import websockets   # imported here so the app still runs without it installed
        self._loop = asyncio.get_running_loop()
        delay = 2
        while True:
            try:
                async with websockets.connect(AIS_URL) as ws:   # compression is on by default
                    self._ws = ws
                    await ws.send(json.dumps({
                        "APIKey": self.api_key,
                        "BoundingBoxes": [self.box],
                        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
                    }))
                    async for raw in ws:
                        self.status, delay = "live", 2
                        self._handle(json.loads(raw))
            except Exception as err:
                # The stream has no uptime guarantee: back off and reconnect.
                print(f"AIS stream: {type(err).__name__}: {err} (retrying in {delay}s)")
                self.status = "reconnecting"
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    def _handle(self, msg):
        kind = msg.get("MessageType")
        meta = msg.get("MetaData", {})
        mmsi = meta.get("MMSI")
        if not mmsi or kind not in ("PositionReport", "ShipStaticData"):
            return
        body = msg["Message"][kind]
        with self.lock:
            ship = self.ships.setdefault(mmsi, {"mmsi": mmsi, "type": "Unknown"})
            name = (meta.get("ShipName") or body.get("Name") or "").strip()
            if name:
                ship["name"] = name
            if kind == "PositionReport":
                ship.update(lat=body["Latitude"], lon=body["Longitude"],
                            speed_kt=body.get("Sog"), heading=body.get("TrueHeading"),
                            status=NAV_STATUS.get(body.get("NavigationalStatus"), "Unknown"),
                            seen=time.time())
            else:
                ship["type"] = ship_type(body.get("Type", 0))
                ship["destination"] = (body.get("Destination") or "").strip()
        if time.time() - self._last_save > 60:
            self._save()

    def _save(self):
        self._last_save = time.time()
        recorded = {"recorded_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
                    "ships": self._current()}
        self._cache_file().write_text(json.dumps(recorded))

    def _current(self):
        cutoff = time.time() - 30 * 60       # forget ships not heard from in 30 min
        with self.lock:
            return [s for s in self.ships.values() if "lat" in s and s.get("seen", 0) > cutoff]

    def snapshot(self):
        ships = self._current()
        if ships:
            return {"source": "live", "ships": ships}
        # Nothing live yet: fall back to the last real recording, clearly labelled.
        if self._cache_file().exists():
            saved = json.loads(self._cache_file().read_text())
            return {"source": "recorded", "recorded_at": saved["recorded_at"],
                    "ships": saved["ships"], "status": self.status}
        return {"source": self.status, "ships": []}
