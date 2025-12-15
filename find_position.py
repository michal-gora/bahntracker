import asyncio
import json
import websockets
from pyproj import Transformer

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"
TRAIN_ID = "sbm_140330651162704"  # Train 6398 to Mammendorf

transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

async def get_live_position():
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print(f"🚂 Looking for LIVE POSITION of train {TRAIN_ID}\n")
        print("="*80)
        
        # Try different commands to find real-time position
        commands = [
            f"GET vehicles_{TRAIN_ID}",
            f"SUB vehicles",
            f"GET position_{TRAIN_ID}",
        ]
        
        for command in commands:
            print(f"\n🔍 Trying: {command}")
            await ws.send(command)
            
            try:
                async with asyncio.timeout(3):
                    async for msg in ws:
                        if isinstance(msg, str):
                            try:
                                data = json.loads(msg)
                                source = data.get('source', '')
                                
                                if source != 'websocket':
                                    print(f"   Response from: {source}")
                                    content = data.get('content')
                                    
                                    if content is not None:
                                        print(f"   ✅ Got data!")
                                        
                                        # Try to find position coordinates
                                        if 'geometry' in content:
                                            geom = content.get('geometry', {})
                                            if geom.get('type') == 'Point':
                                                coords = geom.get('coordinates', [])
                                                print(f"\n   📍 FOUND POSITION: {coords}")
                                                lon, lat = transformer.transform(coords[0], coords[1])
                                                print(f"      {lat:.6f}°N, {lon:.6f}°E")
                                                print(f"      https://www.google.com/maps?q={lat},{lon}")
                                        
                                        print(f"\n   Data structure:")
                                        print(f"      {json.dumps(data, indent=6)[:500]}...")
                                        break
                                    else:
                                        print(f"   ❌ Content: None")
                                        break
                                        
                            except json.JSONDecodeError:
                                pass
            except asyncio.TimeoutError:
                print(f"   ⏱️  Timeout")
        
        print("\n" + "="*80)
        print("💡 Alternative approach: Subscribe to ALL vehicles on the map")
        print("="*80)
        print("\nTrying: SUB bbox (bounding box subscription)")
        
        # Subscribe to a bounding box around Munich
        # Format: SUB bbox_min_x_min_y_max_x_max_y
        # Munich area roughly: 11.4-11.7 E, 47.9-48.2 N
        # In EPSG:3857: approximately 1269000-1302000, 6087000-6142000
        bbox_command = "SUB bbox_1269000_6087000_1350000_6200000"
        await ws.send(bbox_command)
        print(f"Sent: {bbox_command}")
        print("Listening for vehicle updates in Munich area (10 seconds)...\n")
        
        vehicle_count = 0
        found_our_train = False
        
        try:
            async with asyncio.timeout(10):
                async for msg in ws:
                    if isinstance(msg, str):
                        try:
                            data = json.loads(msg)
                            source = data.get('source', '')
                            
                            if source.startswith('bbox_'):
                                content = data.get('content')
                                if content:
                                    # Check if this is our train
                                    train_id = content.get('properties', {}).get('train_id')
                                    
                                    vehicle_count += 1
                                    
                                    if train_id == TRAIN_ID:
                                        found_our_train = True
                                        print(f"\n🎯 FOUND OUR TRAIN! {TRAIN_ID}")
                                        print("="*80)
                                        
                                        geom = content.get('geometry', {})
                                        if geom.get('type') == 'Point':
                                            coords = geom.get('coordinates', [])
                                            lon, lat = transformer.transform(coords[0], coords[1])
                                            print(f"📍 Current Position: {lat:.6f}°N, {lon:.6f}°E")
                                            print(f"🗺️  Google Maps: https://www.google.com/maps?q={lat},{lon}")
                                        
                                        props = content.get('properties', {})
                                        print(f"\n📊 Properties:")
                                        for key, value in props.items():
                                            print(f"   {key}: {value}")
                                        
                                        return
                                    
                                    if vehicle_count % 10 == 0:
                                        print(f"   Received {vehicle_count} vehicles...")
                                        
                        except json.JSONDecodeError:
                            pass
        except asyncio.TimeoutError:
            if found_our_train:
                print(f"\n✅ Found train!")
            else:
                print(f"\n⏱️  Timeout after receiving {vehicle_count} vehicles")
                print(f"   Our train ({TRAIN_ID}) was not in the bounding box")
                print(f"   (It might have finished its journey or left the monitored area)")

if __name__ == "__main__":
    asyncio.run(get_live_position())
