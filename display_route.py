import asyncio
import json
import websockets
import sys
from pyproj import Transformer

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"
# TRAIN_ID = "sbm_140330651162704"  # Train 6398 to Mammendorf
# TRAIN_ID = "sbm_140265128772992"  # Train to Leuchtenbergring S1
# TRAIN_ID = "sbm_140265161331808" # S6 Tutzing
# TRAIN_ID = "sbm_140265140401920" # S8 Herrsching
# TRAIN_ID = "sbm_140265243803856" # S3 Maisach
# TRAIN_ID = "sbm_140265127395680"
TRAIN_ID = "sbm_140265165665952" # S5
LINE_NAME = "S5"

# Create transformer from EPSG:3857 (Web Mercator) to WGS84 (lat/lon)
transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

async def display_route():
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print(f"🚆 Train 6398 Route: Fasanenpark → Mammendorf\n")
        print("="*80)
        
        trajectory_command = f"GET full_trajectory_{TRAIN_ID}"
        await ws.send(trajectory_command)
        
        async for msg in ws:
            if isinstance(msg, str):
                try:
                    data = json.loads(msg)
                    print(json.dumps(data, indent=4))
                    if data.get('source', '').startswith('full_trajectory_'):
                        content = data.get('content')
                        
                        if content:
                            feature = content['features'][0]
                            coords = feature['geometry']['coordinates']
                            
                            print(f"\n📍 Total waypoints: {len(coords)}")
                            print(f"🗺️  Coordinate system: EPSG:3857 (Web Mercator)\n")
                            
                            # Convert all coordinates
                            latlon_coords = []
                            for x, y in coords:
                                lon, lat = transformer.transform(x, y)
                                latlon_coords.append((lat, lon))
                            
                            # Display key points
                            print("🎯 Key points along the route:")
                            print("-" * 80)
                            
                            # Start
                            lat, lon = latlon_coords[0]
                            print(f"START:  {lat:.6f}°N, {lon:.6f}°E")
                            print(f"        https://www.google.com/maps?q={lat},{lon}")
                            
                            # Every 20% of the route
                            for i in range(1, 5):
                                idx = len(latlon_coords) * i // 5
                                lat, lon = latlon_coords[idx]
                                print(f"\n{i*20:3d}%:   {lat:.6f}°N, {lon:.6f}°E")
                                print(f"        https://www.google.com/maps?q={lat},{lon}")
                            
                            # End
                            lat, lon = latlon_coords[-1]
                            print(f"\nEND:    {lat:.6f}°N, {lon:.6f}°E")
                            print(f"        https://www.google.com/maps?q={lat},{lon}")
                            
                            print("\n" + "="*80)
                            print("📊 Route statistics:")
                            print("-" * 80)
                            
                            # Calculate approximate distance
                            import math
                            total_distance = 0
                            for i in range(len(latlon_coords) - 1):
                                lat1, lon1 = latlon_coords[i]
                                lat2, lon2 = latlon_coords[i + 1]
                                
                                # Haversine formula for distance (rough)
                                dlat = math.radians(lat2 - lat1)
                                dlon = math.radians(lon2 - lon1)
                                a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
                                c = 2 * math.asin(math.sqrt(a))
                                total_distance += 6371 * c  # Earth radius in km
                            
                            print(f"  Approximate route length: {total_distance:.2f} km")
                            print(f"  Number of waypoints: {len(coords)}")
                            print(f"  Average distance between waypoints: {total_distance*1000/len(coords):.1f} meters")
                            
                            # Save to file for mapping
                            print("\n" + "="*80)
                            print("💾 Saving coordinates...")
                            
                            # Save as GeoJSON
                            geojson = {
                                "type": "FeatureCollection",
                                "features": [{
                                    "type": "Feature",
                                    "geometry": {
                                        "type": "LineString",
                                        "coordinates": [[lon, lat] for lat, lon in latlon_coords]
                                    },
                                    "properties": {
                                        # "train": "6398",
                                        # "line": "S3",
                                        # "from": "Fasanenpark",
                                        # "to": "Mammendorf"
                                        "name": LINE_NAME
                                    }
                                }]
                            }
                            
                            geojson_location = "routes_geojson"
                            csv_location = "routes_csv"

                            with open(f"{geojson_location}/route_{LINE_NAME}.geojson", 'w') as f:
                                json.dump(geojson, f, indent=2)
                            
                            print("✅ Saved to route.geojson")
                            print("   You can open this file at: https://geojson.io/")
                            
                            # Also save CSV
                            with open(f"{csv_location}/route_{LINE_NAME}.csv", 'w') as f:
                                f.write("latitude,longitude\n")
                                for lat, lon in latlon_coords:
                                    f.write(f"{lat:.6f},{lon:.6f}\n")
                            
                            print("✅ Saved to route.csv")
                            
                        return
                        
                except json.JSONDecodeError:
                    pass

if __name__ == "__main__":
    asyncio.run(display_route())
