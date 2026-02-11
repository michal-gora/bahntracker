# Model Train Control - Implementation Plan
## Project Goal
Synchronize a physical model train with real S-Bahn trains going to Mammendorf/Maisach

---

## What We Have

### 1. Travel Times (Calculated from API ✅)
```
Holzkirchen → Otterfing:        240s (4 min)
Otterfing → Großhelfendorf:     300s (5 min)
Großhelfendorf → Deisenhofen:   360s (6 min)
Deisenhofen → Sauerlach:        120s (2 min)
Sauerlach → Höllriegelskreuth:  180s (3 min)
Höllriegelskreuth → Pullach:    120s (2 min)
Pullach → Fasanenpark:          120s (2 min)
```
Stored in: `travel_times.json`

### 2. API Capabilities
- Live train state: BOARDING / DRIVING
- Live coordinates: `raw_coordinates` [lon, lat]
- No arrival times (only departure times)

---

## The Plan

### Model Train States (6 states)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  ┌──────────────────┐                                                       │
│  │ WAITING_AT_NONAME│◀────────────────────────────────────────────────┐     │
│  └────────┬─────────┘                                                 │     │
│           │                                                           │     │
│           │ (real train BOARDING, find station)                       │     │
│           ▼                                                           │     │
│  ┌──────────────────┐                                                 │     │
│  │ AT_STATION_VALID │◀───────────────────────┐                        │     │
│  │  (validity ON)   │                        │                        │     │
│  └────────┬─────────┘                        │                        │     │
│           │                                  │                        │     │
│           │ (real train DRIVING)             │                        │     │
│           │                                  │                        │     │
│           ├───────────────────────┐          │                        │     │
│           │                       │          │                        │     │
│           │ (NOT Fasanenpark)     │ (IS Fasanenpark)                  │     │
│           ▼                       ▼          │                        │     │
│  ┌──────────────────┐   ┌──────────────────┐ │                        │     │
│  │     DRIVING      │   │DRIVING_TO_NONAME │ │                        │     │
│  │  (normal speed)  │   │  (normal speed)  │ │                        │     │
│  └────────┬─────────┘   └────────┬─────────┘ │                        │     │
│           │                      │           │                        │     │
│           │                      │ (model arrives at noname)          │     │
│           │                      └────────────────────────────────────┘     │
│           │                                                                 │
│           │ (model arrives at station - hall sensor)                        │
│           │                                                                 │
│           ├────────────────────────┬────────────────────────────────────┐   │
│           │                        │                                    │   │
│           │ (real BOARDING)        │ (real still DRIVING)               │   │
│           │                        ▼                                    │   │
│           │               ┌──────────────────┐                          │   │
│           │               │AT_STATION_WAITING│                          │   │
│           │               │  (validity OFF)  │                          │   │
│           │               └────────┬─────────┘                          │   │
│           │                        │                                    │   │
│           │                        │ (real BOARDING)                    │   │
│           │                        │                                    │   │
│           └───────────────────────►├◀───────────────────────────────────┘   │
│                                    │                                        │
│                                    │                                        │
│  ┌──────────────────┐              │                                        │
│  │RUNNING_TO_STATION│◀─────────────┼────────────────────────────────────┐   │
│  │   (FULL SPEED)   │──────────────┘                                    │   │
│  └──────────────────┘  (model arrives)                                  │   │
│           ▲                                                             │   │
│           │                                                             │   │
│           │ (while DRIVING, real switches to BOARDING = model late!)   │   │
│           └─────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Moore State Machine

#### State Outputs (Applied when entering state)

| State | Speed | Validity LED | Display | Notes |
|-------|-------|--------------|---------|-------|
| WAITING_AT_NONAME | 0 | OFF | "---" | Waiting for sync |
| AT_STATION_VALID | 0 | ON | current_station | Valid boarding state |
| AT_STATION_WAITING | 0 | OFF | current_station | Model early, waiting for real train |
| DRIVING | travel_speed | OFF | next_station | Normal driving |
| DRIVING_TO_NONAME | travel_speed | OFF | "→ noname" | Last leg to noname |
| RUNNING_TO_STATION | 1.0 (FULL) | OFF | next_station | Catch-up mode |

#### State Transitions

| Current State | Trigger | Next State |
|---------------|---------|------------|
| WAITING_AT_NONAME | Real BOARDING | AT_STATION_VALID |
| AT_STATION_VALID | Real DRIVING + NOT Fasanenpark | DRIVING |
| AT_STATION_VALID | Real DRIVING + IS Fasanenpark | DRIVING_TO_NONAME |
| DRIVING | Hall sensor + Real BOARDING | AT_STATION_VALID |
| DRIVING | Hall sensor + Real DRIVING | AT_STATION_WAITING |
| DRIVING | Real BOARDING (no hall yet) | RUNNING_TO_STATION |
| DRIVING_TO_NONAME | Hall sensor | WAITING_AT_NONAME |
| AT_STATION_WAITING | Real BOARDING | AT_STATION_VALID |
| RUNNING_TO_STATION | Hall sensor | AT_STATION_VALID |

#### Entry Actions (Data processing on state entry)

| Entering State | From Any State | Actions |
|----------------|----------------|---------|
| AT_STATION_VALID | WAITING_AT_NONAME | Find nearest station by GPS → set current_station_index |
| AT_STATION_VALID | DRIVING, RUNNING_TO_STATION | Increment current_station_index |
| DRIVING | AT_STATION_VALID | Calculate travel_speed from travel_times[current_station] |
| DRIVING_TO_NONAME | AT_STATION_VALID | Set travelspeed to specified return-to-noname constant |
| WAITING_AT_NONAME | DRIVING_TO_NONAME | Reset current_station_index = None |

---

## Implementation Steps

### Step 1: Clean up sbahn.py
- Remove old segment-based logic
- Keep only: WebSocket connection, state tracking, keepalive

### Step 2: Create model_controller.py
```python
class ModelTrainController:
    def __init__(self, travel_times_file='travel_times.json'):
        self.load_travel_times()
        self.state = ModelState.WAITING_AT_NONAME
        self.current_station_index = None
        
    def on_real_train_update(self, real_state, real_coords):
        # State machine logic here
        pass
```

### Step 3: Create main tracking loop
```python
async def track_train(ws, train_number, controller):
    while True:
        train_data = await get_next_train_update(ws, train_number)
        state = train_data['properties']['state']
        coords = train_data['properties']['raw_coordinates']
        
        controller.on_real_train_update(state, coords)
```

---

## Files

| File | Purpose |
|------|---------|
| `travel_times.json` | Hardcoded station travel times |
| `generate_travel_times.py` | Script to regenerate travel times |
| `model_controller.py` | Model train state machine |
| `sbahn.py` | WebSocket connection & train tracking |
| `main.py` | Entry point |

---

## Next Action

Start implementing `model_controller.py` with the state machine?
