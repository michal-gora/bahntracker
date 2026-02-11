import asyncio
import json
import websockets

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"

async def find_any_active_train(ws):
    """Find any active S-Bahn train"""
    await ws.send("BUFFER 100 100")
    await ws.send("BBOX 11.4 48.0 11.8 48.3 5 tenant=sbm")
    
    print("🔍 Looking for ANY active S-Bahn train...\n")
    
    try:
        async with asyncio.timeout(10):
            async for msg in ws:
                data = json.loads(msg)
                if data.get('source') == 'buffer':
                    content_items = data.get('content', [])
                    for item in content_items:
                        item_content = item.get('content', {})
                        props = item_content.get('properties', {})
                        
                        if props.get('line') == 'S3':
                            return item_content, props
    except asyncio.TimeoutError:
        return None, None
    return None, None


async def main():
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print("🔌 Connected to WebSocket\n")
        
        live_data, props = await find_any_active_train(ws)
        
        if live_data:
            print(f"✅ Found active train {props.get('train_number')}!")
            print(f"   Line: {props.get('line')}")
            print(f"   State: {props.get('state')}")
            print(f"   Train ID: {props.get('train_id')}")
            print()
            
            print("="*80)
            print("FULL PROPERTIES:")
            print("="*80)
            print(json.dumps(props, indent=2, ensure_ascii=False))
            print()
            
            print("="*80)
            print("KEY FINDINGS:")
            print("="*80)
            has_next_stops = 'next_stoppoints' in props
            has_at_stop = 'at_stoppoint' in props
            print(f"✅ Has 'next_stoppoints': {has_next_stops} - {props.get('next_stoppoints', 'NOT PRESENT')}")
            print(f"✅ Has 'at_stoppoint': {has_at_stop} - {props.get('at_stoppoint', 'NOT PRESENT')}")
            print(f"✅ Route identifier: {props.get('route_identifier')}")
            
        else:
            print("❌ No active S3 trains found right now")


if __name__ == "__main__":
    asyncio.run(main())
