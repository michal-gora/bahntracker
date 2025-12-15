import asyncio
import json
import websockets
from pyproj import Transformer
from datetime import datetime

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"

transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

async def monitor_all_trains():
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print(f"🚂 Monitoring ALL S-Bahn trains with live positions")
        print(f"🕐 Current time: {datetime.now().strftime('%H:%M:%S')}\n")
        print("="*80)
        
        # Subscribe to larger Munich area bounding box
        # Expanded area to catch more trains
        bbox_command = "SUB bbox_1200000_6000000_1400000_6250000"
        await ws.send(bbox_command)
        print(f"📡 Subscribed to Munich region")
        print(f"   Command: {bbox_command}")
        print(f"\nWaiting for live train positions (15 seconds)...\n")
        
        trains_seen = {}
        message_count = 0
        
        try:
            async with asyncio.timeout(15):
                async for msg in ws:
                    if isinstance(msg, str):
                        try:
                            data = json.loads(msg)
                            source = data.get('source', '')
                            
                            if source.startswith('bbox_'):
                                content = data.get('content')
                                if content:
                                    message_count += 1
                                    
                                    props = content.get('properties', {})
                                    train_id = props.get('train_id', 'unknown')
                                    train_number = props.get('train_number', 'N/A')
                                    line_name = props.get('line_name', 'N/A')
                                    
                                    # Get position
                                    geom = content.get('geometry', {})
                                    coords = geom.get('coordinates', [])
                                    
                                    if train_id not in trains_seen and geom.get('type') == 'Point':
                                        trains_seen[train_id] = {
                                            'train_number': train_number,
                                            'line': line_name,
                                            'coords': coords,
                                            'properties': props
                                        }
                                        
                                        # Convert to lat/lon
                                        if len(coords) >= 2:
                                            lon, lat = transformer.transform(coords[0], coords[1])
                                            
                                            print(f"🚆 Train {train_number} ({line_name})")
                                            print(f"   ID: {train_id}")
                                            print(f"   Position: {lat:.6f}°N, {lon:.6f}°E")
                                            print(f"   Map: https://www.google.com/maps?q={lat},{lon}")
                                            
                                            # Show interesting properties
                                            if 'speed' in props:
                                                print(f"   Speed: {props['speed']} km/h")
                                            if 'delay' in props:
                                                print(f"   Delay: {props['delay']} seconds")
                                            if 'state' in props:
                                                print(f"   State: {props['state']}")
                                            
                                            print()
                                    
                                    if message_count % 50 == 0:
                                        print(f"   [{message_count} messages received, {len(trains_seen)} unique trains]")
                                        
                        except json.JSONDecodeError:
                            pass
        except asyncio.TimeoutError:
            pass
        
        print("\n" + "="*80)
        print(f"📊 Summary:")
        print(f"   Total messages: {message_count}")
        print(f"   Unique trains seen: {len(trains_seen)}")
        print("="*80)
        
        if len(trains_seen) == 0:
            print("\n❌ No trains found with live positions!")
            print("   Possible reasons:")
            print("   - Wrong bounding box coordinates")
            print("   - No trains currently transmitting GPS")
            print("   - API requires different subscription format")
        else:
            print(f"\n✅ Successfully found {len(trains_seen)} trains with live GPS positions!")
            print("\n💡 To track a specific train, use its train_id and subscribe to")
            print("   the bounding box or vehicle updates.")

if __name__ == "__main__":
    asyncio.run(monitor_all_trains())
