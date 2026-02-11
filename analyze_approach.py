"""
Analyzing route_identifier from earlier debug sessions:

From our verbose logs, we saw:
- route_identifier: "6366-800725-8002980-133500"

Theory: This could be:
  Part 0: 6366 = train_number
  Part 1: 800725 = ??? (could be partial UIC or journey ID)
  Part 2: 8002980 = destination UIC (Holzkirchen)
  Part 3: 133500 = departure time (13:35:00?)

But the key question is: Does the live train data tell us CURRENT station when BOARDING?

From our timetable data, we saw:
- "at_stoppoint": 8004146  ← This is a UIC code!
- "next_stoppoints": [8004146, 8001963, ...]  ← Array of UICs

The "at_stoppoint" field appears in TIMETABLE data, but does it appear in LIVE data?

Let me check our captured train data from sbahn.py verbose runs...
"""

# S3 stations (Holzkirchen → Mammendorf)
S3_WEST = [
    ("Holzkirchen", "8002980"),
    ("Otterfing", "8004726"),
    ("Großhelfendorf", "8005299"),
    ("Deisenhofen", "8001404"),
    ("Sauerlach", "8002161"),
    ("Höllriegelskreuth", "8005831"),
    ("Pullach", "8005991"),
    ("Fasanenpark", "8001963"),
    ("Fasanerie", "8004146"),
    ("Unterhaching", "8004148"),
    ("Taufkirchen", "8004138"),
    ("Perlach", "8000262"),
    ("Neuperlach Süd", "8004136"),
    ("Ostbahnhof", "8004131"),
    ("Rosenheimer Platz", "8004135"),
    ("Isartor", "8004132"),
    ("Marienplatz", "8098263"),
    ("Karlsplatz (Stachus)", "8004129"),
    ("Hauptbahnhof", "8004128"),
    ("Hackerbrücke", "8004179"),
    ("Donnersbergerbrücke", "8004151"),
    ("Hirschgarten", "8004158"),
    ("Laim", "8004152"),
    ("Pasing", "8004153"),
    ("Leienfelsstraße", "8002377"),
    ("Langwied", "8004667"),
    ("Lochhausen", "8001996"),
    ("Gröbenzell", "8002247"),
    ("Olching", "8003824"),
    ("Maisach", "8003828"),
    ("Mammendorf", "8002533")
]

def find_station_by_uic(uic):
    """Find station name by UIC code"""
    for name, station_uic in S3_WEST:
        if station_uic == str(uic):
            return name
    return f"Unknown (UIC: {uic})"


print("Testing UIC lookup from timetable data:\n")
print(f"8004146 → {find_station_by_uic('8004146')}")  # Fasanerie
print(f"8004158 → {find_station_by_uic('8004158')}")  # Hirschgarten
print(f"8003828 → {find_station_by_uic('8003828')}")  # Maisach
print()

print("="*80)
print("PROPOSED APPROACH:")
print("="*80)
print()
print("1. Hardcode S3 station list (31 stations) ← We have this!")
print()
print("2. When tracking train, detect BOARDING state")
print()
print("3. Use GPS coordinates to find nearest station (haversine distance)")
print("   - Match current lat/lon to station coordinates")
print("   - Find index in S3_WEST list")
print()
print("4. When BOARDING → DRIVING:")
print("   - next_station = S3_WEST[current_index + 1]")
print("   - Query timetable for next_station UIC")
print("   - Get arrival time for our train_number")
print("   - Calculate duration and set speed")
print()
print("5. When DRIVING → BOARDING:")
print("   - current_index += 1")
print("   - Repeat")
print()
print("="*80)
print("ALTERNATIVE IF LIVE DATA HAS 'at_stoppoint':")
print("="*80)
print()
print("If live train.properties contains 'at_stoppoint' (UIC):")
print("  - No GPS matching needed!")
print("  - Directly look up UIC in S3_WEST")
print("  - Get index, next = index + 1")
print()
print("Need to verify: Does LIVE data (from BBOX) include at_stoppoint?")
print("We only saw it in TIMETABLE data so far.")
