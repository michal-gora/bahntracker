#!/usr/bin/env python3
"""
Magnet-Station Mode Server

Alternative operating mode where the model train moves between physical magnet
stations on the track, corresponding to real-world S-Bahn stations.

Layout:  Fasanenpark (home) ←──── Unterhaching ←── Taufkirchen ←── Furth ←── Deisenhofen
         magnet index:  4            3                2              1          0

The model train starts and waits at Fasanenpark (magnet 4).  When the tracked
real-world train boards at Deisenhofen, the model drives to magnet 0.  Each
subsequent boarding event advances the model to the matching magnet.

No state machine, no HALL feedback.  We simply:
  1. Reuse sbahn.py to select and track a real train.
  2. On each BOARDING event, map the real station to a magnet index.
  3. Send LOOPS:X + SPEED:constant so the model passes through the right
     number of magnets to reach the target.
  4. Display "Fasanenpark" statically on the station LCD and update the ETA.

Usage:
    python magnet_station_server.py
    Then type 's' + Enter for status, 'q' + Enter to quit.
"""

import asyncio
import json
import sys
import time
import traceback
from datetime import datetime
import websockets

from tcp_model_output import TcpModelOutput, MODEL_TCP_PORT, PING_TIMEOUT as MODEL_PING_TIMEOUT
from tcp_station_output import TcpStationOutput, STATION_TCP_PORT, PING_TIMEOUT as STATION_PING_TIMEOUT
from sbahn import (
    WS_URL,
    TARGET_DESTINATIONS,
    PING_TIMEOUT as WS_PING_TIMEOUT,
    load_stations,
    get_incoming_trains,
    pick_target_train,
    keep_alive,
    subscribe_bbox,
)

# ── Configuration ───────────────────────────────────────────────────────

# Stations in track order (Deisenhofen → Fasanenpark).
# Magnet 0 is nearest to the start of the route, magnet 4 = Fasanenpark (home).
MAGNET_STATIONS = ["Deisenhofen", "Furth", "Taufkirchen", "Unterhaching", "Fasanenpark"]

# Constant speed for moving between magnets (PWM fraction 0–1)
DRIVE_SPEED = 0.60

# Timeout (seconds) — if selected train sends nothing for this long, re-select
NO_DATA_TIMEOUT = 90

# ── Magnet-index helpers ────────────────────────────────────────────────


def build_station_to_magnet(stations: list) -> dict[str, int]:
    """Map station names to magnet indices using MAGNET_STATIONS ordering.

    Only stations in MAGNET_STATIONS get an index; others are ignored.
    """
    mapping: dict[str, int] = {}
    for magnet_idx, magnet_name in enumerate(MAGNET_STATIONS):
        # Match by station name prefix (handles "Furth" vs "Furth(b Deisenhofen)")
        for st in stations:
            if st["name"].startswith(magnet_name) or magnet_name.startswith(st["name"]):
                mapping[st["name"]] = magnet_idx
                break
    return mapping


def find_station_by_coords(stations: list, coords: list[float]) -> str | None:
    """Find the nearest station to [lon, lat] coordinates.

    Returns the station name, or None if nothing is close enough.
    """
    if not coords or len(coords) < 2:
        return None
    lon, lat = coords[0], coords[1]
    best_name = None
    best_dist = float("inf")
    for st in stations:
        dlat = st["lat"] - lat
        dlon = st["lon"] - lon
        dist = dlat * dlat + dlon * dlon
        if dist < best_dist:
            best_dist = dist
            best_name = st["name"]
    # Sanity: if nearest station is more than ~2 km away, ignore
    if best_dist > 0.001:  # roughly 1 km² threshold
        return None
    return best_name


# ── TCP server for model (simplified — no HALL processing) ──────────────

async def model_tcp_server(model: TcpModelOutput, restart_event: asyncio.Event):
    """TCP server for the model controller.  Handles HELLO/PING only (no HALL)."""

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        print(f"📡 Model TCP connection from {peer}")
        last_ping = asyncio.get_running_loop().time()

        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            hello = line.decode().strip()
            if hello != "HELLO:MODEL":
                print(f"❌ Expected HELLO:MODEL, got: {hello!r}")
                writer.close()
                return
            writer.write(b"ACK\n")
            await writer.drain()
            model.set_writer(writer)

            while True:
                try:
                    now = asyncio.get_running_loop().time()
                    if now - last_ping > MODEL_PING_TIMEOUT:
                        print(f"⚠️  No PING from model for {MODEL_PING_TIMEOUT}s — closing")
                        break
                    line = await asyncio.wait_for(reader.readline(), timeout=1.0)
                    if not line:
                        break
                    msg = line.decode().strip()
                    if msg == "PING":
                        last_ping = asyncio.get_running_loop().time()
                        writer.write(b"PONG\n")
                        await writer.drain()
                    elif msg == "HALL":
                        # We don't use HALL in this mode, but acknowledge receipt
                        print("🧲 HALL received (ignored in magnet-station mode)")
                    elif msg:
                        print(f"⚠️  Unknown message from model: {msg!r}")
                except asyncio.TimeoutError:
                    continue
        except asyncio.TimeoutError:
            print("❌ Model timed out during handshake")
        except Exception as e:
            print(f"❌ Model TCP error: {e}")
        finally:
            model.disconnect()
            try:
                writer.close()
            except Exception:
                pass

    server = await asyncio.start_server(handle_client, "0.0.0.0", MODEL_TCP_PORT)
    print(f"🌐 Model TCP server on 0.0.0.0:{MODEL_TCP_PORT}")
    return server


# ── TCP server for station display (simplified) ────────────────────────

async def station_tcp_server(station: TcpStationOutput, restart_event: asyncio.Event):
    """TCP server for the station display.  Handles HELLO/PING/RESTART."""

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        print(f"📡 Station TCP connection from {peer}")
        last_ping = asyncio.get_running_loop().time()

        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            hello = line.decode().strip()
            if hello != "HELLO:STATION":
                print(f"❌ Expected HELLO:STATION, got: {hello!r}")
                writer.close()
                return
            writer.write(b"ACK\n")
            await writer.drain()
            station.set_writer(writer)

            while True:
                try:
                    now = asyncio.get_running_loop().time()
                    if now - last_ping > STATION_PING_TIMEOUT:
                        print(f"⚠️  No PING from station for {STATION_PING_TIMEOUT}s — closing")
                        break
                    line = await asyncio.wait_for(reader.readline(), timeout=1.0)
                    if not line:
                        break
                    msg = line.decode().strip()
                    if msg == "PING":
                        last_ping = asyncio.get_running_loop().time()
                        writer.write(b"PONG\n")
                        await writer.drain()
                    elif msg == "RESTART":
                        print("🔄 RESTART received from station display")
                        restart_event.set()
                    elif msg:
                        print(f"⚠️  Unknown message from station: {msg!r}")
                except asyncio.TimeoutError:
                    continue
        except asyncio.TimeoutError:
            print("❌ Station timed out during handshake")
        except Exception as e:
            print(f"❌ Station TCP error: {e}")
        finally:
            station.disconnect()
            try:
                writer.close()
            except Exception:
                pass

    server = await asyncio.start_server(handle_client, "0.0.0.0", STATION_TCP_PORT)
    print(f"🌐 Station TCP server on 0.0.0.0:{STATION_TCP_PORT}")
    return server


# ── Core tracking loop ──────────────────────────────────────────────────

async def track_magnet_mode(
    ws,
    train_number: int,
    scheduled_ms: float,
    stations: list,
    station_to_magnet: dict[str, int],
    model: TcpModelOutput,
    station_out: TcpStationOutput,
    restart_event: asyncio.Event,
    model_magnet: int,
) -> tuple[bool, int]:
    """
    Track a real train and drive the model between magnets on BOARDING events.

    Returns (departed: bool, model_magnet: int).
      - departed=True  → train completed its journey (passed Fasanenpark)
      - departed=False → aborted (restart / timeout / WS closed)
      - model_magnet   → current magnet index of the model train
    """
    print(f"👁️  Watching for train {train_number} (magnet-station mode)...")
    print(f"   Model currently at magnet {model_magnet} ({MAGNET_STATIONS[model_magnet]})\n")

    departed = False
    last_train_msg = time.time()
    last_api_state: str | None = None
    home_magnet = len(MAGNET_STATIONS) - 1  # Fasanenpark index

    restart_event.clear()

    async for message in ws:
        # Manual restart?
        if restart_event.is_set():
            print("🔄 Restart requested — aborting tracking")
            restart_event.clear()
            return False, model_magnet

        # No-data timeout (before first departure)
        if not departed and time.time() - last_train_msg > NO_DATA_TIMEOUT:
            print(f"⏱️  No data from train {train_number} for {NO_DATA_TIMEOUT}s — soft-restart")
            return False, model_magnet

        try:
            data = json.loads(message)
            source = data.get("source", "")
            content = data.get("content")

            items = []
            if source == "buffer":
                items = content or []
            elif source.startswith("trajectory"):
                items = [data]

            for item in items:
                trajectory = item.get("content") if source == "buffer" else item.get("content")
                if not isinstance(trajectory, dict):
                    continue

                props = trajectory.get("properties", {})
                if props.get("train_number") != train_number:
                    continue

                last_train_msg = time.time()
                new_state = props.get("state")
                if not new_state or new_state == last_api_state:
                    continue
                last_api_state = new_state

                raw_coords = props.get("raw_coordinates")
                coordinates = None
                if raw_coords and len(raw_coords) >= 2:
                    coordinates = [raw_coords[0], raw_coords[1]]

                delay = props.get("delay") or 0
                delay_str = f" (delay: {delay / 1000:.0f}s)" if delay else " (on time)"
                now_str = datetime.now().strftime("%H:%M:%S")
                icon = "🚉" if new_state == "BOARDING" else "🚆"
                print(f"\n[{now_str}] {icon} Real train: {new_state}{delay_str}")

                # Update ETA to Fasanenpark on every state change
                arrival_unix = int((scheduled_ms + delay) / 1000)
                station_out.send_eta(arrival_unix)

                if new_state == "BOARDING":
                    departed = True

                    # Which station is the real train boarding at?
                    nearest = find_station_by_coords(stations, coordinates)
                    if nearest and nearest in station_to_magnet:
                        real_magnet = station_to_magnet[nearest]
                    elif nearest:
                        # Station exists but isn't in our magnet set — ignore
                        print(f"   📍 Real train at {nearest} — not in magnet range, ignoring")
                        continue
                    else:
                        print(f"   📍 Could not determine station from coords {coordinates}")
                        continue

                    print(f"   📍 Real train boarding at: {nearest} (magnet {real_magnet})")
                    print(f"   🚂 Model currently at: magnet {model_magnet} ({MAGNET_STATIONS[model_magnet]})")

                    # Compute forward delta using modular arithmetic.
                    # The model track is a loop: after Fasanenpark (index 4) the
                    # model travels forward and reaches Deisenhofen (index 0) next,
                    # so Deisenhofen is physically AHEAD even though 0 < 4 numerically.
                    # Example: model at 4, real at 0 → (0-4) % 5 = 1 (one magnet forward) ✓
                    num_stations = len(MAGNET_STATIONS)
                    delta = (real_magnet - model_magnet) % num_stations

                    if delta == 0:
                        print(f"   ✅ Model already at correct magnet — no movement needed")
                        continue

                    loops_to_send = delta - 1  # LOOPS:0 = stop on next magnet (1 magnet ahead)
                    print(f"   🚀 Advancing model by {delta} magnet(s): LOOPS:{loops_to_send}, SPEED:{DRIVE_SPEED}")

                    model.send_loops(loops_to_send)
                    model.send_speed(DRIVE_SPEED)
                    model_magnet = real_magnet
                    print(f"   📍 Model now heading to magnet {model_magnet} ({MAGNET_STATIONS[model_magnet]})")

                elif new_state == "DRIVING" and departed:
                    # Real train departed a station — just log it
                    if coordinates:
                        nearest = find_station_by_coords(stations, coordinates)
                        if nearest:
                            print(f"   📍 Real train departed from: {nearest}")

                    # If the real train just departed Fasanenpark, we're done
                    if model_magnet == home_magnet:
                        print(f"   🏁 Real train past Fasanenpark — cycle complete")
                        return True, model_magnet

        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"❌ Error processing update: {e}")
            traceback.print_exc()

    # WebSocket closed before completion
    return False, model_magnet


# ── Stdin listener ──────────────────────────────────────────────────────

async def stdin_listener(restart_event: asyncio.Event, status_fn):
    """Listen for keyboard input."""
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)

    print("⌨️  Controls: [s] Status | [q] Quit\n")

    while True:
        line = await reader.readline()
        cmd = line.decode().strip().lower()
        if cmd == "s":
            print(f"\n📊 {status_fn()}")
        elif cmd == "q":
            print("👋 Quitting...")
            raise KeyboardInterrupt
        elif cmd:
            print(f"   Unknown command '{cmd}'. Use: s=status, q=quit")


# ── Main ────────────────────────────────────────────────────────────────

async def main():
    """Main entry point for magnet-station mode."""
    stations = load_stations()
    print(f"📋 Loaded {len(stations)} stations from travel_times.json")

    # Build station→magnet mapping
    station_to_magnet = build_station_to_magnet(stations)
    print(f"\n🧲 Magnet-station mapping:")
    for name, idx in sorted(station_to_magnet.items(), key=lambda x: x[1]):
        print(f"   magnet {idx}: {name}")
    print()

    if len(station_to_magnet) != len(MAGNET_STATIONS):
        missing = set(MAGNET_STATIONS) - {m for m in MAGNET_STATIONS if any(
            name.startswith(m) or m.startswith(name) for name in station_to_magnet)}
        print(f"⚠️  Warning: could not map all magnet stations. Missing: {missing}")

    # Output interfaces
    model = TcpModelOutput()
    station_out = TcpStationOutput()
    restart_event = asyncio.Event()

    # Start TCP servers
    await model_tcp_server(model, restart_event)
    await station_tcp_server(station_out, restart_event)
    print()

    # Static station display: always show "Fasanenpark"
    station_out.send_station("Fasanenpark", "AT_STATION_VALID")

    # Model starts at Fasanenpark (home) = last magnet
    home_magnet = len(MAGNET_STATIONS) - 1
    model_magnet = home_magnet

    def status_fn():
        return (f"Model at magnet {model_magnet} ({MAGNET_STATIONS[model_magnet]}), "
                f"home={MAGNET_STATIONS[home_magnet]}")

    stdin_task = asyncio.create_task(stdin_listener(restart_event, status_fn))
    last_scheduled_ms: float = 0

    # Get Fasanenpark UIC
    fasanenpark = next((s for s in stations if s["name"] == "Fasanenpark"), None)
    if not fasanenpark or not fasanenpark.get("uic"):
        print("❌ Fasanenpark not found in travel_times.json")
        return
    uic: str = fasanenpark["uic"]
    print(f"📍 Fasanenpark UIC: {uic}\n")

    try:
        while True:  # reconnection loop
            try:
                async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
                    print("🔌 Connected to geops.io WebSocket\n")
                    keepalive_task = asyncio.create_task(keep_alive(ws))

                    try:
                        await subscribe_bbox(ws)

                        while True:  # train selection loop
                            trains = await get_incoming_trains(ws, uic)
                            if not trains:
                                print("❌ No trains found, retrying in 30s...")
                                await asyncio.sleep(30)
                                continue

                            print(f"\n📋 Timetable ({len(trains)} trains):")
                            for t in trains:
                                marker = "→" if any(d in t["destination"] for d in TARGET_DESTINATIONS) else " "
                                skip = " (skipping)" if t["timestamp"] <= last_scheduled_ms else ""
                                print(f"   {marker} {t['number']} → {t['destination']} @ {t['time']}{skip}")

                            train_number = pick_target_train(trains, exclude_before_ms=last_scheduled_ms)
                            if not train_number:
                                print("⏳ No suitable train in next 30 min, retrying in 60s...")
                                await asyncio.sleep(60)
                                continue

                            print(f"\n{'='*60}")
                            print(f"  TRACKING TRAIN {train_number} (magnet-station mode)")
                            print(f"  Model at magnet {model_magnet} ({MAGNET_STATIONS[model_magnet]})")
                            print(f"{'='*60}\n")

                            scheduled_ms = next(t["timestamp"] for t in trains if t["number"] == train_number)
                            estimated_ms = next(t["estimated_ms"] for t in trains if t["number"] == train_number)

                            # Send initial ETA
                            station_out.send_eta(int(estimated_ms / 1000))

                            departed, model_magnet = await track_magnet_mode(
                                ws, train_number, scheduled_ms, stations,
                                station_to_magnet, model, station_out,
                                restart_event, model_magnet,
                            )

                            if departed:
                                last_scheduled_ms = scheduled_ms
                                print(f"\n✅ Train {train_number} cycle complete. Model at magnet {model_magnet}.")

                                # After a full cycle the model is at Fasanenpark (home).
                                # It stays there waiting for the next train.
                                # Reset model to home for the next cycle.
                                model.send_speed(0.0)
                                model_magnet = home_magnet
                                print(f"   Model reset to home (magnet {home_magnet}, {MAGNET_STATIONS[home_magnet]})")
                            else:
                                print(f"⚠️  Tracking aborted for train {train_number} — will retry")

                    finally:
                        keepalive_task.cancel()
                        try:
                            await keepalive_task
                        except asyncio.CancelledError:
                            pass

            except websockets.exceptions.ConnectionClosed as e:
                print(f"\n🔌 WebSocket closed ({e}). Reconnecting in 5s...")
                await asyncio.sleep(5)
            except OSError as e:
                print(f"\n🔌 Network error ({e}). Reconnecting in 10s...")
                await asyncio.sleep(10)

    except KeyboardInterrupt:
        print("\n👋 Stopped by user")
    finally:
        stdin_task.cancel()

    print(f"\n📊 Final: model at magnet {model_magnet} ({MAGNET_STATIONS[model_magnet]})")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bye!")
        sys.exit(0)
