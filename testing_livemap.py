import websockets
import asyncio
import json
from datetime import datetime

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"


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
                    print(json.dumps(content, indent=4))
                    train_number = content.get("train_number")
                    destination = (content.get("to") or ["Unknown"])[0]
                    time_ms = content.get("time", 0)
                    time_str = datetime.fromtimestamp(time_ms / 1000).strftime("%H:%M")
                    state = content.get("state")
                    
                    # Filter out trains that are clearly not running (CANCELLED state if it exists)
                    if state == "CANCELLED":
                        continue
                    
                    trains.append({
                        "number": train_number,
                        "destination": destination,
                        "time": time_str,
                        "timestamp": time_ms,
                        "state": state,
                        "has_realtime": content.get("has_realtime_journey", False),
                    })
                    if len(trains) >= max_trains:
                        break
    except asyncio.TimeoutError:
        pass
    trains.sort(key=lambda t: t["timestamp"])
    return trains

TARGET_DESTINATIONS = ["Mammendorf", "Maisach"]

def pick_target_train(trains: list) -> int | None:
    """Pick first train going to one of our target destinations in the next 30 minutes."""
    import time
    now_ms = time.time() * 1000
    max_future_ms = now_ms + (30 * 60 * 1000)  # 30 minutes from now
    
    for t in trains:
        dest = t.get("destination", "")
        timestamp = t.get("timestamp", 0)
        
        # Only consider trains departing in the next 30 minutes
        if timestamp < now_ms or timestamp > max_future_ms:
            continue
        
        if any(d in dest for d in TARGET_DESTINATIONS):
            print(f"🎯 Selected: Train {t['number']} → {t['destination']} @ {t['time']}")
            return t["number"]
    return None

async def get_trains(ws):
    # await ws.send("BUFFER 100 100")
    # await asyncio.sleep(0.1)
    await ws.send("BBOX 1120000 6340000 1180000 6390000 11 mots=rail line_tags=S")

    last_real_state = None  # Track the real train's last reported state

    async for message in ws:
        try:
            data = json.loads(message)
            print(json.dumps(data, indent=4))

        except Exception as e:
            print(f"An error occurred: {e}")



#–––––––––– main() ––––––––––

async def main():
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        try:
            uic = await get_station_uic(ws, "Marienplatz")
            trains = await get_incoming_trains(ws, uic, 10)
            # await get_trains(ws)

            # await ws.send("BUFFER 100 100")
            # await ws.send("GET station_schematic")
            # async for message in ws:
            #     try:
            #         print(message)
            #         data = json.loads(message)
            #         json.dumps(data, indent=4)
            #     except:
            #         print("Excepted")
            #         pass

        except KeyboardInterrupt:
            print("\n👋 Stopped by user")
            

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bye!")
