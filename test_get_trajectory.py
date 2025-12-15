import asyncio
import json
import websockets
from pyproj import Transformer
from datetime import datetime

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"

transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

async def test_get_trajectory():
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print(f"🧪 Testing: GET trajectory (without train ID)")
        print(f"🕐 Time: {datetime.now().strftime('%H:%M:%S')}\n")
        print("="*80)
        
        # Try different commands
        commands_to_try = [
            "GET vehicles",
            "SUB vehicles", 
            "GET trains",
            "SUB trains",
        ]
        
        for command in commands_to_try:
            print(f"\n{'='*80}")
            print(f"🧪 Testing: {command}")
            print(f"{'='*80}")
            await ws.send(command)
            print(f"Sent: {command}\n")
        
        message_count = 0
        trains_found = {}
        
        try:
            async with asyncio.timeout(10):
                async for msg in ws:
                    if isinstance(msg, str):
                        try:
                            data = json.loads(msg)
                            source = data.get('source', '')
                            
                            print(f"Message {message_count + 1}: source = '{source}'")
                            
                            if source in ['trajectory', 'vehicles', 'trains']:
                                content = data.get('content')
                                
                                if content is not None:
                                    print(f"   ✅ Got content!")
                                    
                                    # Check if it's an array of trains
                                    if isinstance(content, list):
                                        print(f"   📋 Content is a list with {len(content)} items")
                                        for idx, item in enumerate(content[:3]):  # Show first 3
                                            print(f"\n   Item {idx + 1}:")
                                            print(f"      Keys: {list(item.keys()) if isinstance(item, dict) else 'not a dict'}")
                                    elif isinstance(content, dict):
                                        print(f"   📄 Content is a dict")
                                        print(f"      Keys: {list(content.keys())}")
                                        
                                        # Check for features (GeoJSON)
                                        if 'features' in content:
                                            features = content['features']
                                            print(f"      Features: {len(features)} items")
                                            
                                            for idx, feature in enumerate(features[:5]):  # Show first 5 trains
                                                props = feature.get('properties', {})
                                                geom = feature.get('geometry', {})
                                                
                                                train_id = props.get('train_id', 'unknown')
                                                train_number = props.get('train_number', 'N/A')
                                                line_name = props.get('line_name', 'N/A')
                                                
                                                if train_id not in trains_found:
                                                    trains_found[train_id] = True
                                                    
                                                    print(f"\n      🚆 Train {idx + 1}: {train_number} ({line_name})")
                                                    print(f"         ID: {train_id}")
                                                    
                                                    # Get position
                                                    if geom.get('type') == 'Point':
                                                        coords = geom.get('coordinates', [])
                                                        if len(coords) >= 2:
                                                            lon, lat = transformer.transform(coords[0], coords[1])
                                                            print(f"         📍 Position: {lat:.6f}°N, {lon:.6f}°E")
                                                            print(f"         🗺️  https://www.google.com/maps?q={lat},{lon}")
                                                        
                                                        # Show properties
                                                        interesting_props = ['speed', 'delay', 'state', 'destination']
                                                        for prop_key in interesting_props:
                                                            if prop_key in props:
                                                                print(f"         {prop_key}: {props[prop_key]}")
                                    
                                    # Show full structure of first message
                                    if message_count == 0:
                                        print(f"\n   📄 Full structure (first 1000 chars):")
                                        print(f"      {json.dumps(data, indent=6)[:1000]}...")
                                    
                                    return  # Got data, exit
                                else:
                                    print(f"   ❌ Content is None")
                                    return
                            
                            message_count += 1
                            
                            if message_count > 20:
                                print(f"\n⏹️  Stopping after 20 messages")
                                break
                                
                        except json.JSONDecodeError:
                            print(f"   (Non-JSON message)")
        except asyncio.TimeoutError:
            print(f"\n⏱️  Timeout after {message_count} messages")
        
        print("\n" + "="*80)
        print(f"📊 Result:")
        print(f"   Messages received: {message_count}")
        print(f"   Trains found: {len(trains_found)}")
        print("="*80)

if __name__ == "__main__":
    asyncio.run(test_get_trajectory())
