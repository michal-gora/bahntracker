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

## Architecture: ONE State Machine on Server

```
                          ┌──────────────────────────────────────────────────┐
                          │   Server (Raspberry Pi / Computer)               │
                          │                                                  │
  ┌─────────────┐        │   ┌────────────────────────────────────────┐     │
  │ geops.io    │◀───────▶│   │  ONE State Machine (6 states)          │     │
  │ WebSocket   │  input  │   │  All decision logic lives here         │     │
  └─────────────┘        │   └───────┬──────────────────┬─────────────┘     │
                          │           │                  │                    │
                          │     ┌─────┴─────┐      ┌────┴─────┐             │
                          │     │  Model    │      │ Station  │             │
                          │     │  output + │      │  output  │             │
                          │     │  input    │      │  only    │             │
                          │     └─────┬─────┘      └────┬─────┘             │
                          └───────────┼─────────────────┼────────────────────┘
                                      │                 │
                              WiFi/WS │                 │ GPIO or WiFi/WS
                                      │                 │
                          ┌───────────┴─────┐    ┌─────┴──────────────┐
                          │  Model Train    │    │  Station Display   │
                          │  (dumb I/O)     │    │  (dumb I/O)        │
                          │                 │    │                    │
                          │  Receives:      │    │  Receives:         │
                          │  SPEED:0.5      │    │  STATION:name:valid│
                          │  STOP           │    │  STATION:name:invalid│
                          │                 │    │  STATION:clear     │
                          │  Sends:         │    │                    │
                          │  HALL           │    │                    │
                          │                 │    │  Controls:         │
                          │  Local safety:  │    │  - LCD display     │
                          │  HALL → stop    │    │  - Validity LED    │
                          │  motor, then    │    │                    │
                          │  report to      │    │                    │
                          │  server         │    │                    │
                          └─────────────────┘    └────────────────────┘
```

### Communication Protocols

#### Server → Model Train

| Command | Meaning |
|---------|---------|
| `SPEED:0.42` | Set motor speed (0.0-1.0) |
| `STOP` | Stop motor |

#### Model Train → Server

| Message | Meaning |
|---------|---------|
| `HALL` | Hall sensor triggered (arrived at station) |

#### Server → Station Display

| Command | Meaning | Example |
|---------|---------|---------|
| `STATION:name:valid` | Show station, validity ON | `STATION:Fasanenpark:valid` |
| `STATION:name:invalid` | Show station, validity OFF | `STATION:Fasanenpark:invalid` |
| `STATION:clear` | Clear display, everything OFF | `STATION:clear` |

---

## The ONE State Machine (6-State Moore, on Server)

### Inputs

| Input | Source | Values |
|-------|--------|--------|
| Real train state change | geops.io API | BOARDING, DRIVING |
| Real train coordinates | geops.io API | [lon, lat] |
| Hall sensor trigger | Model train (WiFi) | HALL |

### State Outputs (applied once on entry)

| State | → Model | → Station | Notes |
|-------|---------|-----------|-------|
| WAITING_AT_NONAME | STOP | STATION:clear | Waiting for sync |
| AT_STATION_VALID | STOP | STATION:name:valid | Real train boarding |
| AT_STATION_WAITING | STOP | STATION:name:invalid | Model early, real still driving |
| DRIVING | SPEED:x | STATION:name:invalid | Normal driving |
| DRIVING_TO_NONAME | SPEED:x | STATION:clear | Last leg after Fasanenpark |
| RUNNING_TO_STATION | SPEED:1.0 | STATION:name:invalid | Catch-up mode |

### State Transitions

| Current State | Trigger | Next State |
|---------------|---------|------------|
| WAITING_AT_NONAME | API: BOARDING | AT_STATION_VALID |
| AT_STATION_VALID | API: DRIVING (not Fasanenpark) | DRIVING |
| AT_STATION_VALID | API: DRIVING (is Fasanenpark) | DRIVING_TO_NONAME |
| DRIVING | HALL + last API was BOARDING | AT_STATION_VALID |
| DRIVING | HALL + last API was DRIVING | AT_STATION_WAITING |
| DRIVING | API: BOARDING (no HALL yet) | RUNNING_TO_STATION |
| DRIVING_TO_NONAME | HALL | WAITING_AT_NONAME |
| AT_STATION_WAITING | API: BOARDING | AT_STATION_VALID |
| RUNNING_TO_STATION | HALL | AT_STATION_VALID |

### Entry Actions (data processing)

| Entering State | From | Actions |
|----------------|------|---------|
| AT_STATION_VALID | WAITING_AT_NONAME | Find nearest station by GPS → set current_station_index |
| AT_STATION_VALID | DRIVING, RUNNING_TO_STATION | Increment current_station_index |
| AT_STATION_VALID | AT_STATION_WAITING | (index already correct) |
| DRIVING | AT_STATION_VALID | Calculate speed from travel_times[current_station] |
| DRIVING_TO_NONAME | AT_STATION_VALID | Calculate speed (Fasanenpark → noname) |
| WAITING_AT_NONAME | DRIVING_TO_NONAME | Reset current_station_index = None |

### Server Variables

| Variable | Type | Purpose |
|----------|------|---------|
| `state` | enum | Current state machine state |
| `current_station_index` | int/None | Index in station list |
| `last_api_state` | str | Last real train state (BOARDING/DRIVING) |
| `stations` | list | Loaded from travel_times.json |

---

## Implementation Steps

### Step 1: Server (sbahn.py)
1. Connect to geops.io WebSocket
2. Track train going to Mammendorf/Maisach
3. Load travel_times.json
4. State machine processes API events + HALL events
5. Sends commands to model (SPEED/STOP) and station (STATION)
6. Model/station interfaces are pluggable (print stubs first, WiFi later, GPIO optional)

### Step 2: Model Train firmware (ESP32/similar)
1. WebSocket client (connect to server)
2. On `SPEED:x` → set motor PWM
3. On `STOP` → stop motor
4. On hall sensor GPIO → stop motor immediately, send `HALL` to server
5. No state machine, no logic

### Step 3: Station Display firmware (ESP32 or GPIO on same Pi)
1. On `STATION:name:valid` → display name, green LED on
2. On `STATION:name:invalid` → display name, green LED off
3. On `STATION:clear` → clear display, all LEDs off
4. No state machine, no logic

### Step 4: Testing
1. Run server with print stubs (no hardware)
2. Simulate HALL events via keyboard or timer
3. Verify state transitions
4. Add real hardware

---

## Files

| File | Location | Purpose |
|------|----------|---------|
| `travel_times.json` | Server | Station travel times |
| `generate_travel_times.py` | Server | Regenerate travel times from API |
| `sbahn.py` | Server | geops.io + state machine + command sender |
| `model_firmware/` | Model | ESP32 firmware (dumb I/O) |
| `station_firmware/` | Station | ESP32 firmware or GPIO script (dumb I/O) |

---

## Next Action

Start implementing the server (sbahn.py refactor)?
