import asyncio
import json
import os
import signal
from datetime import datetime, timezone

import websockets

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"
FASANENPARK_UIC = "8001963"


def format_departure_time(timestamp_ms: int) -> str:
    """Convert Unix timestamp (milliseconds) to human-readable time."""
    dt = datetime.fromtimestamp(timestamp_ms / 1000)
    return dt.strftime('%H:%M')


def parse_departure(data: dict) -> dict:
    """Extract relevant departure information from geops API response."""
    return {
        'train_number': data.get('train_number', 'N/A'),
        'destination': data.get('to', ['Unknown'])[0] if data.get('to') else 'Unknown',
        'scheduled_time': format_departure_time(data.get('ris_aimed_time', 0)),
        'estimated_time': format_departure_time(data.get('ris_estimated_time') or data.get('time', 0)),
        'delay_seconds': ((data.get('ris_estimated_time') or data.get('time', 0)) - data.get('ris_aimed_time', 0)) // 1000 if data.get('ris_estimated_time') else 0,
        'has_realtime': data.get('has_fzo', False),
    }


async def get_departures(url: str, station_uic: str, max_departures: int = 10):
    """Fetch real-time departures from geops API.
    
    Args:
        url: WebSocket URL
        station_uic: Station UIC code (e.g., '8001963' for Fasanenpark)
        max_departures: Maximum number of departures to display
    """
    departures = []
    
    async with websockets.connect(url, max_size=10 * 1024 * 1024) as ws:
        print(f"\n🚂 Connecting to geops real-time API...")
        
        # Request timetable for the station
        command = f"GET timetable_{station_uic}"
        await ws.send(command)
        print(f"📡 Requesting departures for station UIC {station_uic}\n")

        try:
            async for msg in ws:
                if isinstance(msg, str):
                    try:
                        data = json.loads(msg)
                        
                        # Check if this is a timetable response
                        if data.get('source', '').startswith('timetable_'):
                            content = data.get('content', {})
                            departure = parse_departure(content)
                            departures.append(departure)
                            
                            # Display the departure
                            delay_info = ""
                            if departure['delay_seconds'] > 0:
                                delay_info = f" ⚠️  +{departure['delay_seconds'] // 60} min"
                            elif departure['delay_seconds'] < 0:
                                delay_info = f" ✓ {departure['delay_seconds'] // 60} min early"
                            
                            realtime_indicator = "🟢" if departure['has_realtime'] else "⚪"
                            
                            print(f"{realtime_indicator} Train {departure['train_number']:5} → {departure['destination']:20} | "
                                  f"Scheduled: {departure['scheduled_time']} | "
                                  f"Estimated: {departure['estimated_time']}{delay_info}")
                            
                            # Stop after collecting enough departures
                            if len(departures) >= max_departures:
                                print(f"\n✅ Displayed {max_departures} departures")
                                break
                                
                    except json.JSONDecodeError:
                        pass  # Skip non-JSON messages
                        
        except websockets.ConnectionClosedOK:
            print("\n✅ Connection closed normally")
        except websockets.ConnectionClosedError as e:
            print(f"\n❌ Connection error: {e}")
    
    return departures


async def track_next_train(url: str, station_uic: str):
    """Track the next incoming S-Bahn to a station using trajectory data.
    
    Demonstrates the two-step process:
    1. Get next departure from timetable (to get train_id)
    2. Request trajectory for that specific train_id
    """
    
    async with websockets.connect(url, max_size=10 * 1024 * 1024) as ws:
        print(f"\n🚂 Connecting to geops real-time API...")
        
        # Step 1: Get timetable and find trains with real-time tracking
        print("\n📋 Step 1: Getting timetable to find trains with GPS tracking...")
        timetable_command = f"GET timetable_{station_uic}"
        await ws.send(timetable_command)
        
        trains_with_tracking = []
        message_count = 0
        
        async for msg in ws:
            if isinstance(msg, str):
                try:
                    data = json.loads(msg)
                    
                    if data.get('source', '').startswith('timetable_'):
                        content = data.get('content', {})
                        if content.get('has_fzo'):  # Has real-time tracking
                            train_info = {
                                'id': content.get('train_id'),
                                'number': content.get('train_number'),
                                'destination': content.get('to', ['Unknown'])[0] if content.get('to') else 'Unknown',
                                'departure_time': format_departure_time(content.get('time'))
                            }
                            trains_with_tracking.append(train_info)
                        
                        message_count += 1
                        if message_count >= 3:
                            break
                except json.JSONDecodeError:
                    pass
        
        print(f"✅ Found {len(trains_with_tracking)} trains with GPS tracking")
        
        if not trains_with_tracking:
            print("❌ No trains with active GPS found")
            return
        
        # Display train details
        print("\n📋 Trains with GPS tracking:")
        for train in trains_with_tracking:
            print(f"  • {train['number']} → {train['destination']:20} @ {train['departure_time']} (ID: {train['id']})")
        
        # Step 2: Subscribe to first train with tracking
        if trains_with_tracking:
            train = trains_with_tracking[0]
            print(f"\n📍 Step 2: Subscribing to trajectory of train {train['number']}...")
            
            # Use SUB instead of GET to keep connection open for updates
            trajectory_command = f"SUB full_trajectory_{train['id']}"
            await ws.send(trajectory_command)
            print(f"Sent: {trajectory_command}")
            print("Waiting for trajectory updates (30 seconds)...\n")
            
            # Wait for updates
            try:
                async with asyncio.timeout(30):  # Wait up to 30 seconds
                    async for msg in ws:
                        if isinstance(msg, str):
                            try:
                                data = json.loads(msg)
                                print(f"Received: {data.get('source', 'unknown')}")
                                
                                if data.get('source', '').startswith('full_trajectory_'):
                                    content = data.get('content')
                                    
                                    if content is not None:
                                        print(f"\n✅ GOT TRAJECTORY DATA!")
                                        print(json.dumps(data, indent=2))
                                        print("\n" + "=" * 80)
                                        return
                                    else:
                                        print(f"   Content: None\n")
                                        
                            except json.JSONDecodeError:
                                pass
            except asyncio.TimeoutError:
                print(f"\n⏱️  Timeout - no trajectory updates received")
        
        print("\n❌ No active trajectory data found")
                        #     content = data.get('content', {})
                            
                        #     # Extract position information
                        #     properties = content.get('properties', {})
                        #     geometry = content.get('geometry', {})
                        #     coordinates = geometry.get('coordinates', [])
                            



def main():
    """Main entry point - track the next incoming S-Bahn."""
    print("=" * 80)
    print("🚉 Tracking Next S-Bahn to Fasanenpark (Real-time via geops.io)")
    print("=" * 80)
    
    try:
        asyncio.run(track_next_train(WS_URL, FASANENPARK_UIC))
    except KeyboardInterrupt:
        print("\n\n👋 Stopped by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    main()
