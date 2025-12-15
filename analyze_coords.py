import asyncio
import json
import websockets

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"
TRAIN_ID = "sbm_140330651162704"  # Train 6398 to Mammendorf

def epsg3857_to_wgs84(x, y):
    """Convert EPSG:3857 (Web Mercator) to WGS84 (lat/lon)"""
    # EPSG:3857 uses meters, origin at equator/prime meridian
    lon = (x / 20037508.34) * 180
    lat = (y / 20037508.34) * 180
    lat = 180 / 3.141592653589793 * (2 * 3.141592653589793**((lat * 3.141592653589793) / 180) - 3.141592653589793 / 2)
    return lat, lon

def simple_mercator_to_latlon(x, y):
    """Simplified conversion assuming EPSG:3857"""
    import math
    lon = x / 111320.0  # Rough conversion
    lat = math.degrees(math.atan(math.sinh(y / 6378137.0)))  # Web Mercator formula
    return lat, lon

async def analyze_coordinates():
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        print(f"🗺️  Analyzing trajectory coordinates\n")
        
        trajectory_command = f"GET full_trajectory_{TRAIN_ID}"
        await ws.send(trajectory_command)
        
        async for msg in ws:
            if isinstance(msg, str):
                try:
                    data = json.loads(msg)
                    
                    if data.get('source', '').startswith('full_trajectory_'):
                        content = data.get('content')
                        
                        if content:
                            feature = content['features'][0]
                            coords = feature['geometry']['coordinates']
                            
                            print(f"📍 Total coordinates: {len(coords)}\n")
                            
                            # Analyze coordinate ranges
                            x_coords = [c[0] for c in coords]
                            y_coords = [c[1] for c in coords]
                            
                            print(f"📊 Raw coordinate ranges:")
                            print(f"  X: {min(x_coords):,} to {max(x_coords):,}")
                            print(f"  Y: {min(y_coords):,} to {max(y_coords):,}\n")
                            
                            # Sample coordinates (first, middle, last)
                            print(f"🔍 Sample coordinates:")
                            samples = [
                                ("First (start)", coords[0]),
                                ("Middle", coords[len(coords)//2]),
                                ("Last (end)", coords[-1])
                            ]
                            
                            print("\nRaw coordinates:")
                            for label, coord in samples:
                                print(f"  {label:15} X={coord[0]:,}  Y={coord[1]:,}")
                            
                            # Try conversion (these look like they might be in a Swiss or European projection)
                            # Common projections in Germany/Switzerland:
                            # - EPSG:31468 (Gauss-Kruger Zone 4)
                            # - EPSG:25832 (UTM Zone 32N)
                            # - EPSG:21781 (Swiss CH1903 / LV03)
                            # - EPSG:2056 (Swiss CH1903+ / LV95)
                            
                            print("\n" + "="*80)
                            print("🌍 Likely coordinate system analysis:")
                            print("="*80)
                            
                            # Check if these are Swiss LV03 or LV95 coordinates
                            first_x, first_y = coords[0]
                            
                            if 1200000 <= first_x <= 1400000 and 6000000 <= first_y <= 6200000:
                                print("\n✅ These look like EPSG:2056 (Swiss LV95) coordinates!")
                                print("   (Used in Switzerland and some border regions)")
                                print("\n   To convert to lat/lon, you can use:")
                                print("   - Website: https://epsg.io/transform")
                                print("   - Python: pyproj library")
                                print("\n   Sample conversion (approximate):")
                                # Rough approximation for Munich area in LV95-like system
                                for label, coord in samples:
                                    # Very rough estimation (this would need proper pyproj)
                                    approx_lon = 11.0 + (coord[0] - 1300000) / 100000
                                    approx_lat = 48.0 + (coord[1] - 6090000) / 111000
                                    print(f"   {label:15} ~{approx_lat:.4f}°N, {approx_lon:.4f}°E")
                                
                                print("\n   First coordinate: Copy this to test:")
                                print(f"   https://epsg.io/transform#s_srs=2056&t_srs=4326&x={first_x}&y={first_y}")
                            
                            elif 4400000 <= first_x <= 4600000 and 5200000 <= first_y <= 5400000:
                                print("\n✅ These look like UTM Zone 32N (EPSG:25832) coordinates!")
                            
                            else:
                                print(f"\n❓ Unknown projection system")
                                print(f"   X range suggests: {min(x_coords)} - {max(x_coords)}")
                                print(f"   Y range suggests: {min(y_coords)} - {max(y_coords)}")
                            
                            print("\n" + "="*80)
                            print("📝 What the coordinates represent:")
                            print("="*80)
                            print(f"   The {len(coords)} coordinate pairs define the COMPLETE ROUTE")
                            print(f"   of this train journey as a line on the map.")
                            print(f"   Each [x, y] pair is a point along the railway tracks.")
                            print(f"   Connected together, they show the exact path the train will follow.")
                            
                        return
                        
                except json.JSONDecodeError:
                    pass

if __name__ == "__main__":
    asyncio.run(analyze_coordinates())
