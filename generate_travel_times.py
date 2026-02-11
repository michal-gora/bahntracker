#!/usr/bin/env python3
"""
Generate travel times for S3 stations.

Approach:
1. First try to get scheduled departure times from timetable API
2. Calculate difference between consecutive station departures
3. If API doesn't give good data, allow manual entry

Usage:
    python generate_travel_times.py

Output:
    Updates travel_times.json with calculated times
"""

import asyncio
import json
import websockets
from datetime import datetime

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"

# Load existing config
with open('travel_times.json', 'r') as f:
    config = json.load(f)

STATIONS = config['stations']


async def get_train_at_station(ws, uic, target_train_numbers=None):
    """Get train departure info at a station"""
    await ws.send(f"GET timetable_{uic}")
    
    trains = {}
    try:
        async with asyncio.timeout(5):
            async for msg in ws:
                data = json.loads(msg)
                if data.get('source', '').startswith('timetable_'):
                    content = data.get('content', {})
                    train_num = content.get('train_number')
                    destination = content.get('to', [''])[0]
                    
                    # Only interested in trains going West (Mammendorf/Maisach direction)
                    if destination in ['Mammendorf', 'Maisach']:
                        dep_time = content.get('departureTime')
                        delay = content.get('departureDelay') or 0
                        
                        if target_train_numbers is None or train_num in target_train_numbers:
                            trains[train_num] = {
                                'departureTime': dep_time,
                                'delay': delay,
                                'destination': destination
                            }
                    
                    if len(trains) >= 10:
                        break
    except asyncio.TimeoutError:
        pass
    
    return trains


async def calculate_travel_times():
    """Calculate travel times between consecutive stations using timetable"""
    
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print("🔌 Connected to WebSocket\n")
        
        print("="*80)
        print("CALCULATING TRAVEL TIMES FROM TIMETABLE")
        print("="*80 + "\n")
        
        # Get trains at first station (Holzkirchen)
        first_uic = STATIONS[0]['uic']
        first_name = STATIONS[0]['name']
        
        print(f"📍 Getting trains at {first_name}...")
        first_trains = await get_train_at_station(ws, first_uic)
        
        if not first_trains:
            print(f"❌ No westbound trains found at {first_name}")
            print("\n⚠️  Cannot auto-calculate. Use manual mode.")
            return None
        
        print(f"   Found {len(first_trains)} westbound trains: {list(first_trains.keys())}")
        
        # Track one train through all stations
        target_train = list(first_trains.keys())[0]
        print(f"\n🚆 Tracking train {target_train} through all stations...\n")
        
        departure_times = {}
        
        for station in STATIONS:
            uic = station['uic']
            name = station['name']
            
            trains = await get_train_at_station(ws, uic, [target_train])
            
            if target_train in trains:
                dep_time = trains[target_train]['departureTime']
                departure_times[name] = dep_time
                
                # Convert to readable time
                dt = datetime.fromtimestamp(dep_time / 1000)
                print(f"   {name:25s} departs at {dt.strftime('%H:%M:%S')} ({dep_time})")
            else:
                print(f"   {name:25s} ❌ Train not found at this station")
        
        print("\n" + "="*80)
        print("CALCULATED TRAVEL TIMES")
        print("="*80 + "\n")
        
        # Calculate differences
        station_names = [s['name'] for s in STATIONS]
        travel_times = {}
        
        for i in range(len(station_names) - 1):
            from_station = station_names[i]
            to_station = station_names[i + 1]
            
            if from_station in departure_times and to_station in departure_times:
                diff_ms = departure_times[to_station] - departure_times[from_station]
                diff_sec = diff_ms / 1000
                travel_times[from_station] = diff_sec
                
                print(f"   {from_station:20s} → {to_station:20s}: {diff_sec:.0f} seconds ({diff_sec/60:.1f} min)")
            else:
                print(f"   {from_station:20s} → {to_station:20s}: ❓ No data")
        
        return travel_times


def manual_entry():
    """Allow manual entry of travel times"""
    print("\n" + "="*80)
    print("MANUAL ENTRY MODE")
    print("="*80)
    print("\nEnter travel time in SECONDS from each station to the next.")
    print("Press Enter to skip (keep existing value).\n")
    
    for i, station in enumerate(STATIONS[:-1]):  # Skip last station
        next_station = STATIONS[i + 1]
        current_val = station.get('travel_time_to_next')
        current_str = f" (current: {current_val}s)" if current_val else ""
        
        prompt = f"{station['name']} → {next_station['name']}{current_str}: "
        user_input = input(prompt).strip()
        
        if user_input:
            try:
                station['travel_time_to_next'] = int(user_input)
            except ValueError:
                print(f"   Invalid input, skipping")
    
    return {s['name']: s['travel_time_to_next'] for s in STATIONS}


def save_travel_times(travel_times):
    """Save travel times to config file"""
    for station in STATIONS:
        name = station['name']
        if name in travel_times and travel_times[name] is not None:
            station['travel_time_to_next'] = int(travel_times[name])
    
    config['stations'] = STATIONS
    config['last_updated'] = datetime.now().isoformat()
    
    with open('travel_times.json', 'w') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Saved to travel_times.json")


async def main():
    print("="*80)
    print("S3 TRAVEL TIME GENERATOR")
    print("="*80)
    print()
    print("This script calculates travel times between S3 stations.")
    print()
    print("Options:")
    print("  1. Auto-calculate from timetable API")
    print("  2. Manual entry")
    print()
    
    choice = input("Choose option (1/2): ").strip()
    
    if choice == '1':
        travel_times = await calculate_travel_times()
        if travel_times:
            save = input("\nSave these values? (y/n): ").strip().lower()
            if save == 'y':
                save_travel_times(travel_times)
    elif choice == '2':
        travel_times = manual_entry()
        save_travel_times(travel_times)
    else:
        print("Invalid choice")


if __name__ == "__main__":
    asyncio.run(main())
