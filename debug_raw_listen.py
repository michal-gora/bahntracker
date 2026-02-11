import asyncio
import json
import websockets

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"

async def listen_raw(ws):
    """Just listen to whatever comes through"""
    
    # Try different command formats
    print("📡 Trying BUFFER + BBOX commands...\n")
    await ws.send("BUFFER 100 100")
    await asyncio.sleep(0.5)
    
    # Munich area coordinates (wider)
    await ws.send("BBOX 1230000 6090000 1350000 6180000 5 tenant=sbm")
    
    message_count = 0
    trains_seen = set()
    
    try:
        async with asyncio.timeout(20):
            async for msg in ws:
                message_count += 1
                data = json.loads(msg)
                source = data.get('source', 'unknown')
                
                if message_count <= 5:
                    print(f"Message #{message_count}:")
                    print(f"  Source: {source}")
                    print(f"  Keys: {list(data.keys())}")
                    print()
                
                if source == 'buffer':
                    content_items = data.get('content', [])
                    print(f"📦 Buffer message with {len(content_items)} items")
                    
                    for item in content_items:
                        item_content = item.get('content', {})
                        props = item_content.get('properties', {})
                        train_number = props.get('train_number')
                        line = props.get('line')
                        destination = props.get('destination')
                        state = props.get('state')
                        
                        if train_number and train_number not in trains_seen:
                            trains_seen.add(train_number)
                            print(f"  🚆 Train {train_number} ({line}) → {destination} [{state}]")
                            
                            # Check for station fields
                            station_keys = [k for k in props.keys() if 'stop' in k.lower() or 'station' in k.lower()]
                            if station_keys:
                                print(f"     Station fields: {station_keys}")
                                for key in station_keys:
                                    print(f"       {key}: {props[key]}")
                    print()
                    
    except asyncio.TimeoutError:
        print(f"\n⏱️ Timeout after {message_count} messages")
    
    print(f"\n✅ Total messages: {message_count}")
    print(f"✅ Unique trains seen: {len(trains_seen)}")
    return trains_seen


async def main():
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print("🔌 Connected to WebSocket\n")
        trains = await listen_raw(ws)


if __name__ == "__main__":
    asyncio.run(main())
