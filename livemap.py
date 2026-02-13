from flask import Flask, jsonify
import folium
import json
import threading
import time
import websocket
import math

app = Flask(__name__)
ROUTES_FILE = 'route.geojson'

# --- GLOBAL SHARED STATE ---
LIVE_DATA = {}
DATA_LOCK = threading.Lock()

# --- GEOPS WORKER (Same as before) ---
def run_geops_client():
    API_KEY = "5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"
    WS_URL = f"wss://api.geops.io/realtime-ws/v1/?key={API_KEY}"
    BBOX_CMD = "BBOX 1269000 6087000 1350000 6200000 5 tenant=sbm"

    def on_open(ws):
        print("✅ WS Connected. Sending Init Commands...")
        ws.send("BUFFER 100 100")
        time.sleep(0.5)
        ws.send(BBOX_CMD)
        
        def pinger():
            while ws.sock and ws.sock.connected:
                time.sleep(10)
                try: ws.send("PING")
                except: break
        threading.Thread(target=pinger, daemon=True).start()

    def on_message(ws, message):
        try:
            msg = json.loads(message)
            source = msg.get('source')
            items = []
            if source == 'trajectory': items = [msg]
            elif source == 'buffer': items = msg.get('content', [])
            
            for item in items:
                content = item.get('content') if 'content' in item else item
                if item.get('source') != 'trajectory': continue

                props = content.get('properties', {})
                geom = content.get('geometry', {})
                train_id = props.get('train_id')
                line_name = props.get('line', {}).get('name', '?')
                
                lat, lon = 0, 0
                if 'raw_coordinates' in props:
                    lon, lat = props['raw_coordinates']
                elif 'geometry' in content:
                    coords = content['geometry'].get('coordinates', [])
                    if coords:
                        x, y = coords[0]
                        lat = (2 * math.atan(math.exp((y / 20037508.34) * 180 * math.pi / 180)) - math.pi / 2) * 180 / math.pi
                        lon = (x / 20037508.34) * 180

                if lat != 0 and lon != 0:
                    with DATA_LOCK:
                        LIVE_DATA[train_id] = {
                            "id": line_name, "lat": lat, "lon": lon, "ts": time.time()
                        }
        except: pass

    while True:
        try:
            ws = websocket.WebSocketApp(WS_URL, on_open=on_open, on_message=on_message)
            ws.run_forever()
        except: time.sleep(5)

threading.Thread(target=run_geops_client, daemon=True).start()


# --- FLASK ---
@app.route('/')
def map_view():
    m = folium.Map(location=[48.137, 11.575], zoom_start=10)
    
    # 1. Static Routes Layer
    try:
        with open(ROUTES_FILE, 'r') as f:
            folium.GeoJson(
                json.load(f), 
                name='S-Bahn Routes', 
                style_function=lambda x: {'color': 'blue'}
            ).add_to(m)
    except: pass

    # 2. EMPTY Live Trains Layer (Placeholder)
    # We add this so it shows up in LayerControl
    train_layer = folium.FeatureGroup(name="Live Trains")
    train_layer.add_to(m)
    
    # Get IDs to use in JS
    map_var = m.get_name()
    layer_var = train_layer.get_name()

    # 3. Inject JS to populate that SPECIFIC layer
    m.get_root().html.add_child(folium.Element(f"""
        <script>
        document.addEventListener("DOMContentLoaded", function() {{
            setTimeout(function() {{
                var myMap = {map_var};
                var liveLayer = {layer_var}; // This is the FeatureGroup we created in Python!

                function update() {{
                    fetch('/api/trains').then(r=>r.json()).then(data => {{
                        liveLayer.clearLayers(); // Clear ONLY the train layer
                        
                        data.forEach(t => {{
                            L.circleMarker([t.lat, t.lon], {{
                                radius: 6, color: 'red', fillOpacity: 0.9, weight: 1
                            }}).bindPopup(t.id).addTo(liveLayer);
                        }});
                    }});
                }}
                setInterval(update, 1000);
            }}, 1000);
        }});
        </script>
    """))

    # 4. Add Control (Must be last)
    folium.LayerControl(collapsed=False).add_to(m)
    
    return m._repr_html_()

@app.route('/api/trains')
def get_trains():
    with DATA_LOCK:
        now = time.time()
        return jsonify([t for t in LIVE_DATA.values() if now - t['ts'] < 60])

if __name__ == '__main__':
    app.run(debug=True, port=5000)
