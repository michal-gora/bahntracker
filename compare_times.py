import asyncio
import json
import websockets
from datetime import datetime

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"
TRAIN_ID = "sbm_140330651162704"  # Train 6398 to Mammendorf
FASANENPARK_UIC = "8001963"

def format_time(timestamp_ms: int) -> str:
    """Convert Unix timestamp (milliseconds) to human-readable time."""
    dt = datetime.fromtimestamp(timestamp_ms / 1000)
    return dt.strftime('%H:%M:%S')

async def compare_times():
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print(f"🔍 Comparing timestamps for train {TRAIN_ID}\n")
        
        # First, get timetable info for this train
        print("📋 Step 1: Get timetable data...")
        timetable_command = f"GET timetable_{FASANENPARK_UIC}"
        await ws.send(timetable_command)
        
        timetable_data = None
        message_count = 0
        
        async for msg in ws:
            if isinstance(msg, str):
                try:
                    data = json.loads(msg)
                    
                    if data.get('source', '').startswith('timetable_'):
                        content = data.get('content', {})
                        if content.get('train_id') == TRAIN_ID:
                            timetable_data = content
                            print(f"\n✅ Found timetable entry for train {content.get('train_number')}")
                            print(f"\nTimetable fields:")
                            print(f"  • train_id: {content.get('train_id')}")
                            print(f"  • train_number: {content.get('train_number')}")
                            print(f"  • to (destination): {content.get('to')}")
                            print(f"  • time: {content.get('time')} → {format_time(content.get('time', 0))}")
                            print(f"  • ris_aimed_time: {content.get('ris_aimed_time')} → {format_time(content.get('ris_aimed_time', 0))}")
                            print(f"  • ris_estimated_time: {content.get('ris_estimated_time')} → {format_time(content.get('ris_estimated_time', 0)) if content.get('ris_estimated_time') else 'None'}")
                            print(f"  • has_fzo (has GPS): {content.get('has_fzo')}")
                            break
                        
                        message_count += 1
                        if message_count >= 20:
                            break
                except json.JSONDecodeError:
                    pass
        
        if not timetable_data:
            print("❌ Could not find timetable data for this train")
            return
        
        # Now get trajectory data
        print("\n📍 Step 2: Get trajectory data...")
        trajectory_command = f"GET full_trajectory_{TRAIN_ID}"
        await ws.send(trajectory_command)
        
        async for msg in ws:
            if isinstance(msg, str):
                try:
                    data = json.loads(msg)
                    
                    if data.get('source', '').startswith('full_trajectory_'):
                        content = data.get('content')
                        
                        if content:
                            print(f"\n✅ Got trajectory data")
                            print(f"\nTrajectory timestamps:")
                            print(f"  • timestamp (root): {data.get('timestamp')} → {format_time(data.get('timestamp', 0))}")
                            
                            if content.get('features'):
                                feature = content['features'][0]
                                props = feature.get('properties', {})
                                print(f"  • event_timestamp: {props.get('event_timestamp')} → {format_time(props.get('event_timestamp', 0))}")
                                print(f"  • line_name: {props.get('line_name')}")
                                print(f"  • journey_id: {props.get('journey_id')}")
                            
                            print(f"\n📊 Comparison:")
                            print(f"  Timetable 'time' (Fasanenpark departure): {format_time(timetable_data.get('time', 0))}")
                            print(f"  Trajectory 'event_timestamp': {format_time(props.get('event_timestamp', 0))}")
                            print(f"  Trajectory root 'timestamp' (API response time): {format_time(data.get('timestamp', 0))}")
                            
                            time_diff = (props.get('event_timestamp', 0) - timetable_data.get('time', 0)) / 1000
                            print(f"\n⏱️  Difference: {time_diff:.0f} seconds")
                            
                            if abs(time_diff) < 60:
                                print("  → event_timestamp ≈ departure time from Fasanenpark!")
                            else:
                                print("  → event_timestamp is different from Fasanenpark departure")
                                print("     (might be: journey start, last position update, or something else)")
                            
                        return
                        
                except json.JSONDecodeError:
                    pass

if __name__ == "__main__":
    asyncio.run(compare_times())
