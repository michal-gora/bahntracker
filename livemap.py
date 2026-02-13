import websocket
import json
import threading
import time
import traceback
import math

# YOUR SETTINGS
API_KEY = "5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"
WS_URL = f"wss://api.geops.io/realtime-ws/v1/?key={API_KEY}"

# Different BBOX attempts (Munich Area)
BBOX_MUNICH = "BBOX 1269000 6087000 1350000 6200000 5 tenant=sbm"
# BBOX_ZURICH = "BBOX 946000 5990000 962000 6010000 10" # Known working fallback

def on_open(ws):
    print("\n✅ CONNECTED to geOps!")
    print("------------------------------------------------")
    
    # 1. Send Buffer (Vital to prevent timeout)
    print(">> Sending BUFFER 100 100...")
    ws.send("BUFFER 100 100")
    time.sleep(1)
    
    # 2. Send BBOX
    print(f">> Sending {BBOX_MUNICH}...")
    ws.send(BBOX_MUNICH)
    print("------------------------------------------------")
    print("⏳ Waiting for data... (Press Ctrl+C to stop)")

def on_message(ws, message):
    try:
        msg = json.loads(message)
        source = msg.get('source')
        
        # 1. Unpack Buffer or Single Trajectory
        # We normalize everything into a list of "message objects"
        items = []
        if source == 'trajectory':
            items = [msg] 
        elif source == 'buffer':
            items = msg.get('content', []) 
            # Defensive: verify it is actually a list
            if not isinstance(items, list):
                return
        else:
            # Ignore other messages (status, etc)
            return
        
        # 2. Process Items
        for item in items:
            # Defensive: Item must be a dict
            if not isinstance(item, dict):
                continue

            # Verify source is trajectory
            if item.get('source') != 'trajectory':
                continue
            
            # Extract content safely
            content = item.get('content')
            if not content or not isinstance(content, dict):
                continue

            props = content.get('properties', {})
            geom = content.get('geometry', {})
            
            # Get ID & Line
            train_id = props.get('train_id', 'unknown')
            line_name = props.get('line', {}).get('name', '?')
            
            # Get Coordinates
            lat, lon = 0.0, 0.0
            
            # A) Try RAW Lat/Lon (Best)
            if 'raw_coordinates' in props:
                raw = props['raw_coordinates']
                if isinstance(raw, list) and len(raw) >= 2:
                    lon, lat = raw[0], raw[1]
            
            # B) Fallback to Geometry (EPSG:3857)
            if lat == 0.0 and geom:
                coords = geom.get('coordinates', [])
                if coords and len(coords) > 0:
                    x, y = coords[0]
                    # Inverse Mercator
                    lon = (x / 20037508.34) * 180
                    lat = (y / 20037508.34) * 180
                    lat = 180 / math.pi * (2 * math.atan(math.exp(lat * math.pi / 180)) - math.pi / 2)

            # PRINT RESULT (Success!)
            if lat != 0 and lon != 0:
                print(f"✅ Found: {line_name} ({train_id}) at {lat:.5f}, {lon:.5f}")
                
    except Exception:
        traceback.print_exc()


def on_error(ws, error):
    print(f"❌ ERROR: {error}")

def on_close(ws, status, msg):
    print(f"⚠️ CLOSED: {status} - {msg}")

# Main execution
if __name__ == "__main__":
    websocket.enableTrace(False) # Set True for full network debug
    ws = websocket.WebSocketApp(
        WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.run_forever()
