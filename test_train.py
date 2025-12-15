import asyncio
import json
import websockets

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"
TRAIN_ID = "sbm_140330651162704"  # Train 6398 to Mammendorf

async def test_trajectory():
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print(f"🚂 Connected to geops.io")
        print(f"📍 Testing trajectory for train: {TRAIN_ID}\n")
        
        # Get full trajectory and analyze for position data
        command = f"GET full_trajectory_{TRAIN_ID}"
        await ws.send(command)
        print(f"Sent: {command}\n")
        
        # Wait for response
        try:
            async with asyncio.timeout(5):
                async for msg in ws:
                    if isinstance(msg, str):
                        try:
                            data = json.loads(msg)
                            source = data.get('source', '')
                            
                            print(f"Received from: {source}")
                            
                            if source.startswith('full_trajectory_'):
                                content = data.get('content')
                                
                                if content is not None:
                                    print("\n" + "="*80)
                                    print("📊 ANALYZING TRAJECTORY DATA FOR CURRENT POSITION")
                                    print("="*80)
                                    
                                    # Check all keys in content
                                    print(f"\n🔑 Top-level keys in content: {list(content.keys())}")
                                    
                                    # Check features
                                    if 'features' in content and len(content['features']) > 0:
                                        for idx, feature in enumerate(content['features']):
                                            print(f"\n📍 Feature {idx + 1}:")
                                            print(f"   Type: {feature.get('type')}")
                                            
                                            geom = feature.get('geometry', {})
                                            print(f"   Geometry type: {geom.get('type')}")
                                            print(f"   Geometry keys: {list(geom.keys())}")
                                            
                                            coords = geom.get('coordinates', [])
                                            if isinstance(coords, list) and len(coords) > 0:
                                                # Check if it's LineString (route) or Point (position)
                                                if geom.get('type') == 'LineString':
                                                    print(f"   📏 LineString with {len(coords)} points (ROUTE PATH)")
                                                    print(f"      First point: {coords[0]}")
                                                    print(f"      Last point: {coords[-1]}")
                                                elif geom.get('type') == 'Point':
                                                    print(f"   📍 Point coordinates (CURRENT POSITION): {coords}")
                                                    from pyproj import Transformer
                                                    transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
                                                    lon, lat = transformer.transform(coords[0], coords[1])
                                                    print(f"      → {lat:.6f}°N, {lon:.6f}°E")
                                                    print(f"      → https://www.google.com/maps?q={lat},{lon}")
                                            
                                            props = feature.get('properties', {})
                                            print(f"   Properties: {list(props.keys())}")
                                            if 'state' in props:
                                                print(f"      state: {props['state']}")
                                            if 'speed' in props:
                                                print(f"      speed: {props['speed']} km/h")
                                            if 'delay' in props:
                                                print(f"      delay: {props['delay']} seconds")
                                    
                                    # Check properties at root level
                                    if 'properties' in content:
                                        print(f"\n🔧 Root properties: {list(content['properties'].keys())}")
                                    
                                    print("\n" + "="*80)
                                    print("💡 CONCLUSION:")
                                    print("="*80)
                                    print("The full_trajectory gives us the PLANNED ROUTE (LineString).")
                                    print("To get CURRENT POSITION, we need a different approach - likely")
                                    print("the train's real-time position comes from a different API call or")
                                    print("we need to track it using vehicle tracking endpoints.")
                                    
                                    return
                                else:
                                    print("   Content: None")
                                    return
                                    
                        except json.JSONDecodeError:
                            pass
                            
        except asyncio.TimeoutError:
            print("\n⏱️  Timeout - no response received")

if __name__ == "__main__":
    asyncio.run(test_trajectory())
