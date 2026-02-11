import asyncio
import json
import websockets
import traceback
from pyproj import Transformer
from datetime import datetime

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"

# Initialize the coordinate transformer
transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)


class ModelTrainController:
    """Placeholder for model train WebSocket control.
    The model train receives simple commands over WebSocket:
    - set_speed(speed): 0.0 (stopped) to 1.0 (full speed)
    - stop(): stop the train (BOARDING at station)
    - set_station(name): update station name display
    - set_boarding(active): toggle boarding indicator (e.g. door LEDs)
    """
    
    def set_speed(self, speed: float):
        """Set model train speed. 0.0 = stopped, 1.0 = full speed"""
        # TODO: Send speed command via WebSocket to model train
        pass
    
    def stop(self):
        """Stop the model train at station"""
        # TODO: Send stop command via WebSocket
        pass
    
    def set_station(self, name: str):
        """Update the station name display"""
        # TODO: Send display update via WebSocket
        pass
    
    def set_boarding(self, active: bool):
        """Toggle boarding indicator (e.g. green door LEDs)"""
        # TODO: Send LED command via WebSocket
        pass


class TrainTracker:
    """Tracks a single train's state transitions and segment timing.
    Only reacts to meaningful changes (state transitions, new segments).
    """
    
    def __init__(self, train_number, controller: ModelTrainController = None):
        self.train_number = train_number
        self.controller = controller or ModelTrainController()
        
        # State tracking
        self.state = None           # "DRIVING" or "BOARDING"
        self.segment_entry = None   # ms timestamp: when current segment started
        self.segment_exit = None    # ms timestamp: when current segment ends
        self.station_name = None    # Current/last station name (set during BOARDING)
        self.coordinates = None     # Latest [lon, lat]
        self.delay_ms = None        # Latest delay in ms
        self.line_name = None       # e.g. "S3"
        self.update_count = 0
    
    def update(self, train_data: dict) -> bool:
        """Process a train update. Returns True if this was our train."""
        if not isinstance(train_data, dict):
            return False
        
        props = train_data.get('properties', {})
        train_number = props.get('train_number')
        
        if train_number != self.train_number:
            return False
        
        self.update_count += 1
        
        # Extract data
        new_state = props.get('state', 'Unknown')
        self.delay_ms = props.get('delay')
        self.coordinates = props.get('raw_coordinates')
        time_intervals = props.get('time_intervals', [])
        
        line = props.get('line')
        if isinstance(line, dict):
            self.line_name = line.get('name', 'N/A')
        
        # Extract segment timing
        new_entry = None
        new_exit = None
        if time_intervals and len(time_intervals) >= 2:
            new_entry = time_intervals[0][0]
            new_exit = time_intervals[1][0]
        
        # Detect state change
        state_changed = new_state != self.state
        segment_changed = new_entry != self.segment_entry
        
        if state_changed:
            self._on_state_change(new_state, new_entry, new_exit)
        elif segment_changed and new_entry and new_exit:
            self._on_new_segment(new_entry, new_exit)
        
        # Update stored state
        self.state = new_state
        if new_entry:
            self.segment_entry = new_entry
        if new_exit:
            self.segment_exit = new_exit
        
        return True
    
    def _on_state_change(self, new_state, entry_time, exit_time):
        """Called when train transitions between DRIVING and BOARDING"""
        duration = (exit_time - entry_time) / 1000 if entry_time and exit_time else 0
        now = datetime.now().strftime('%H:%M:%S')
        segment_info = ""
        if entry_time and exit_time:
            entry_str = datetime.fromtimestamp(entry_time / 1000).strftime('%H:%M:%S')
            exit_str = datetime.fromtimestamp(exit_time / 1000).strftime('%H:%M:%S')
            segment_info = f"\n   ⏱️  Segment: {entry_str} → {exit_str} ({duration:.0f}s)"
        
        if new_state == "BOARDING":
            pos = self._format_coords()
            delay_str = f"\n   ⏳ Delay: {self.delay_ms/1000:.0f}s" if self.delay_ms else "\n   ✅ On time"
            print(f"\n[{now}] 🚉 [{self.line_name}] BOARDING{pos}{segment_info}{delay_str}")
            
            # Model train: stop and show boarding
            self.controller.stop()
            self.controller.set_boarding(True)
        
        elif new_state == "DRIVING":
            pos = self._format_coords()
            delay_str = f"\n   ⏳ Delay: {self.delay_ms/1000:.0f}s" if self.delay_ms else "\n   ✅ On time"
            print(f"\n[{now}] 🚆 [{self.line_name}] DRIVING{pos}{segment_info}{delay_str}")
            
            # Model train: calculate speed and go
            self.controller.set_boarding(False)
            if duration > 0:
                speed = self._calculate_model_speed(duration)
                self.controller.set_speed(speed)
                print(f"   🎮 Model speed: {speed:.2f}")
        
        else:
            print(f"\n[{now}] ❓ [{self.line_name}] Unknown state: {new_state}")
    
    def _on_new_segment(self, entry_time, exit_time):
        """Called when a new segment starts within the same state (e.g. still DRIVING)"""
        duration = (exit_time - entry_time) / 1000
        # Silently update - no need to spam, same state continues
    
    def _calculate_model_speed(self, segment_duration_seconds: float) -> float:
        """Calculate model train speed based on real segment duration.
        Returns 0.0-1.0 speed value.
        
        TODO: Calibrate these values with actual model train:
        - TRACK_LOOP_SECONDS: how long one loop takes at full speed
        - MIN_SPEED / MAX_SPEED: hardware limits
        """
        TRACK_LOOP_SECONDS_AT_FULL = 10.0  # Calibrate this!
        MIN_SPEED = 0.1
        MAX_SPEED = 1.0
        
        speed = TRACK_LOOP_SECONDS_AT_FULL / segment_duration_seconds
        return max(MIN_SPEED, min(MAX_SPEED, speed))
    
    def _format_coords(self) -> str:
        if self.coordinates and len(self.coordinates) >= 2:
            lon, lat = self.coordinates
            return f" @ {lat:.4f}°N, {lon:.4f}°E\n   🗺️  https://www.google.com/maps?q={lat},{lon}"
        return ""


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

async def track_train(ws, number):
    """Track a specific train using TrainTracker for clean state transitions"""
    tracker = TrainTracker(number)
    
    buffer_cmd = "BUFFER 100 100"
    await ws.send(buffer_cmd)
    await asyncio.sleep(0.1)
    
    bbox_cmd = "BBOX 1269000 6087000 1350000 6200000 5 tenant=sbm"
    await ws.send(bbox_cmd)
    print(f"📡 Tracking train {number}...")
    await asyncio.sleep(0.1)
    
    try:
        async for message in ws:
            try:
                data = json.loads(message)
                source = data.get("source", "")
                content = data.get("content")
                
                if source == "buffer":
                    for item in content:
                        if item:
                            trajectory = item.get('content')
                            tracker.update(trajectory)
                
            except json.JSONDecodeError:
                pass
            except Exception as e:
                print(f"❌ Error: {e}")
        
        # If we reach here, the async iterator ended (connection closed cleanly)
        print(f"\n⚠️  WebSocket stream ended (connection closed)")
    except Exception as e:
        print(f"\n❌ Connection error: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n📊 Tracked {tracker.update_count} updates")
    return tracker

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
            await asyncio.sleep(7)  # Send PING every 10 seconds
            await ws.send("PING")
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
            print(f"\n🎯 Tracking train {train_number}\n")
            await track_train(ws, train_number)
            
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