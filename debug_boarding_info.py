import asyncio
import json
import websockets
from datetime import datetime

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"

# S3 stations from Holzkirchen to Mammendorf (in order)
S3_STATIONS = [
    ("Holzkirchen", "8002980"),
    ("Otterfing", "8004726"),
    ("Großhelfendorf", "8005299"),
    ("Deisenhofen", "8001404"),
    ("Sauerlach", "8002161"),
    ("Höllriegelskreuth", "8005831"),
    ("Pullach", "8005991"),
    ("Fasanenpark", "8001963"),
    ("Fasanerie", "8004146"),
    ("Unterhaching", "8004148"),
    ("Taufkirchen", "8004138"),
    ("Perlach", "8000262"),
    ("Neuperlach Süd", "8004136"),
    ("Ostbahnhof", "8004131"),
    ("Rosenheimer Platz", "8004135"),
    ("Isartor", "8004132"),
    ("Marienplatz", "8098263"),
    ("Karlsplatz (Stachus)", "8004129"),
    ("Hauptbahnhof", "8004128"),
    ("Hackerbrücke", "8004179"),
    ("Donnersbergerbrücke", "8004151"),
    ("Hirschgarten", "8004158"),
    ("Laim", "8004152"),
    ("Pasing", "8004153"),
    ("Leienfelsstraße", "8002377"),
    ("Langwied", "8004667"),
    ("Lochhausen", "8001996"),
    ("Gröbenzell", "8002247"),
    ("Olching", "8003824"),
    ("Maisach", "8003828"),
    ("Mammendorf", "8002533")
]

async def track_all_trains_verbose(ws):
    """Track ALL trains and show their properties"""
    await ws.send("BUFFER 100 100")
    await ws.send("BBOX 11.4 48.0 11.8 48.3 5 tenant=sbm")
    
    print("🔍 Monitoring all S-Bahn trains in Munich area...\n")
    print("Looking for trains going to Maisach/Mammendorf\n")
    print("="*80 + "\n")
    
    seen_trains = set()
    
    try:
        async with asyncio.timeout(15):
            async for msg in ws:
                data = json.loads(msg)
                if data.get('source') == 'buffer':
                    content_items = data.get('content', [])
                    for item in content_items:
                        item_content = item.get('content', {})
                        props = item_content.get('properties', {})
                        
                        train_number = props.get('train_number')
                        line = props.get('line')
                        destination = props.get('destination', '')
                        
                        # Only S3 line
                        if line == 'S3' and train_number not in seen_trains:
                            seen_trains.add(train_number)
                            
                            # Check if going to Maisach/Mammendorf
                            going_west = 'Maisach' in destination or 'Mammendorf' in destination
                            
                            print(f"🚆 Train {train_number} → {destination}")
                            print(f"   Line: {line}")
                            print(f"   State: {props.get('state')}")
                            print(f"   Going to Maisach/Mammendorf: {'✅ YES' if going_west else '❌ NO'}")
                            print(f"   Train ID: {props.get('train_id')}")
                            print()
                            
                            # Check for station-related fields
                            print("   🔍 Station-related fields:")
                            station_fields = {}
                            for key in props.keys():
                                if 'station' in key.lower() or 'stop' in key.lower() or 'uic' in key.lower():
                                    station_fields[key] = props[key]
                            
                            if station_fields:
                                for key, value in station_fields.items():
                                    print(f"      - {key}: {value}")
                            else:
                                print("      (No station-related fields found)")
                            
                            print()
                            
                            # If BOARDING, show ALL properties
                            if props.get('state') == 'BOARDING':
                                print("   🛑 BOARDING STATE - FULL PROPERTIES:")
                                print(json.dumps(props, indent=6, ensure_ascii=False))
                                print()
                            
                            print("-"*80)
                            print()
                            
    except asyncio.TimeoutError:
        pass
    
    if not seen_trains:
        print("❌ No S3 trains found in the monitoring period")
    else:
        print(f"\n✅ Monitored {len(seen_trains)} unique S3 train(s)")


async def main():
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print("🔌 Connected to WebSocket\n")
        await track_all_trains_verbose(ws)
        
        print("\n" + "="*80)
        print("STATION LIST REFERENCE (S3 Line: Holzkirchen → Mammendorf)")
        print("="*80)
        for i, (name, uic) in enumerate(S3_STATIONS):
            print(f"{i:2d}. {name:30s} (UIC: {uic})")


if __name__ == "__main__":
    asyncio.run(main())
