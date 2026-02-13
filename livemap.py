from flask import Flask, jsonify
import folium
import json

app = Flask(__name__)
ROUTES_FILE = 'route.geojson'

LIVE_TRAINS = [
    {"id": "S1", "lat": 48.137, "lon": 11.575},
    {"id": "S8", "lat": 48.120, "lon": 11.620}
]

@app.route('/')
def map_view():
    m = folium.Map(location=[48.1351, 11.5820], zoom_start=11)
    
    # Static routes
    try:
        with open(ROUTES_FILE, 'r') as f:
            folium.GeoJson(json.load(f), name='Routes', 
                          style_function=lambda x: {'color': 'blue', 'weight': 4}).add_to(m)
    except:
        folium.PolyLine([[48.35, 11.79], [48.25, 11.64], [48.14, 11.56]],
                       color='blue', weight=5).add_to(m)

    # Static Green Circle (Hardcoded)
    folium.CircleMarker([48.1375, 11.5760], radius=8, color='green', popup='Static').add_to(m)
    
    # --- FIXED JAVASCRIPT SECTION ---
    # We get the map's auto-generated variable name
    map_var = m.get_name()
    
    m.get_root().html.add_child(folium.Element(f"""
        <script>
        document.addEventListener("DOMContentLoaded", function() {{
            setTimeout(function() {{
                var myMap = {map_var};
                var currentLayer = L.layerGroup().addTo(myMap); // Active layer

                function updateTrains() {{
                    fetch('/api/trains')
                        .then(r => r.json())
                        .then(trains => {{
                            // 1. Create NEW invisible layer
                            var newLayer = L.layerGroup();
                            
                            trains.forEach(t => {{
                                L.circleMarker([t.lat, t.lon], {{
                                    radius: 12, color: 'red', fillOpacity: 0.9
                                }}).bindPopup('S-' + t.id).addTo(newLayer);
                            }});

                            // 2. Add new layer to map (instant visible)
                            newLayer.addTo(myMap);
                            
                            // 3. Remove old layer (instant swap)
                            myMap.removeLayer(currentLayer);
                            
                            // 4. Update reference
                            currentLayer = newLayer;
                        }})
                        .catch(e => console.error("Fetch error:", e));
                }}
                
                setInterval(updateTrains, 2000);
                updateTrains();
            }}, 500);
        }});
        </script>
    """))

    
    folium.LayerControl().add_to(m)
    return m._repr_html_()

@app.route('/api/trains')
def get_trains():
    global LIVE_TRAINS
    LIVE_TRAINS[0]['lat'] += 0.001
    LIVE_TRAINS[1]['lon'] += 0.001
    
    # Loop movement
    if LIVE_TRAINS[0]['lat'] > 48.16: LIVE_TRAINS[0]['lat'] = 48.13
    if LIVE_TRAINS[1]['lon'] > 11.66: LIVE_TRAINS[1]['lon'] = 11.60
    
    return jsonify(LIVE_TRAINS)

if __name__ == '__main__':
    print("🚂 http://localhost:5000")
    app.run(debug=True, port=5000)
