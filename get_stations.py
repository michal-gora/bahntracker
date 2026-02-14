import websocket
import json
import math
import time
import threading

# --- CONFIGURATION ---
API_KEY = "5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"
WS_URL = f"wss://api.geops.io/realtime-ws/v1/?key={API_KEY}"
BBOX = "1269000 6087000 1350000 6200000 5 tenant=sbm"

# Store unique stations here
unique_stations = {}
is_collecting = True

def mercator_to_latlon(x, y):
    lon = (x / 20037508.34) * 180
    lat = (y / 20037508.34) * 180
    lat = 180 / math.pi * (2 * math.atan(math.exp(lat * math.pi / 180)) - math.pi / 2)
    return lat, lon

def on_open(ws):
    print("✅ Connected. Fetching stations...")
    ws.send(f"BBOX {BBOX}")
    ws.send("GET station")

def on_message(ws, message):
    if not is_collecting: return
    try:
        msg = json.loads(message)
        items = msg.get('content') if msg.get('source') == 'list' else [msg]
        
        if not items: return

        for item in items:
            content = item.get('content') if 'content' in item else item
            if not isinstance(content, dict): continue
            
            src = item.get('source') or msg.get('source')
            if src != 'station': continue

            props = content.get('properties', {})
            geom = content.get('geometry', {})
            
            # FILTER: S-Bahn/U-Bahn
            mot = props.get('mot', {})
            if not mot.get('rail') and not mot.get('subway'):
                continue

            name = props.get('name', 'Unknown Station')
            uic = props.get('uic', name)
            
            coords = geom.get('coordinates')
            if coords and len(coords) == 2:
                lat, lon = mercator_to_latlon(coords[0], coords[1])
                unique_stations[uic] = {
                    "uic": uic, # Store it inside for easy access
                    "name": name,
                    "lat": round(lat, 5),
                    "lon": round(lon, 5)
                }
    except: pass

def on_error(ws, error):
    pass # Ignore errors during close

def on_close(ws, close_status_code, close_msg):
    pass

# --- MAIN ---
if __name__ == "__main__":
    ws = websocket.WebSocketApp(WS_URL, on_open=on_open, on_message=on_message)
    
    # Run WS in background
    wst = threading.Thread(target=ws.run_forever)
    wst.daemon = True
    wst.start()

    # Collect for 8 seconds
    print("Collecting data for 8 seconds...")
    time.sleep(8)
    is_collecting = False
    ws.close()
    
    # Wait a moment for thread to die
    time.sleep(1)

    print(f"\n✅ Finished! Found {len(unique_stations)} stations.")
    print("---------------------------------------------------")
    print("const STATIONS_DATA = [")
    
    sorted_stations = sorted(unique_stations.items(), key=lambda item: item[1]['name'])
    
    for uic, s in sorted_stations:
        # Use the key 'uic' from the dictionary, or the stored one if you saved it inside
        print(f'    {{ "uic": "{uic}", "name": "{s["name"]}", "lat": {s["lat"]}, "lon": {s["lon"]} }},')
    
    print("];")
