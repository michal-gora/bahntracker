import asyncio
import json
import websockets

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"

async def check_timetable_at_station(ws, station_name, uic):
    """Check what arrival/departure info we get from timetable"""
    await ws.send(f"GET timetable_{uic}")
    print(f"📡 Getting timetable for {station_name} (UIC: {uic})\n")
    
    trains = []
    try:
        async with asyncio.timeout(5):
            async for msg in ws:
                data = json.loads(msg)
                if data.get('source', '').startswith('timetable_'):
                    content = data.get('content', {})
                    trains.append(content)
                    if len(trains) >= 5:
                        break
    except asyncio.TimeoutError:
        pass
    
    return trains


async def main():
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print("🔌 Connected\n")
        print("="*80)
        print("CHECKING ARRIVAL VS DEPARTURE TIMES IN TIMETABLE")
        print("="*80)
        print()
        
        # Check a middle station (not start or end) - Fasanenpark
        trains = await check_timetable_at_station(ws, "Fasanenpark", "8001963")
        
        print(f"Found {len(trains)} trains at Fasanenpark:\n")
        
        for i, train in enumerate(trains[:5], 1):
            print(f"--- Train {i}: {train.get('train_number')} to {train.get('to', ['?'])[0]} ---")
            print(f"  Line: {train.get('line', {}).get('name')}")
            print(f"  State: {train.get('state')}")
            print()
            print(f"  🕐 time: {train.get('time')}")
            print(f"  📤 departureTime: {train.get('departureTime')}")
            print(f"  📥 arrivalTime: {train.get('arrivalTime')}")
            print(f"  🎯 aimedDepartureTime: {train.get('aimedDepartureTime')}")
            print(f"  🎯 aimedArrivalTime: {train.get('aimedArrivalTime')}")
            print(f"  ⏱️  departureDelay: {train.get('departureDelay')}")
            print(f"  ⏱️  arrivalDelay: {train.get('arrivalDelay')}")
            print()
        
        print("="*80)
        print("ANALYSIS:")
        print("="*80)
        print()
        
        # Analyze pattern
        has_arrival = sum(1 for t in trains if t.get('arrivalTime') is not None)
        has_departure = sum(1 for t in trains if t.get('departureTime') is not None)
        
        print(f"Trains with arrivalTime: {has_arrival}/{len(trains)}")
        print(f"Trains with departureTime: {has_departure}/{len(trains)}")
        print()
        
        if has_arrival == 0:
            print("❌ PROBLEM: No trains have arrivalTime!")
            print("   This means we CAN'T use timetable to get arrival times")
            print()
            print("   Possible reasons:")
            print("   1. Fasanenpark might be considered a departure-only station in timetable")
            print("   2. API only provides departure times, not arrivals")
            print("   3. We need to query differently")
        else:
            print("✅ Arrival times ARE available in timetable!")


if __name__ == "__main__":
    asyncio.run(main())
