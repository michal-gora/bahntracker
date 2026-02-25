"""
Model Train Synchronization Server

Connects to geops.io WebSocket API, tracks a real S3 train going toward
Mammendorf/Maisach, and drives the state machine that controls the model
train and station display.

Architecture:
    - ONE state machine on this server (train_state_machine.py)
    - Model train = dumb I/O (receives SPEED/STOP, sends HALL)
    - Station display = dumb I/O (receives STATION commands)

Usage:
    python sbahn.py
    Then type 'h' + Enter to simulate a HALL sensor trigger.
    Type 's' + Enter to see current status.
    Type 'q' + Enter to quit.
"""

import asyncio
import json
import sys
import traceback
from datetime import datetime
import websockets

from train_state_machine import TrainStateMachine, State
from outputs import PrintModelOutput, PrintStationOutput
from tcp_model_output import TcpModelOutput, tcp_model_server
from tcp_station_output import TcpStationOutput, tcp_station_server

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"

# Destinations we're looking for
TARGET_DESTINATIONS = ["Mammendorf", "Maisach"]
PING_TIMEOUT = 10  # seconds - if no PING received from geops.io, consider connection dead


def load_stations(path: str = "travel_times.json") -> list:
    """Load station list from travel_times.json."""
    with open(path) as f:
        data = json.load(f)
    return data["stations"]


# ── WebSocket helper functions ──────────────────────────────────────────

async def get_station_uic(ws, station_name: str) -> str | None:
    """Get UIC code for a station."""
    await ws.send("GET station")
    try:
        async with asyncio.timeout(5):
            async for msg in ws:
                data = json.loads(msg)
                if data.get("source") == "station":
                    content = data.get("content", {})
                    props = content.get("properties", {})
                    name = props.get("name", "")
                    uic = props.get("uic")
                    network = props.get("networkLines")
                    if station_name in name and network:
                        print(f"✅ Station: {name} → UIC: {uic}")
                        return uic
    except asyncio.TimeoutError:
        print("⏱️  Timeout getting station UIC")
    return None


async def get_incoming_trains(ws, uic: str, max_trains: int = 100) -> list:
    """Get timetable entries for a station."""
    await ws.send(f"GET timetable_{uic}")
    trains = []
    try:
        async with asyncio.timeout(5):
            async for msg in ws:
                data = json.loads(msg)
                if data.get("source", "").startswith("timetable_"):
                    content = data.get("content", {})
                    train_number = content.get("train_number")
                    destination = (content.get("to") or ["Unknown"])[0]
                    aimed_ms = content.get("aimedDepartureTime") or content.get("time", 0)
                    estimated_ms = content.get("departureTime") or aimed_ms
                    time_str = datetime.fromtimestamp(aimed_ms / 1000).strftime("%H:%M")
                    state = content.get("state")

                    # Filter out trains that are clearly not running (CANCELLED state if it exists)
                    if state == "CANCELLED":
                        continue

                    trains.append({
                        "number": train_number,
                        "destination": destination,
                        "time": time_str,
                        "timestamp": aimed_ms,        # scheduled (no delay) — used as base for live delay updates
                        "estimated_ms": estimated_ms, # current best estimate including known delay
                        "state": state,
                        "has_realtime": content.get("has_realtime_journey", False),
                    })
                    if len(trains) >= max_trains:
                        break
    except asyncio.TimeoutError:
        pass
    trains.sort(key=lambda t: t["timestamp"])
    return trains


def pick_target_train(trains: list, exclude_before_ms: float = 0) -> int | None:
    """Pick first train going to one of our target destinations in the next 30 minutes.
    
    Args:
        trains:           Timetable list from get_incoming_trains().
        exclude_before_ms: Skip trains whose scheduled timestamp is <= this value.
                          Pass the scheduled_ms of the last tracked train so stale
                          timetable entries for already-passed trains are ignored,
                          even if they still appear as 'upcoming' in the API.
    """
    import time
    now_ms = time.time() * 1000
    max_future_ms = now_ms + (30 * 60 * 1000)  # 30 minutes from now

    for t in trains:
        dest = t.get("destination", "")
        timestamp = t.get("timestamp", 0)
        number = t.get("number")

        # Skip trains at or before the last tracked train's scheduled slot
        if timestamp <= exclude_before_ms:
            continue

        # Only consider trains departing in the next 30 minutes
        if timestamp < now_ms or timestamp > max_future_ms:
            continue

        if any(d in dest for d in TARGET_DESTINATIONS):
            print(f"🎯 Selected: Train {number} → {dest} @ {t['time']}")
            return number
    return None


# ── Live tracking with state machine ───────────────────────────────────

async def keep_alive(ws):
    """Send a text PING message every 10 seconds — required by the geops.io API to keep the connection alive."""
    while True:
        try:
            await asyncio.sleep(PING_TIMEOUT)
            await ws.send("PING")
        except Exception:
            break


async def subscribe_bbox(ws):
    """Subscribe to live BBOX data (call once per WebSocket connection)."""
    await ws.send("BUFFER 100 100")
    await asyncio.sleep(0.1)
    await ws.send("BBOX 1269000 6087000 1350000 6200000 5 tenant=sbm")
    print("📡 Subscribed to BBOX live data\n")


async def track_with_state_machine(ws, train_number: int, sm: TrainStateMachine, scheduled_ms: float):
    """
    Feed live train data into the state machine until the real train departs Fasanenpark
    (SM enters DRIVING_TO_NONAME). From that point the model runs autonomously back to
    noname and waits for the next train — no more API input needed for this cycle.
    """
    print(f"👁️  Watching for train {train_number}...\n")

    last_real_state = None  # Track the real train's last reported state

    async for message in ws:
        try:
            data = json.loads(message)
            source = data.get("source", "")
            content = data.get("content")

            if source == "buffer":
                # Buffer contains a batch of updates
                for item in content or []:
                    if not item:
                        continue
                    trajectory = item.get("content")
                    new_real = _process_train_update(trajectory, train_number, sm, last_real_state, scheduled_ms)
                    if new_real is not None:
                        last_real_state = new_real

            elif source.startswith("trajectory"):
                # Individual trajectory update
                new_real = _process_train_update(content, train_number, sm, last_real_state, scheduled_ms)
                if new_real is not None:
                    last_real_state = new_real

        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"❌ Error processing update: {e}")
            traceback.print_exc()

        # Once the real train departs Fasanenpark the SM drives back to noname on its own.
        # No more API updates are needed for this train — return so the caller can pick the next one.
        if sm.state == State.DRIVING_TO_NONAME:
            print("\n🏁 Train passed Fasanenpark. Model returning to noname autonomously...\n")
            return


def _process_train_update(
    data: dict, train_number: int, sm: TrainStateMachine, last_reported_state: str | None,
    scheduled_ms: float
) -> str | None:
    """
    Process a single train update. Feed state changes to the state machine.
    Returns the new real state if it changed, else None.
    """
    if not isinstance(data, dict):
        return None

    props = data.get("properties", {})
    if props.get("train_number") != train_number:
        return None

    new_state = props.get("state")
    raw_coords = props.get("raw_coordinates")

    # raw_coordinates is already [lon, lat] in EPSG:4326
    coordinates = None
    if raw_coords and len(raw_coords) >= 2:
        coordinates = [raw_coords[0], raw_coords[1]]  # [lon, lat]

    # Only feed state machine on actual state CHANGES
    if new_state and new_state != last_reported_state:
        now = datetime.now().strftime("%H:%M:%S")
        delay = props.get("delay") or 0
        delay_str = f" (delay: {delay/1000:.0f}s)" if delay else " (on time)"
        pos_str = f"\n   🗺️  https://www.google.com/maps?q={coordinates[1]},{coordinates[0]}" if coordinates else ""

        arrival_unix = int((scheduled_ms + delay) / 1000)

        icon = "🚉" if new_state == "BOARDING" else "🚆"
        print(f"\n[{now}] {icon} Real train: {new_state}{delay_str}{pos_str}")

        sm.on_api_state_change(new_state, coordinates, arrival_unix)
        return new_state

    return None


# ── Stdin listener for simulated HALL events ────────────────────────────

async def stdin_listener(sm: TrainStateMachine):
    """Listen for keyboard input to simulate HALL events and control."""
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)

    print("⌨️  Controls: [h] HALL sensor | [s] Status | [q] Quit\n")

    while True:
        line = await reader.readline()
        cmd = line.decode().strip().lower()

        if cmd == "h":
            now = datetime.now().strftime("%H:%M:%S")
            print(f"\n[{now}] 🧲 HALL sensor triggered!")
            sm.on_hall_sensor()
        elif cmd == "s":
            print(f"\n📊 {sm.status()}")
        elif cmd == "q":
            print("👋 Quitting...")
            raise KeyboardInterrupt
        elif cmd:
            print(f"   Unknown command '{cmd}'. Use: h=HALL, s=status, q=quit")


# ── Main ────────────────────────────────────────────────────────────────

async def main():
    """Main entry point: connect, find train, run state machine."""
    # Load station data
    stations = load_stations()
    print(f"📋 Loaded {len(stations)} stations from travel_times.json")
    for i, st in enumerate(stations):
        tt = st.get("travel_time_to_next")
        tt_str = f" → {tt}s" if tt else ""
        print(f"   {i}: {st['name']}{tt_str}")
    print()

    # Create output interfaces
    model = TcpModelOutput()
    station = TcpStationOutput()

    # Create state machine
    sm = TrainStateMachine(model, station, stations)
    print(f"🔧 State machine initialized: {sm.state.name}\n")

    # Start TCP servers
    tcp_server = await tcp_model_server(model, sm)
    await tcp_station_server(station)
    print()

    # These survive WebSocket reconnections
    stdin_task = asyncio.create_task(stdin_listener(sm))
    last_scheduled_ms: float = 0  # scheduled timestamp of the last tracked train
    uic: int | None = None

    try:
        while True:  # reconnection loop
            try:
                async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
                    print("🔌 Connected to geops.io WebSocket\n")
                    keepalive_task = asyncio.create_task(keep_alive(ws))
                    try:
                        await subscribe_bbox(ws)

                        if uic is None:
                            uic = await get_station_uic(ws, "Fasanenpark")
                            if not uic:
                                print("❌ Could not find Fasanenpark station")
                                return

                        while True:  # main train loop
                            # Ensure the model is at noname before picking a new train.
                            # This guards against reconnects while the model is still
                            # driving back to noname from the previous cycle.
                            if sm.state != State.WAITING_AT_NONAME:
                                print(f"⏳ SM in {sm.state.name}, waiting for model to reach noname before picking next train...")
                                while sm.state != State.WAITING_AT_NONAME:
                                    try:
                                        await asyncio.wait_for(ws.recv(), timeout=0.5)
                                    except asyncio.TimeoutError:
                                        pass

                            trains = await get_incoming_trains(ws, uic)
                            if not trains:
                                print("❌ No trains found in timetable, retrying in 30s...")
                                await asyncio.sleep(30)
                                continue

                            print(f"\n📋 Timetable ({len(trains)} trains):")
                            for t in trains:
                                marker = "→" if any(d in t["destination"] for d in TARGET_DESTINATIONS) else " "
                                skip = " (already passed, skipping)" if t["timestamp"] <= last_scheduled_ms else ""
                                print(f"   {marker} {t['number']} → {t['destination']} @ {t['time']}{skip}")

                            train_number = pick_target_train(trains, exclude_before_ms=last_scheduled_ms)
                            if not train_number:
                                print(f"⏳ No suitable train in the next 30 minutes, retrying in 60s...")
                                await asyncio.sleep(60)
                                continue

                            print(f"\n{'='*60}")
                            print(f"  TRACKING TRAIN {train_number}")
                            print(f"  State machine: {sm.state.name}")
                            print(f"{'='*60}\n")

                            scheduled_ms = next(t["timestamp"] for t in trains if t["number"] == train_number)
                            estimated_ms = next(t["estimated_ms"] for t in trains if t["number"] == train_number)

                            # Send initial ETA immediately using departureTime (already includes known delay).
                            # Will be refined on every live API update as delay changes.
                            sm.eta_to_fasanenpark = int(estimated_ms / 1000)
                            sm.station.send_eta(sm.eta_to_fasanenpark)

                            await track_with_state_machine(ws, train_number, sm, scheduled_ms)
                            last_scheduled_ms = scheduled_ms
                            # Loop back to top — the wait-for-WAITING_AT_NONAME check
                            # at the top of this loop will block until the HALL sensor fires.

                    finally:
                        keepalive_task.cancel()
                        try:
                            await keepalive_task
                        except asyncio.CancelledError:
                            pass

            except websockets.exceptions.ConnectionClosed as e:
                print(f"\n🔌 WebSocket connection closed ({e}). Reconnecting in 5s...")
                last_scheduled_ms = 0  # allow re-picking after reconnect
                await asyncio.sleep(5)
            except OSError as e:
                print(f"\n🔌 Network error ({e}). Reconnecting in 10s...")
                await asyncio.sleep(10)

    except KeyboardInterrupt:
        print("\n👋 Stopped by user")
    finally:
        stdin_task.cancel()

    print(f"\n📊 Final: {sm.status()}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bye!")
        sys.exit(0)
