import asyncio
import json
import websockets
from pyproj import Transformer
from datetime import datetime

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"

transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

async def test_bbox_with_params():
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print(f"🧪 Testing BBOX with tenant and channel_prefix parameters")
        print(f"🕐 Time: {datetime.now().strftime('%H:%M:%S')}\n")
        print("="*80)
        
        # Step 1: Set buffer
        buffer_cmd = "BUFFER 100 100"
        await ws.send(buffer_cmd)
        print(f"📡 Sent: {buffer_cmd}")
        await asyncio.sleep(0.1)
        
        # Step 2: BBOX with tenant and channel_prefix (use exact coordinates from website)
        bbox_cmd = "BBOX 799506 -6924 4013052 3452222 5 tenant=sbm channel_prefix=schematic"
        await ws.send(bbox_cmd)
        print(f"📡 Sent: {bbox_cmd}")
        print(f"\nWaiting for responses...\n")
        
        trains_found = {}
        message_count = 0
        
        try:
            async with asyncio.timeout(10):
                async for msg in ws:
                    if isinstance(msg, str):
                        try:
                            data = json.loads(msg)
                            source = data.get('source', '')
                            
                            message_count += 1
                            
                            if source == 'websocket':
                                continue
                            
                            print(f"Message {message_count}: source='{source}'")
                            
                            content = data.get('content')
                            if content is not None:
                                # Check if it has train data
                                if isinstance(content, dict):
                                    props = content.get('properties', {})
                                    geom = content.get('geometry', {})
                                    
                                    train_id = props.get('train_id')
                                    if train_id and train_id not in trains_found:
                                        trains_found[train_id] = True
                                        
                                        print(f"   ✅ FOUND TRAIN!")
                                        print(f"   🚆 Train: {props.get('train_number', 'N/A')} ({props.get('line_name', 'N/A')})")
                                        print(f"   ID: {train_id}")
                                        
                                        if geom.get('type') == 'Point':
                                            coords = geom.get('coordinates', [])
                                            if len(coords) >= 2:
                                                lon, lat = transformer.transform(coords[0], coords[1])
                                                print(f"   📍 Position: {lat:.6f}°N, {lon:.6f}°E")
                                                print(f"   🗺️  https://www.google.com/maps?q={lat},{lon}")
                                        
                                        # Show interesting properties
                                        interesting_keys = ['speed', 'delay', 'state', 'destination']
                                        for key in interesting_keys:
                                            if key in props:
                                                print(f"   {key}: {props[key]}")
                                        print()
                                    
                                    elif not train_id:
                                        # Not a train, show what it is
                                        print(f"   Content type: {content.get('type', 'unknown')}")
                                
                                elif isinstance(content, list):
                                    # This is a list of messages
                                    for item in content:
                                        if isinstance(item, dict) and 'content' in item:
                                            item_content = item['content']
                                            if isinstance(item_content, dict):
                                                props = item_content.get('properties', {})
                                                geom = item_content.get('geometry', {})
                                                
                                                train_id = props.get('train_id')
                                                if train_id and train_id not in trains_found:
                                                    trains_found[train_id] = True
                                                    
                                                    print(f"\n   🚆 Train: {props.get('train_number', 'N/A')} ({props.get('line_name', 'N/A')})")
                                                    print(f"      ID: {train_id}")
                                                    
                                                    # Check geometry type and coordinates
                                                    if geom:
                                                        geom_type = geom.get('type', 'unknown')
                                                        coords = geom.get('coordinates', [])
                                                        
                                                        if geom_type == 'Point' and len(coords) >= 2:
                                                            try:
                                                                lon, lat = transformer.transform(coords[0], coords[1])
                                                                print(f"      📍 Position: {lat:.6f}°N, {lon:.6f}°E")
                                                                print(f"      🗺️  https://www.google.com/maps?q={lat},{lon}")
                                                            except Exception as e:
                                                                print(f"      📍 Raw coords: {coords}")
                                                        elif coords:
                                                            print(f"      Geometry: {geom_type}, coords: {coords[:2] if len(coords) > 2 else coords}")
                                                    
                                                    # Show interesting properties
                                                    interesting_keys = ['speed', 'delay', 'state', 'line_name']
                                                    for key in interesting_keys:
                                                        if key in props:
                                                            value = props[key]
                                                            if key == 'delay' and value is not None:
                                                                print(f"      {key}: {value}ms ({value/1000:.0f}s = {value/60000:.0f}min)")
                                                            else:
                                                                print(f"      {key}: {value}")
                            else:
                                print(f"   Content: None")
                            
                            if message_count > 50:
                                print("\n⏹️  Stopping after 50 messages")
                                break
                                
                        except json.JSONDecodeError as e:
                            print(f"   JSON decode error: {e}")
        except asyncio.TimeoutError:
            print(f"\n⏱️  Timeout")
        
        print("\n" + "="*80)
        print(f"📊 Summary:")
        print(f"   Messages received: {message_count}")
        print(f"   Trains found: {len(trains_found)}")
        print("="*80)
        
        if len(trains_found) > 0:
            print(f"\n✅ SUCCESS! Found {len(trains_found)} trains with live positions!")
        else:
            print(f"\n❌ No trains found")

if __name__ == "__main__":
    asyncio.run(test_bbox_with_params())
