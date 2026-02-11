import asyncio
import json
import websockets

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"

async def find_s3_trains(ws):
    """Find S3 trains and show full properties"""
    await ws.send("BUFFER 100 100")
    await ws.send("BBOX 1230000 6090000 1350000 6180000 5 tenant=sbm")
    
    print("🔍 Looking for S3 trains...\n")
    
    s3_trains = []
    
    try:
        async with asyncio.timeout(10):
            async for msg in ws:
                data = json.loads(msg)
                if data.get('source') == 'buffer':
                    content_items = data.get('content', [])
                    
                    for item in content_items:
                        if item is None:
                            continue
                        item_content = item.get('content', {})
                        props = item_content.get('properties', {})
                        
                        line = props.get('line', {})
                        if isinstance(line, dict) and line.get('name') == 'S3':
                            s3_trains.append((props, item_content))
                            if len(s3_trains) >= 3:  # Get first 3
                                raise StopAsyncIteration
    except (asyncio.TimeoutError, StopAsyncIteration):
        pass
    
    return s3_trains


async def main():
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print("🔌 Connected to WebSocket\n")
        
        trains = await find_s3_trains(ws)
        
        print(f"✅ Found {len(trains)} S3 trains\n")
        print("="*80)
        
        for i, (props, full_content) in enumerate(trains, 1):
            train_number = props.get('train_number')
            state = props.get('state')
            train_id = props.get('train_id')
            line = props.get('line', {})
            
            print(f"\n{'='*80}")
            print(f"TRAIN #{i}: {train_number} (Train ID: {train_id})")
            print(f"State: {state}")
            print('='*80)
            print()
            
            # Show ALL properties
            print("ALL PROPERTIES:")
            for key in sorted(props.keys()):
                value = props[key]
                if isinstance(value, list) and len(str(value)) > 150:
                    print(f"  {key}: [{len(value)} items]")
                else:
                    value_str = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
                    print(f"  {key}: {value_str}")
            
            print()
            print("-"*80)
            print("LOOKING FOR STATION INFO:")
            print("-"*80)
            
            # Check for any station/stop/uic related fields
            station_keys = []
            for key in props.keys():
                key_lower = key.lower()
                if any(word in key_lower for word in ['station', 'stop', 'uic', 'at_', 'next_']):
                    station_keys.append(key)
            
            if station_keys:
                print("✅ Found station-related keys:")
                for key in station_keys:
                    print(f"   {key}: {props[key]}")
            else:
                print("❌ No obvious station-related keys found")
            
            print()


if __name__ == "__main__":
    asyncio.run(main())
