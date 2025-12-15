import asyncio
import json
import websockets
from datetime import datetime

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"
TRAIN_ID = "sbm_140330651162704"  # Train 6398 to Mammendorf

def format_time(timestamp_ms: int) -> str:
    """Convert Unix timestamp (milliseconds) to human-readable time."""
    dt = datetime.fromtimestamp(timestamp_ms / 1000)
    return dt.strftime('%H:%M:%S')

async def test_timestamp_updates():
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print(f"🔍 Testing if event_timestamp updates over time\n")
        
        for i in range(3):
            print(f"📍 Request {i+1}/3...")
            trajectory_command = f"GET full_trajectory_{TRAIN_ID}"
            await ws.send(trajectory_command)
            
            async for msg in ws:
                if isinstance(msg, str):
                    try:
                        data = json.loads(msg)
                        
                        if data.get('source', '').startswith('full_trajectory_'):
                            content = data.get('content')
                            
                            if content:
                                root_timestamp = data.get('timestamp')
                                feature = content['features'][0]
                                props = feature.get('properties', {})
                                event_timestamp = props.get('event_timestamp')
                                
                                print(f"  Root timestamp: {format_time(root_timestamp)} ({root_timestamp})")
                                print(f"  Event timestamp: {format_time(event_timestamp)} ({event_timestamp})")
                                print(f"  Coordinates count: {len(feature['geometry']['coordinates'])}")
                                print()
                                
                            break
                            
                    except json.JSONDecodeError:
                        pass
            
            if i < 2:
                print("⏳ Waiting 5 seconds...\n")
                await asyncio.sleep(5)
        
        print("📊 Summary:")
        print("  If event_timestamp stays the same → likely journey start or specific departure time")
        print("  If event_timestamp updates → likely last GPS position update time")

if __name__ == "__main__":
    asyncio.run(test_timestamp_updates())
