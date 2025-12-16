import asyncio
import json
import websockets
import traceback
from pyproj import Transformer
from datetime import datetime

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"

# Initialize the coordinate transformer
transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

async def get_station_uic(ws, station_name):
    """Get UIC code for a station using an existing WebSocket connection"""
    res = None
    command = "GET station"
    await ws.send(command)
    print(f"📡 Sent: {command}")
    
    try:
        async with asyncio.timeout(5):
            async for msg in ws:
                data = json.loads(msg)
                source = data.get('source', '')
                
                if source == 'station':
                    content = data.get('content', None)
                    geometry = content.get('geometry', {})
                    properties = content.get('properties', None)
                    name = properties.get('name', None)
                    networkLines = properties.get('networkLines', None)
                    uic = properties.get('uic', None)
                    coordinates = geometry.get('coordinates', [])  # [x, y] in EPSG:3857
                    
                    if station_name in name and networkLines:
                        if coordinates and len(coordinates) >= 2:
                            lon, lat = transformer.transform(coordinates[0], coordinates[1])
                            print(f"✅ Found: {name} → UIC: {uic}")
                            print(f"   📍 Coordinates: {lat:.6f}°N, {lon:.6f}°E")
                        else:
                            print(f"✅ Found: {name} → UIC: {uic}")
                        res = uic
                        break
    except asyncio.TimeoutError:
        print("⏱️  Timeout waiting for station data")
    
    return res

async def get_incoming_trains(ws, uic, max_trains=100):
    """Get incoming trains for a station using an existing WebSocket connection"""
    if not uic:
        print("❌ Could not find station")
        return
    
    # Now get timetable for this station
    command = f"GET timetable_{uic}"
    await ws.send(command)
    print(f"📡 Sent: {command}")
    
    trains = []
    try:
        async with asyncio.timeout(5):
            async for msg in ws:
                data = json.loads(msg)
                source = data.get('source', '')
                
                if source.startswith('timetable_'):
                    content = data.get('content', {})
                    train_number = content.get('train_number')
                    destination = content.get('to', ['Unknown'])[0] if content.get('to') else 'Unknown'
                    time_ms = content.get('time', 0)
                    
                    from datetime import datetime
                    time_str = datetime.fromtimestamp(time_ms / 1000).strftime('%H:%M')
                    
                    trains.append({
                        'number': train_number,
                        'destination': destination,
                        'time': time_str,
                        'timestamp': time_ms
                    })
                    
                    print(f"🚆 Train {train_number} → {destination} @ {time_str}")
                    
                    if len(trains) >= max_trains:  # Get first 5 trains
                        break
    except asyncio.TimeoutError:
        print("⏱️  Timeout waiting for timetable")
    
    # Sort trains by departure time
    trains.sort(key=lambda t: t['timestamp'])
    
    return trains

async def get_sbahn(ws, number):
    buffer_cmd = "BUFFER 100 100"
    await ws.send(buffer_cmd)
    print(f"📡 Sent: {buffer_cmd}")
    await asyncio.sleep(0.1)
    
    bbox_cmd = "BBOX 1269000 6087000 1350000 6200000 5 tenant=sbm"
    await ws.send(bbox_cmd)
    print(f"📡 Sent: {bbox_cmd}")
    await asyncio.sleep(0.1)
    
    trains_found = {}
    message_count = 0
    
    try:
        async for message in ws:
            message_count += 1
            try:
                data = json.loads(message)
                source = data.get("source", "")
                content = data.get("content")
                
                if source == "buffer":
                    for item in content:
                        if item:
                            trajectory = item.get('content')
                            process_trajectory(trajectory, number)
                
                
            except json.JSONDecodeError:
                print("⚠️  Received non-JSON message")
            except Exception as e:
                print(f"❌ Error processing message: {e}")
                
            if message_count >= 1000:
                print(f"="*80)
                break
    except Exception as e:
        print(f"\n❌ Error: {e}")
    print(f"\n📨 Received {message_count} messages")
        
        
def process_trajectory(train_data, number) -> bool:
    """Process individual train data from the buffer response"""
    # print(json.dumps(train_data, indent=2, ensure_ascii=False))
    try:
        if not isinstance(train_data, dict):
            return False
        props = train_data.get('properties', {})
        geom = train_data.get('geometry', {})
        
        train_id = props.get('train_id', 'Unknown')
        train_number = props.get('train_number', 'N/A')
        line = props.get('line')
        line_name = line.get('name', 'N/A') if isinstance(line, dict) else 'N/A'
        # if line:
        #     pass
        # else:
        #     print(f"Line is {line}")
        #     print(json.dumps(props, indent=2, ensure_ascii=False))

        
        state = props.get('state', 'Unknown')
        delay = props.get('delay', 'Unknown')
        raw_coordinates = props.get('raw_coordinates')  # [lon, lat] format
        route_identifier = props.get('route_identifier')  # Contains station UICs
        
        if train_number != number:
            # print("not the right number")
            return False
        
        print(f"\n🚆 Train {train_number} (Line {line_name})")
        print(f"   ID: {train_id}")
        print(f"   State: {state}")
        if delay is not None:
            print(f"   Delay: {delay/1000:.0f}s ({delay/60000:.0f}min)")
        if route_identifier:
            print(f"   📋 Route: {route_identifier}")
        
        # Extract and convert coordinates
        if raw_coordinates and len(raw_coordinates) >= 2:
            # raw_coordinates is already in [lon, lat] format
            lon, lat = raw_coordinates[0], raw_coordinates[1]
            print(f"   📍 Position: {lat:.6f}°N, {lon:.6f}°E")
            print(f"   🗺️  https://www.google.com/maps?q={lat},{lon}")
        else:
            # Fall back to geometry coordinates if raw_coordinates not available
            geom_type = geom.get('type')
            coords = geom.get('coordinates', [])
            
            if geom_type == 'LineString' and coords and len(coords) > 0:
                if len(coords[0]) >= 2:
                    try:
                        start_lon, start_lat = transformer.transform(coords[0][0], coords[0][1])
                        print(f"   📍 Position: {start_lat:.6f}°N, {start_lon:.6f}°E")
                        print(f"   🗺️  https://www.google.com/maps?q={start_lat},{start_lon}")
                    except Exception as e:
                        print(f"   ⚠️  Coordinate error: {e}")
    except Exception as e:
        print(f"   ⚠️  Error processing trajectory: {e}")
        traceback.print_exc()
        return False
    return True

def pick_train_number_from_list(trains, destinations):
    for t in trains:
        destination = t.get('destination')
        if destination and any(dest in destination for dest in destinations):
            # todo check time
            return t.get('number')
    return None

async def keep_alive(ws):
    """Send PING commands periodically to keep the connection alive"""
    while True:
        try:
            await asyncio.sleep(10)  # Send PING every 10 seconds
            await ws.send("PING")
            print("📡 Sent PING")
        except Exception as e:
            print(f"⚠️ Keepalive error: {e}")
            break

async def main():
    """Main function that creates one WebSocket connection and reuses it"""
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print("🔌 Connected to WebSocket\n")
        
        # Start keepalive task in the background
        keepalive_task = asyncio.create_task(keep_alive(ws))
        
        try:
            uic = await get_station_uic(ws, station_name="Fasanenpark")
            trains = await get_incoming_trains(ws, uic)
            
            print(json.dumps(trains, indent=2))
            train_number = pick_train_number_from_list(trains, ["Mammendorf", "Maisach", "Giesing", "Pasing", "Ostbahnhof"])
            print(f"Chosen train number: {train_number}")
            await get_sbahn(ws, train_number)
            
            print("Done")
        finally:
            # Cancel keepalive task when done
            keepalive_task.cancel()
            try:
                await keepalive_task
            except asyncio.CancelledError:
                pass
        
if __name__ == "__main__":
    asyncio.run(main())