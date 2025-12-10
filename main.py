from mvg import MvgApi, MvgApiError, TransportType
from datetime import datetime

# S3 line stations (west to east) - exact MVG API names
S3_STATIONS = [
    "Mammendorf", "Malching", "Maisach", "Gernlinden", "Esting", "Olching",
    "Gröbenzell", "Lochhausen", "Langwied", "Pasing", "Laim", "Hirschgarten",
    "Donnersbergerbrücke", "Hackerbrücke", "Hauptbahnhof (U, Tram)", "Karlsplatz (Stachus)",
    "Marienplatz", "Isartor", "Rosenheimer Platz", "München, Ostbahnhof", "St.-Martin-Straße",
    "München, Giesing (U) (S)", "Fasangarten", "Fasanenpark", "Unterhaching", "Taufkirchen", "Furth",
    "Deisenhofen", "Sauerlach", "Otterfing", "Holzkirchen"
]

def get_lines_at_station(station_name):
    """Get all lines serving a specific station."""
    station = MvgApi.station(station_name)
    if not station:
        return []
    return MvgApi.lines(station['id'])

def main():
    station_point = "Fasanenpark"
    station1 = MvgApi.station(station_point)
    
    # Example: Get all lines at this station
    lines = get_lines_at_station(station_point)
    print(f"Lines at {station_point}: {[line['label'] for line in lines]}")

    res = "<table border='1' cellpadding='4' cellspacing='0'>"
    res += "<tr><th>Plan</th><th>Time</th><th>Delay</th><th>Line</th><th style='min-width:150px'>Destination</th><th>Departs in</th><th>Cancelled</th></tr>"

    departures = get_departures_for_station(station1['id'])
    print(departures)
    
    # Get stations before Fasanenpark on S3 line
    station_index = S3_STATIONS.index(station_point)
    stations_before_fasanenpark = S3_STATIONS[:station_index]
    # print(f"Stations before Fasanenpark on S3: {stations_before_fasanenpark}")
    for departure in departures:
        if departure['destination'] not in stations_before_fasanenpark:
            continue
        if departure['type'] != 'S-Bahn':
            continue
        minutes_until_departure = int((departure['time'] - datetime.now().timestamp()) // 60)
        dep_time = timestamp_to_time(departure['time'])
        planned_time = timestamp_to_time(departure['planned'])
        res += f"<tr><td style='text-align:center'>{planned_time}</td><td style='text-align:center'>{dep_time}</td><td style='text-align:right'>{departure['delay']}</td><td style='text-align:center'>{departure['line']}</td><td style='text-align:center'>{departure['destination']}</td><td style='text-align:right'>{minutes_until_departure} min</td><td>{departure['cancelled']}</td></tr>"
    res += "</table>"
    return res
    
def timestamp_to_time(ts):
    return datetime.fromtimestamp(ts).strftime('%H:%M')

def get_departures_for_station(station_id, limit=10):
    try:
        mvgapi = MvgApi(station_id)
        departures = mvgapi.departures(limit=limit, transport_types=[TransportType.SBAHN])
        return departures
    except MvgApiError as e:
        print(f"API error: {e}")
        return []
    except Exception as e:
        print(f"Unexpected error: {e}")
        return []


if __name__ == "__main__":
    main()