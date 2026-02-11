import asyncio
import json
import websockets

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"

async def capture_all_trains(ws):
    """Capture ALL trains without filtering"""
    await ws.send("BUFFER 100 100")
    # Wider BBOX for entire Munich region
    await ws.send("BBOX 11.0 47.8 12.2 48.5 5 tenant=sbm")
    
    print("🔍 Capturing ALL trains in Munich region (30 second window)...\n")
    
    trains_data = []
    
    try:
        async with asyncio.timeout(30):
            async for msg in ws:
                data = json.loads(msg)
                if data.get('source') == 'buffer':
                    content_items = data.get('content', [])
                    for item in content_items:
                        item_content = item.get('content', {})
                        props = item_content.get('properties', {})
                        
                        train_number = props.get('train_number')
                        if train_number:
                            trains_data.append(props)
    except asyncio.TimeoutError:
        pass
    
    return trains_data


async def main():
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print("🔌 Connected to WebSocket\n")
        
        trains = await capture_all_trains(ws)
        
        print(f"\n✅ Captured {len(trains)} trains\n")
        print("="*80)
        
        # Group by line
        by_line = {}
        for train in trains:
            line = train.get('line', 'Unknown')
            if line not in by_line:
                by_line[line] = []
            by_line[line].append(train)
        
        print(f"Trains by line:")
        for line, line_trains in sorted(by_line.items()):
            print(f"  {line}: {len(line_trains)} trains")
        
        print("\n" + "="*80)
        print("S3 TRAINS (showing ALL fields):")
        print("="*80 + "\n")
        
        s3_trains = by_line.get('S3', [])
        
        if not s3_trains:
            print("❌ No S3 trains found!")
            print("\nAll available lines:", list(by_line.keys()))
        else:
            for i, train in enumerate(s3_trains, 1):
                train_number = train.get('train_number')
                state = train.get('state')
                destination = train.get('destination', 'Unknown')
                train_id = train.get('train_id')
                
                print(f"--- Train #{i}: {train_number} → {destination} ---")
                print(f"State: {state}")
                print(f"Train ID: {train_id}")
                print()
                
                # Show ALL fields
                print("ALL PROPERTIES:")
                for key in sorted(train.keys()):
                    value = train[key]
                    # Truncate long arrays
                    if isinstance(value, list) and len(str(value)) > 100:
                        print(f"  {key}: [{len(value)} items] {str(value)[:100]}...")
                    else:
                        print(f"  {key}: {value}")
                
                print()
                print("="*80)
                print()


if __name__ == "__main__":
    asyncio.run(main())
