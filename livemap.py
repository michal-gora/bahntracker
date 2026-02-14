from flask import Flask, jsonify
import folium
import json
import threading
import time
import websocket
import math
import os

app = Flask(__name__)
ROUTES_FILE = 'route.geojson'

# --- GLOBAL SHARED STATE ---
LIVE_DATA = {}
DATA_LOCK = threading.Lock()

# --- GEOPS WORKER ---
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

                # --- 1. COORDINATE & HEADING CALCULATION ---
                heading = None 
                coords_poly = geom.get('coordinates', [])
                
                lat, lon = 0, 0
                next_lat, next_lon = None, None

                if coords_poly and len(coords_poly) >= 2:
                    p0 = coords_poly[0]
                    p1 = coords_poly[1]
                    dx = p1[0] - p0[0]
                    dy = p1[1] - p0[1]
                    if abs(dx) > 0.1 or abs(dy) > 0.1:
                        theta = math.atan2(dy, dx)
                        heading = (450 - math.degrees(theta)) % 360
                    
                    next_lat = (2 * math.atan(math.exp((p1[1] / 20037508.34) * 180 * math.pi / 180)) - math.pi / 2) * 180 / math.pi
                    next_lon = (p1[0] / 20037508.34) * 180

                if 'raw_coordinates' in props:
                    lon, lat = props['raw_coordinates']
                elif coords_poly:
                    x, y = coords_poly[0]
                    lat = (2 * math.atan(math.exp((y / 20037508.34) * 180 * math.pi / 180)) - math.pi / 2) * 180 / math.pi
                    lon = (x / 20037508.34) * 180

                # --- 2. TIME CALCULATION ---
                intervals = props.get('time_intervals', [])
                start_ts = props.get('timestamp', time.time() * 1000) / 1000.0
                next_ts = None

                if intervals and len(intervals) >= 2:
                    try:
                        start_ts = intervals[0][0] / 1000.0
                        next_ts = intervals[1][0] / 1000.0
                    except IndexError: pass

                if lat != 0:
                    with DATA_LOCK:
                        if heading is None:
                            prev = LIVE_DATA.get(train_id)
                            if prev: heading = prev.get('heading')

                        LIVE_DATA[train_id] = {
                            "id": line_name, 
                            "lat": lat, 
                            "lon": lon, 
                            "next_lat": next_lat,
                            "next_lon": next_lon,
                            "start_ts": start_ts,
                            "next_ts": next_ts,
                            "color": bg_color,
                            "text_color": text_color,
                            "state": state,
                            "heading": heading,
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
    
    routes_dir = 'routes_geojson'
    route_layer = folium.FeatureGroup(name='S-Bahn Network')
    
    if os.path.exists(routes_dir):
        for filename in os.listdir(routes_dir):
            if filename.endswith('.geojson'):
                file_path = os.path.join(routes_dir, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        folium.GeoJson(
                            data, 
                            style_function=lambda feature: {
                                'color': feature['properties'].get('color', 'blue'),
                                'weight': 3, 'opacity': 0.7
                            }
                        ).add_to(route_layer)
                except Exception: pass
    
    route_layer.add_to(m)

    train_layer = folium.FeatureGroup(name="Live Trains")
    train_layer.add_to(m)
    map_var = m.get_name()
    layer_var = train_layer.get_name()

    m.get_root().html.add_child(folium.Element("""
        <style>
        .icon-container {
            position: relative; width: 30px; height: 30px;
            display: flex; justify-content: center; align-items: center;
        }
        .train-circle {
            width: 24px; height: 24px; border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            font-family: sans-serif; font-weight: bold; font-size: 10px;
            color: white; z-index: 3; box-sizing: border-box;
            box-shadow: 0 1px 3px rgba(0,0,0,0.5);
        }
        .driving { border-radius: 50%; border: 2px solid white; }
        .boarding { border-radius: 50%; border: 3px double white; transform: scale(1.0); }
        .arrow-pointer {
            position: absolute; top: 0; left: 0; right: 0; bottom: 0;
            z-index: 5; pointer-events: none;
        }
        .arrow-pointer::before {
            content: ''; position: absolute; top: -6px; left: 50%; margin-left: -7px;
            width: 0; height: 0; border-left: 7px solid transparent;
            border-right: 7px solid transparent; border-bottom: 11px solid white; 
            transform-origin: center 21px;
        }
        .arrow-pointer::after {
            content: ''; position: absolute; top: -2px; left: 50%; margin-left: -5px;
            width: 0; height: 0; border-left: 5px solid transparent;
            border-right: 5px solid transparent; border-bottom: 9px solid; 
            transform-origin: center 18px;
        }
        </style>
    """))

    m.get_root().html.add_child(folium.Element(f"""
        <script>
        document.addEventListener("DOMContentLoaded", function() {{
            setTimeout(function() {{
                var myMap = {map_var};
                var liveLayer = {layer_var};
                var markers = {{}}; 
                var trainData = {{}}; 

                // TWEAK THIS: Positive moves trains ahead, Negative delays them
                var TIME_OFFSET = 0.0; 

                function update() {{
                    fetch('/api/trains').then(r=>r.json()).then(data => {{
                        var activeIds = new Set();
                        data.forEach(t => {{
                            activeIds.add(t.id);
                            trainData[t.id] = t;
                            
                            var isBoarding = (t.state === 'BOARDING' || t.state === 'STOPPING');
                            var stateClass = isBoarding ? 'boarding' : 'driving';
                            var arrowStyle = (t.heading !== null) 
                                ? `transform: rotate(${{t.heading}}deg); color: ${{t.color}};` 
                                : 'display: none;';
                            
                            var iconHtml = `
                                <div class="icon-container">
                                    <div class="train-circle ${{stateClass}}" style="
                                        background-color: ${{t.color}}; 
                                        color: ${{t.text_color}};">
                                        ${{t.id}}
                                    </div>
                                    <div class="arrow-pointer" style="${{arrowStyle}}"></div>
                                </div>`;

                            if (!markers[t.id]) {{
                                markers[t.id] = L.marker([t.lat, t.lon], {{
                                    icon: L.divIcon({{ className: 'custom-train-icon', html: iconHtml, iconSize: [30, 30], iconAnchor: [15, 15] }})
                                }}).addTo(liveLayer);
                            }} else {{
                                markers[t.id].setIcon(L.divIcon({{ className: 'custom-train-icon', html: iconHtml, iconSize: [30, 30], iconAnchor: [15, 15] }}));
                            }}
                        }});
                        
                        Object.keys(markers).forEach(id => {{
                            if (!activeIds.has(id)) {{ 
                                liveLayer.removeLayer(markers[id]); 
                                delete markers[id]; 
                                delete trainData[id];
                            }}
                        }});
                    }});
                }}

                function animate() {{
                    var now = (Date.now() / 1000) + TIME_OFFSET;
                    
                    Object.keys(trainData).forEach(id => {{
                        var t = trainData[id];
                        var marker = markers[id];
                        
                        // CHECK: If boarding/stopping, do not interpolate
                        var isBoarding = (t.state === 'BOARDING' || t.state === 'STOPPING');

                        if (!isBoarding && t.next_lat && t.next_lon && t.next_ts && t.start_ts) {{
                            var totalDuration = t.next_ts - t.start_ts;
                            var elapsed = now - t.start_ts;
                            
                            if (totalDuration > 0) {{
                                var p = elapsed / totalDuration;
                                
                                // Clamp with slight overshoot allowed (1.05) to prevent stutter
                                p = Math.max(0, Math.min(p, 1.05));
                                
                                var curLat = t.lat + (t.next_lat - t.lat) * p;
                                var curLon = t.lon + (t.next_lon - t.lon) * p;
                                marker.setLatLng([curLat, curLon]);
                            }} else {{
                                marker.setLatLng([t.next_lat, t.next_lon]);
                            }}
                        }} else {{
                            // Fallback for STATIONARY trains (Boarding or missing data)
                            marker.setLatLng([t.lat, t.lon]);
                        }}
                    }});
                    requestAnimationFrame(animate);
                }}

                setInterval(update, 1500);
                requestAnimationFrame(animate);
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
