import asyncio
import json
import websockets
from datetime import datetime

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"

async def get_station_uic(ws, station_name):
    """Get UIC code for a station by name"""
    await ws.send("GET station")
    
    async with asyncio.timeout(5):
        async for msg in ws:
            data = json.loads(msg)
            if data.get('source') == 'station':
                content = data.get('content', {})
                properties = content.get('properties', {})
                if properties.get('name') == station_name:
                    return properties.get('uic')
    return None


async def get_incoming_trains(ws, uic, max_trains=5):
    """Get incoming trains at station"""
    await ws.send(f"GET timetable_{uic}")
    
    trains = []
    async with asyncio.timeout(5):
        async for msg in ws:
            data = json.loads(msg)
            if data.get('source', '').startswith('timetable_'):
                content = data.get('content', {})
                trains.append({
                    'number': content.get('train_number'),
                    'destination': content.get('to', ['Unknown'])[0],
                    'time': content.get('departureTime') or content.get('time'),
                    'next_stoppoints': content.get('next_stoppoints'),  # This is what we're interested in!
                    'at_stoppoint': content.get('at_stoppoint'),
                    'train_id': content.get('train_id')
                })
                if len(trains) >= max_trains:
                    break
    
    return sorted(trains, key=lambda x: x['time'] if x['time'] else 0)


async def track_live_train(ws, train_number):
    """Track a live train and get ALL its properties"""
    # Send BBOX command for Munich area
    await ws.send("BUFFER 100 100")
    await ws.send("BBOX 11.4 48.0 11.8 48.3 5 tenant=sbm")
    
    print(f"🔍 Looking for train {train_number}...\n")
    
    try:
        async with asyncio.timeout(10):
            async for msg in ws:
                data = json.loads(msg)
                if data.get('source') == 'buffer':
                    content_items = data.get('content', [])
                    for item in content_items:
                        item_content = item.get('content', {})
                        props = item_content.get('properties', {})
                        
                        if props.get('train_number') == train_number:
                            return item_content
    except asyncio.TimeoutError:
        return None
    return None


async def get_full_trajectory(ws, train_id):
    """Get full trajectory with ALL properties"""
    await ws.send(f"GET full_trajectory_{train_id}")
    
    async with asyncio.timeout(5):
        async for msg in ws:
            data = json.loads(msg)
            if data.get('source', '').startswith('full_trajectory_'):
                return data.get('content', {})
    return None


async def main():
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print("🔌 Connected to WebSocket\n")
        
        # Get Fasanenpark UIC
        uic = await get_station_uic(ws, "Fasanenpark")
        print(f"📍 Fasanenpark UIC: {uic}\n")
        
        # Get incoming trains
        print("="*80)
        print("STEP 1: TIMETABLE - Looking for trains with next_stoppoints")
        print("="*80 + "\n")
        
        trains = await get_incoming_trains(ws, uic, max_trains=10)
        
        target_train = None
        for train in trains:
            if train['next_stoppoints']:
                print(f"✅ Train {train['number']} to {train['destination']}")
                print(f"   next_stoppoints: {train['next_stoppoints']}")
                print(f"   at_stoppoint: {train['at_stoppoint']}")
                print(f"   train_id: {train['train_id']}")
                print()
                if not target_train:
                    target_train = train
            else:
                print(f"❌ Train {train['number']} to {train['destination']} - NO next_stoppoints")
        
        if not target_train:
            print("\n⚠️  No trains with next_stoppoints found!")
            return
        
        print(f"\n🎯 Will try multiple trains with next_stoppoints\n")
        
        # Try multiple trains until we find an active one
        live_data = None
        for train in trains:
            if train['next_stoppoints']:
                print("="*80)
                print(f"STEP 2: LIVE TRAIN DATA - Trying train {train['number']}")
                print("="*80 + "\n")
                
                live_data = await track_live_train(ws, train['number'])
                if live_data:
                    target_train = train
                    print(f"✅ Found active train {train['number']}!\n")
                    break
                else:
                    print(f"❌ Train {train['number']} not active yet\n")
        
        if live_data:
            print("📦 FULL LIVE TRAIN DATA:")
            print(json.dumps(live_data, indent=2, ensure_ascii=False))
            print("\n")
            
            props = live_data.get('properties', {})
            print("🔍 KEY PROPERTIES:")
            print(f"   train_number: {props.get('train_number')}")
            print(f"   train_id: {props.get('train_id')}")
            print(f"   state: {props.get('state')}")
            print(f"   route_identifier: {props.get('route_identifier')}")
            print(f"   next_stoppoints: {props.get('next_stoppoints', 'NOT PRESENT')}")
            print(f"   at_stoppoint: {props.get('at_stoppoint', 'NOT PRESENT')}")
            print()
        else:
            print("❌ Train not found in live data (might not be active yet)\n")
            return
        
        # Get full trajectory
        print("="*80)
        print(f"STEP 3: FULL TRAJECTORY - All properties")
        print("="*80 + "\n")
        
        trajectory = await get_full_trajectory(ws, props.get('train_id'))
        
        if trajectory:
            # Don't print the massive coordinates array, just the properties
            features = trajectory.get('features', [])
            if features:
                feature = features[0]
                traj_props = feature.get('properties', {})
                
                print("🗺️  TRAJECTORY PROPERTIES:")
                print(json.dumps(traj_props, indent=2, ensure_ascii=False))
                print()
                
                coords = feature.get('geometry', {}).get('coordinates', [])
                print(f"📍 Trajectory has {len(coords)} coordinate points")
                print()
        
        # Analyze route_identifier
        print("="*80)
        print("STEP 4: ROUTE IDENTIFIER ANALYSIS")
        print("="*80 + "\n")
        
        route_id = props.get('route_identifier', '')
        if route_id:
            parts = route_id.split('-')
            print(f"Route Identifier: {route_id}")
            print(f"Split by '-': {parts}")
            print(f"Number of parts: {len(parts)}")
            
            if len(parts) >= 3:
                print(f"\nPossible interpretation:")
                print(f"  Part 0 ({parts[0]}): Train number?")
                print(f"  Part 1 ({parts[1]}): Start station UIC?")
                print(f"  Part 2 ({parts[2]}): End station UIC?")
                if len(parts) > 3:
                    print(f"  Part 3 ({parts[3]}): Departure time?")
        
        print("\n" + "="*80)
        print("SUMMARY")
        print("="*80 + "\n")
        
        print("Key Findings:")
        print(f"1. Timetable query: ✅ Contains next_stoppoints array")
        print(f"2. Live train data: {'✅' if props.get('next_stoppoints') else '❌'} {'Contains' if props.get('next_stoppoints') else 'Does NOT contain'} next_stoppoints")
        print(f"3. Full trajectory: {'✅' if trajectory and traj_props.get('next_stoppoints') else '❌'} {'Contains' if trajectory and traj_props.get('next_stoppoints') else 'Does NOT contain'} next_stoppoints")
        print(f"4. Route identifier: {'✅ Available' if route_id else '❌ Not available'} - {route_id if route_id else 'N/A'}")


if __name__ == "__main__":
    asyncio.run(main())
