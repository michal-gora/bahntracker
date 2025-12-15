import asyncio
import json
import websockets
from pyproj import Transformer
from datetime import datetime

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"

transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

async def test_buffer():
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print(f"🧪 Testing BUFFER command")
        print(f"🕐 Time: {datetime.now().strftime('%H:%M:%S')}\n")
        print("="*80)
        
        # Try BUFFER command with bounding box (Munich area)
        # Format might be: BUFFER minx miny maxx maxy
        commands = [
            "BUFFER 1269000 6087000 1350000 6200000",  # Munich bounding box
            "BUFFER 100 100",
            "SET buffer 1269000 6087000 1350000 6200000",
        ]
        
        # After setting buffer, try to get vehicles
        print("Step 1: Setting buffer...")
        await ws.send(commands[0])
        await asyncio.sleep(1)
        
        print("Step 2: Subscribing to vehicles...\n")
        await ws.send("SUB vehicles")
        
        for command in commands:
            print(f"\n📡 Trying: {command}")
            await ws.send(command)
            
            try:
                async with asyncio.timeout(3):
                    message_count = 0
                    async for msg in ws:
                        if isinstance(msg, str):
                            try:
                                data = json.loads(msg)
                                source = data.get('source', '')
                                
                                if source != 'websocket':
                                    message_count += 1
                                    print(f"   Message {message_count}: source='{source}'")
                                    
                                    content = data.get('content')
                                    if content is not None:
                                        print(f"   ✅ Got content!")
                                        
                                        if isinstance(content, dict):
                                            if 'features' in content:
                                                features = content.get('features', [])
                                                print(f"   📋 Features count: {len(features)}")
                                                
                                                # Show first train
                                                if len(features) > 0:
                                                    feature = features[0]
                                                    props = feature.get('properties', {})
                                                    geom = feature.get('geometry', {})
                                                    
                                                    print(f"\n   🚆 First train:")
                                                    print(f"      ID: {props.get('train_id', 'N/A')}")
                                                    print(f"      Number: {props.get('train_number', 'N/A')}")
                                                    print(f"      Line: {props.get('line_name', 'N/A')}")
                                                    
                                                    if geom.get('type') == 'Point':
                                                        coords = geom.get('coordinates', [])
                                                        if len(coords) >= 2:
                                                            lon, lat = transformer.transform(coords[0], coords[1])
                                                            print(f"      Position: {lat:.6f}°N, {lon:.6f}°E")
                                                            print(f"      Map: https://www.google.com/maps?q={lat},{lon}")
                                                    
                                                    print(f"\n   📊 Available properties:")
                                                    for key in props.keys():
                                                        print(f"      - {key}: {props[key]}")
                                                
                                                if len(features) > 1:
                                                    print(f"\n   ... and {len(features) - 1} more trains")
                                                
                                                break
                                            else:
                                                print(f"   Keys: {list(content.keys())}")
                                        elif isinstance(content, list):
                                            print(f"   📋 List with {len(content)} items")
                                    else:
                                        print(f"   ❌ Content is None")
                                    
                                    if message_count >= 3:
                                        break
                                        
                            except json.JSONDecodeError:
                                pass
            except asyncio.TimeoutError:
                print(f"   ⏱️  Timeout (no response)")

if __name__ == "__main__":
    asyncio.run(test_buffer())
