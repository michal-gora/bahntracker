from flask import Flask, jsonify
import folium
import json
import threading
import time
import websocket
import math

app = Flask(__name__)
ROUTES_FILE = 'route.geojson'

LIVE_DATA = {}
DATA_LOCK = threading.Lock()

# --- ACCURATE COORDINATE CONVERSION ---
def epsg3857_to_wgs84(x, y):
    lon = (x / 20037508.34) * 180
    lat = (y / 20037508.34) * 180
    lat = 180 / math.pi * (2 * math.atan(math.exp(lat * math.pi / 180)) - math.pi / 2)
    return lat, lon

# --- WEBSOCKET CLIENT ---
def geops_worker():
    API_KEY = "5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"
    # Munich BBOX (Web Mercator meters)
    # 1230000, 6100000 is roughly Munich area
    BBOX_CMD = "BBOX 1150000 6300000 1300000 6450000 10 mots=rail"
    
    def on_open(ws):
        print("✅ WS Connected. Sending BUFFER & BBOX...")
        ws.send("BUFFER 60000 500")
        time.sleep(1)
        ws.send(BBOX_CMD)
        
        # Pinger
        def pinger():
            while ws.sock and ws.sock.connected:
                time.sleep(20)
                try:
                    ws.send("PING")
                except: break
        threading.Thread(target=pinger, daemon=True).start()

    def on_message(ws, message):
        try:
            msg = json.loads(message)
            
            # DEBUG: Print first trajectory to confirm data format
            if 'source' in msg and msg['source'] == 'trajectory':
                content = msg.get('content', {})
                props = content.get('properties', {})
                geom = content.get('geometry', {})
                coords = geom.get('coordinates', [])
                
                if coords:
                    train_id = props.get('train_id', 'unknown')
                    name = props.get('line', {}).get('name', '?')
                    
                    # Convert coords
                    x, y = coords[0]
                    lat, lon = epsg3857_to_wgs84(x, y)
                    
                    # Store
                    with DATA_LOCK:
                        LIVE_DATA[train_id] = {
                            "id": name, "lat": lat, "lon": lon, 
                            "ts": time.time(), "raw": (x,y)
                        }
                    
                    # Debug print every 10th update so terminal isn't flooded
                    if len(LIVE_DATA) % 10 == 0:
                        print(f"🔹 Update: {name} at {lat:.4f}, {lon:.4f} (Raw: {x},{y})")
                        
        except Exception as e:
            print(f"❌ Msg Error: {e}")

    # Reconnect loop
    while True:
        print("🔄 Connecting to geOps...")
        try:
            ws = websocket.WebSocketApp(f"wss://api.geops.io/realtime-ws/v1/?key={API_KEY}",
                                      on_open=on_open, on_message=on_message)
            ws.run_forever()
        except Exception as e:
            print(f"⚠️ WS Fail: {e}")
            time.sleep(5)

threading.Thread(target=geops_worker, daemon=True).start()

# --- FLASK ---
@app.route('/')
def map_view():
    # Centered on Munich
    m = folium.Map(location=[48.137, 11.575], zoom_start=10)
    
    # Debug Box on Map
    m.get_root().html.add_child(folium.Element("""
        <div style="position: fixed; top: 10px; right: 10px; width: 150px; 
             background: white; padding: 10px; z-index: 1000; border: 2px solid red;">
             <b>Debug Info</b><br>
             Trains: <span id="train-count">0</span>
        </div>
    """))

    map_var = m.get_name()
    m.get_root().html.add_child(folium.Element(f"""
        <script>
        document.addEventListener("DOMContentLoaded", function() {{
            setTimeout(function() {{
                var myMap = {map_var};
                var currentLayer = L.layerGroup().addTo(myMap);

                function update() {{
                    fetch('/api/trains').then(r=>r.json()).then(data => {{
                        document.getElementById('train-count').innerText = data.length;
                        
                        var newLayer = L.layerGroup();
                        data.forEach(t => {{
                            L.circleMarker([t.lat, t.lon], {{
                                radius: 5, color: 'red', fillOpacity: 1
                            }}).bindPopup(t.id).addTo(newLayer);
                        }});
                        newLayer.addTo(myMap);
                        myMap.removeLayer(currentLayer);
                        currentLayer = newLayer;
                    }});
                }}
                setInterval(update, 2000);
            }}, 1000);
        }});
        </script>
    """))
    return m._repr_html_()

@app.route('/api/trains')
def get_trains():
    with DATA_LOCK:
        # Return all trains, no timeout filtering for debug
        return jsonify(list(LIVE_DATA.values()))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
