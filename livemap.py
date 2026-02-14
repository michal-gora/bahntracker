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

def run_geops_client():
    API_KEY = "5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"
    WS_URL = f"wss://api.geops.io/realtime-ws/v1/?key={API_KEY}"
    BBOX_CMD = "BBOX 1269000 6087000 1350000 6200000 5 tenant=sbm"

    def on_open(ws):
        print("✅ WS Connected.")
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
                
                line_info = props.get('line', {})
                line_name = line_info.get('name', '?')
                bg_color = line_info.get('color', '#FF0000')
                text_color = line_info.get('text_color', '#FFFFFF')
                state = props.get('state', 'DRIVING') 

                # 1. Calculate Heading
                heading = None # Default is None (Unknown)
                coords_poly = geom.get('coordinates', [])
                
                if coords_poly and len(coords_poly) >= 2:
                    p0 = coords_poly[0]
                    p1 = coords_poly[1]
                    dx = p1[0] - p0[0]
                    dy = p1[1] - p0[1]
                    
                    if abs(dx) > 0.1 or abs(dy) > 0.1:
                        theta = math.atan2(dy, dx)
                        heading = (450 - math.degrees(theta)) % 360

                # 2. Get Position
                lat, lon = 0, 0
                if 'raw_coordinates' in props:
                    lon, lat = props['raw_coordinates']
                elif coords_poly:
                    x, y = coords_poly[0]
                    lat = (2 * math.atan(math.exp((y / 20037508.34) * 180 * math.pi / 180)) - math.pi / 2) * 180 / math.pi
                    lon = (x / 20037508.34) * 180

                # 3. Store
                if lat != 0 and lon != 0:
                    with DATA_LOCK:
                        # Fallback to old heading if calc failed
                        if heading is None:
                            prev = LIVE_DATA.get(train_id)
                            if prev:
                                heading = prev.get('heading') # Keep old (might be None or Valid)

                        LIVE_DATA[train_id] = {
                            "id": line_name, 
                            "lat": lat, 
                            "lon": lon, 
                            "color": bg_color,
                            "text_color": text_color,
                            "state": state,
                            "heading": heading, # Can be None
                            "ts": time.time()
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
    
    try:
        with open(ROUTES_FILE, 'r') as f:
            folium.GeoJson(json.load(f), name='S-Bahn Routes', style_function=lambda x: {'color': 'blue'}).add_to(m)
    except: pass

    train_layer = folium.FeatureGroup(name="Live Trains")
    train_layer.add_to(m)
    map_var = m.get_name()
    layer_var = train_layer.get_name()

    m.get_root().html.add_child(folium.Element("""
        <style>
        .train-icon {
            display: flex; align-items: center; justify-content: center;
            font-family: sans-serif; font-weight: bold; font-size: 10px;
            color: white; box-shadow: 0 2px 4px rgba(0,0,0,0.5);
            transition: all 0.3s ease; position: relative;
        }
        .driving { border-radius: 50%; border: 2px solid white; }
        .boarding { border-radius: 6px; border: 3px double white; transform: scale(1.1); z-index: 1000 !important; }
        .arrow-pointer {
            position: absolute; top: -5px; left: 50%; margin-left: -4px;
            width: 0; height: 0; border-left: 4px solid transparent;
            border-right: 4px solid transparent; border-bottom: 6px solid black;
            transform-origin: center 17px;
        }
        </style>
    """))

    m.get_root().html.add_child(folium.Element(f"""
        <script>
        document.addEventListener("DOMContentLoaded", function() {{
            setTimeout(function() {{
                var myMap = {map_var};
                var liveLayer = {layer_var};

                function update() {{
                    fetch('/api/trains').then(r=>r.json()).then(data => {{
                        liveLayer.clearLayers();
                        data.forEach(t => {{
                            var isBoarding = (t.state === 'BOARDING' || t.state === 'STOPPING');
                            var stateClass = isBoarding ? 'boarding' : 'driving';
                            
                            // Only show arrow if driving AND heading is known (not null)
                            var arrowHtml = (!isBoarding && t.heading !== null) 
                                ? `<div class="arrow-pointer" style="transform: rotate(${{t.heading}}deg);"></div>` 
                                : '';
                            
                            var icon = L.divIcon({{
                                className: 'custom-train-icon', 
                                html: `<div class="train-icon ${{stateClass}}" style="
                                    background-color: ${{t.color}}; 
                                    color: ${{t.text_color}};
                                    width: 24px; height: 24px;">
                                    ${{t.id}}
                                    ${{arrowHtml}}
                                </div>`,
                                iconSize: [24, 24],
                                iconAnchor: [12, 12]
                            }});
                            L.marker([t.lat, t.lon], {{icon: icon}})
                             .bindPopup(`Line: <b>${{t.id}}</b><br>State: ${{t.state}}`)
                             .addTo(liveLayer);
                        }});
                    }});
                }}
                setInterval(update, 1000);
            }}, 1000);
        }});
        </script>
    """))

    folium.LayerControl(collapsed=False).add_to(m)
    return m._repr_html_()

@app.route('/api/trains')
def get_trains():
    with DATA_LOCK:
        now = time.time()
        return jsonify([t for t in LIVE_DATA.values() if now - t['ts'] < 60])

if __name__ == '__main__':
    app.run(debug=True, port=5000)
