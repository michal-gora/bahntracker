import asyncio
import json
import websockets
from pyproj import Transformer

# --- CONFIGURATION ---
WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"

# Add your Train IDs here
TRAINS_TO_FETCH = [
"sbm_140265271367376", #S8
"sbm_140265145092272", #S7
"sbm_140265138485280", #S3
"sbm_140265548639776", #S8
"sbm_140265687127328", #S8
"sbm_140265159232096", #BusS2
"sbm_140265517488832", #S5
"sbm_140265788537488", #S5
"sbm_140265695328720", #S8
"sbm_140265794930240", #S7
"sbm_140265120683872", #S6
"sbm_140265151372112", #S3
"sbm_140265794772128", #S8
"sbm_140265141291520", #S5
"sbm_140265172998800", #S4
"sbm_140265169794288", #S1
"sbm_140265135343024", #S6
"sbm_140265789477264", #S2
"sbm_140265433074416", #S4
"sbm_140265143844720", #S3
"sbm_140265136771712", #S2
"sbm_140265796354832", #S3
"sbm_140265564807712", #S8
"sbm_140265695327328", #S3
"sbm_140265545463648", #S2
"sbm_140265790436064", #S1
"sbm_140265661954320", #S1
"sbm_140265552012816", #S6
"sbm_140265154069360", #S2
"sbm_140265302782208", #S3
"sbm_140265262837616", #S7
"sbm_140265159150800", #S2
"sbm_140265425544960", #S2
"sbm_140265786130336", #S7
"sbm_140265159578144", #S2
"sbm_140265543298400", #S7
"sbm_140265120514000", #S2
"sbm_140265666228384", #S6
"sbm_140265265749536", #S4
"sbm_140265796258880", #S8
"sbm_140265271578784", #S6
"sbm_140265120391808", #S7
"sbm_140265544979888", #S6
"sbm_140265146168080", #S2
"sbm_140265130038896", #S1
"sbm_140265144814224", #S1
"sbm_140265157524256", #S2
"sbm_140265787071888", #S6
"sbm_140265148772800", #S4
"sbm_140265789411680", #BusS2
]

# Create transformer from EPSG:3857 (Web Mercator) to WGS84 (lat/lon)
transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

async def fetch_all_routes():
    final_features = []
    seen_geometries = set() # Store hashes of coordinates to track duplicates
    
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print(f"🚆 Fetching {len(TRAINS_TO_FETCH)} routes...")
        print("="*60)

        for train_id in TRAINS_TO_FETCH:
            print(f"Requesting trajectory for {train_id}...", end="", flush=True)
            
            await ws.send(f"GET full_trajectory_{train_id}")
            
            # Wait for specific response
            found = False
            while not found:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    if isinstance(msg, str):
                        data = json.loads(msg)
                        if data.get('source', '') == f'full_trajectory_{train_id}':
                            content = data.get('content')
                            if content and 'features' in content:
                                feature = content['features'][0]
                                props = feature.get('properties', {})
                                geom = feature.get('geometry', {})
                                
                                # Extract metadata
                                line_name = props.get('line_name', 'Unknown')
                                line_color = props.get('stroke', '#005293') 
                                
                                # --- HANDLE GEOMETRY TYPES ---
                                geom_type = geom.get('type')
                                raw_coords = geom.get('coordinates', [])
                                
                                points_to_process = []
                                if geom_type == 'MultiLineString':
                                    for segment in raw_coords:
                                        points_to_process.extend(segment)
                                else:
                                    points_to_process = raw_coords

                                # --- TRANSFORM & FLATTEN ---
                                latlon_coords = []
                                for point in points_to_process:
                                    if len(point) >= 2:
                                        x, y = point[:2] 
                                        lon, lat = transformer.transform(x, y)
                                        latlon_coords.append((round(lon, 5), round(lat, 5))) # Use tuple for hashing
                                
                                # --- DUPLICATE CHECK ---
                                # Create a hashable signature of the route (tuple of tuples)
                                route_signature = tuple(latlon_coords)
                                
                                if route_signature in seen_geometries:
                                    print(f" ⚠️ Duplicate geometry (skipped)")
                                else:
                                    seen_geometries.add(route_signature)
                                    
                                    # Convert back to list for JSON serialization
                                    json_coords = [list(pt) for pt in latlon_coords]
                                    
                                    new_feature = {
                                        "type": "Feature",
                                        "properties": {
                                            "name": line_name,
                                            "stroke": line_color
                                        },
                                        "geometry": {
                                            "type": "LineString",
                                            "coordinates": json_coords
                                        }
                                    }
                                    
                                    final_features.append(new_feature)
                                    print(f" ✅ Got {line_name} ({len(json_coords)} points)")
                                
                                found = True
                            else:
                                print(" ❌ Empty data")
                                found = True 
                        
                except asyncio.TimeoutError:
                    print(" ⏳ Timeout")
                    found = True
                except Exception as e:
                    print(f" ⚠️ Error: {e}")
                    found = True

    # --- SAVE TO FILE ---
    print("="*60)
    
    with open("routes_compact.json", 'w') as f:
        f.write('const ROUTES_DATA = {\n"type":"FeatureCollection","features":[\n')
        for i, feature in enumerate(final_features):
            feature_str = json.dumps(feature, separators=(',', ':'))
            if i < len(final_features) - 1:
                f.write('  ' + feature_str + ',\n')
            else:
                f.write('  ' + feature_str + '\n')
        f.write(']};')
        
    print(f"💾 Saved {len(final_features)} unique routes to 'routes_compact.json'")
    print("📋 Copy the content of this file directly into your HTML 'ROUTES_DATA' variable.")

if __name__ == "__main__":
    asyncio.run(fetch_all_routes())
