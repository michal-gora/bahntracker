from flask import Flask, render_template_string
from mvg import MvgApi, MvgApiError
from datetime import datetime
import main

def get_departures_for_station(station_id, limit=5):
    try:
        mvgapi = MvgApi(station_id)
        departures = mvgapi.departures(limit=limit)
        return departures
    except MvgApiError as e:
        print(f"API error: {e}")
        return []
    except Exception as e:
        print(f"Unexpected error: {e}")
        return []

app = Flask(__name__)

@app.route('/')
def index():
    # station1 = MvgApi.station("Fasanenpark")
    # departures = get_departures_for_station(station1['id'])
    # filtered = []
    # for departure in departures:
    #     if departure['destination'] not in ("Holzkirchen", "Deisenhofen"):
    #         continue
    #     ts = departure['time']
    #     if ts > 1e12:
    #         ts = ts // 1000
    #     dep_time = datetime.fromtimestamp(ts).strftime('%H:%M')
    #     filtered.append({
    #         'line': departure['line'],
    #         'destination': departure['destination'],
    #         'time': dep_time
    #     })
    # html = '''
    # <h1>Departures to Holzkirchen or Deisenhofen</h1>
    # <ul>
    # {% for dep in departures %}
    #   <li>Line: {{ dep.line }}, Destination: {{ dep.destination }}, Departure Time: {{ dep.time }}</li>
    # {% endfor %}
    # </ul>
    # '''
    # return render_template_string(html, departures=filtered)

    
    content = main.main()
    html = f"""
    <html>
    <head>
        <meta http-equiv='refresh' content='10'>
        <title>Departures</title>
    </head>
    <body>
    {content}
    </body>
    </html>
    """
    return html

if __name__ == "__main__":
    app.run(debug=True)
