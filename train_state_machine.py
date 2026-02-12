"""
6-State Moore State Machine for Model Train Synchronization.

All decision logic lives here. The server feeds inputs (API events, HALL sensor)
and reads outputs (commands for model train and station display).

States:
    WAITING_AT_NONAME    - Model parked at noname, waiting for real train to board
    AT_STATION_VALID     - Model at station, real train is boarding (validity ON)
    AT_STATION_WAITING   - Model at station, real train still driving (validity OFF)
    DRIVING              - Model driving between stations
    DRIVING_TO_NONAME    - Model driving from Fasanenpark back to noname
    RUNNING_TO_STATION   - Model catching up at full speed (it's late)
"""

import json
import math
from enum import Enum, auto
from datetime import datetime


class State(Enum):
    WAITING_AT_NONAME = auto()
    AT_STATION_VALID = auto()
    AT_STATION_WAITING = auto()
    DRIVING = auto()
    DRIVING_TO_NONAME = auto()
    RUNNING_TO_STATION = auto()


class TrainStateMachine:
    """ONE state machine that controls both model train and station display."""

    TRACK_LOOP_SECONDS = 10.0   # Time for model to go one station at full speed (calibrate!)
    NONAME_TRAVEL_SECONDS = 8.0  # Time from Fasanenpark to noname (calibrate!)
    MIN_SPEED = 0.01
    MAX_SPEED = 1.0

    def __init__(self, model_output, station_output, stations: list):
        """
        Args:
            model_output:   Object with send_speed(float) and send_stop() methods
            station_output: Object with send_station(name, valid) and send_clear() methods
            stations:       List of station dicts from travel_times.json
        """
        self.model = model_output
        self.station = station_output
        self.stations = stations

        # State variables
        self.state: State = State.WAITING_AT_NONAME
        self.current_station_index: int | None = None
        self.last_api_state: str | None = None  # "BOARDING" or "DRIVING"
        self.travel_speed: float = 0.0

        # Apply initial state outputs
        self._apply_outputs()

    # ── Public API: feed events ─────────────────────────────────────────

    def on_api_state_change(self, new_api_state: str, coordinates: list | None = None):
        """Called when the real train changes state (BOARDING / DRIVING).

        Args:
            new_api_state:  "BOARDING" or "DRIVING"
            coordinates:    [lon, lat] from geops.io (EPSG:4326 already converted)
        """
        old_state = self.state
        old_api = self.last_api_state
        self.last_api_state = new_api_state

        new_state = self._transition_on_api(new_api_state, coordinates)
        if new_state and new_state != old_state:
            self._enter_state(new_state, from_state=old_state, coordinates=coordinates)

    def on_hall_sensor(self):
        """Called when the model train's hall sensor triggers (arrived at a station)."""
        old_state = self.state
        new_state = self._transition_on_hall()
        if new_state and new_state != old_state:
            self._enter_state(new_state, from_state=old_state)

    # ── Transition logic ────────────────────────────────────────────────

    def _transition_on_api(self, api_state: str, coordinates: list | None) -> State | None:
        """Determine next state based on API event. Returns None if no transition."""
        s = self.state

        if s == State.WAITING_AT_NONAME:
            if api_state == "BOARDING":
                return State.AT_STATION_VALID

        elif s == State.AT_STATION_VALID:
            if api_state == "DRIVING":
                if self._is_fasanenpark():
                    return State.DRIVING_TO_NONAME
                else:
                    return State.DRIVING

        elif s == State.DRIVING:
            if api_state == "BOARDING":
                # Real train started boarding but model hasn't arrived yet → catch up!
                return State.RUNNING_TO_STATION

        elif s == State.AT_STATION_WAITING:
            if api_state == "BOARDING":
                return State.AT_STATION_VALID

        elif s == State.RUNNING_TO_STATION:
            if api_state == "DRIVING":
                # Real train departed before we arrived
                if self._is_fasanenpark():
                    return State.DRIVING_TO_NONAME
                else:
                    return State.DRIVING

        # No transition for: DRIVING_TO_NONAME (waits for HALL)
        return None

    def _transition_on_hall(self) -> State | None:
        """Determine next state based on HALL sensor. Returns None if no transition."""
        s = self.state

        if s == State.DRIVING:
            if self.last_api_state == "BOARDING":
                return State.AT_STATION_VALID
            else:  # last_api_state == "DRIVING"
                return State.AT_STATION_WAITING

        elif s == State.DRIVING_TO_NONAME:
            return State.WAITING_AT_NONAME

        elif s == State.RUNNING_TO_STATION:
            # If HALL triggers while still in RUNNING_TO_STATION, real train must still be boarding
            # (if it departed, we'd already be in DRIVING state via API transition)
            return State.AT_STATION_VALID

        # No transition for: WAITING_AT_NONAME (model parked), AT_STATION_* (model stopped)
        return None

    # ── Entry actions ───────────────────────────────────────────────────

    def _enter_state(self, new_state: State, from_state: State, coordinates: list | None = None):
        """Execute entry actions and apply outputs for the new state."""
        now = datetime.now().strftime('%H:%M:%S')

        # ── Data processing (entry actions) ──
        if new_state == State.AT_STATION_VALID:
            if from_state == State.WAITING_AT_NONAME:
                # First sync: find nearest station by GPS
                if coordinates:
                    idx = self._find_nearest_station(coordinates)
                    self.current_station_index = idx
                    print(f"[{now}] 📍 Synced to station: {self.stations[idx]['name']} (index {idx})")
                else:
                    # Fallback: first station
                    self.current_station_index = 0
                    print(f"[{now}] ⚠️  No GPS, defaulting to first station: {self.stations[0]['name']}")
            # from DRIVING/RUNNING_TO_STATION/AT_STATION_WAITING: index already correct (already pointing to this station)

        elif new_state == State.DRIVING:
            # Departing: increment index to point to our destination (next station)
            if self.current_station_index is not None:
                self.current_station_index += 1
                if self.current_station_index >= len(self.stations):
                    self.current_station_index = len(self.stations) - 1
                    print(f"[{now}] ⚠️  Station index overflow, clamped to last station")
            # Calculate speed from travel time
            self.travel_speed = self._calculate_speed()

        elif new_state == State.DRIVING_TO_NONAME:
            # Fixed speed for return to noname
            self.travel_speed = self._calculate_speed_for_time(self.NONAME_TRAVEL_SECONDS)

        elif new_state == State.WAITING_AT_NONAME:
            self.current_station_index = None
            self.last_api_state = None

        # ── State transition ──
        old_name = self.state.name
        self.state = new_state

        print(f"[{now}] 🔄 {old_name} → {new_state.name}")

        # ── Apply Moore outputs ──
        self._apply_outputs()

    def _apply_outputs(self):
        """Apply outputs for current state (Moore: outputs depend only on state)."""
        s = self.state
        now = datetime.now().strftime('%H:%M:%S')

        if s == State.WAITING_AT_NONAME:
            self.model.send_stop()
            self.station.send_clear()
            print(f"[{now}]   → Model: STOP | Station: clear")

        elif s == State.AT_STATION_VALID:
            self.model.send_stop()
            name = self._current_station_name()
            self.station.send_station(name, valid=True)
            print(f"[{now}]   → Model: STOP | Station: {name} ✅")

        elif s == State.AT_STATION_WAITING:
            self.model.send_stop()
            name = self._current_station_name()
            self.station.send_station(name, valid=False)
            print(f"[{now}]   → Model: STOP | Station: {name} ❌ (waiting)")

        elif s == State.DRIVING:
            self.model.send_speed(self.travel_speed)
            name = self._current_station_name()  # current_station_index IS our destination after increment
            self.station.send_station(name, valid=False)
            print(f"[{now}]   → Model: SPEED:{self.travel_speed:.2f} | Station: → {name}")

        elif s == State.DRIVING_TO_NONAME:
            self.model.send_speed(self.travel_speed)
            self.station.send_clear()
            print(f"[{now}]   → Model: SPEED:{self.travel_speed:.2f} | Station: clear (→ noname)")

        elif s == State.RUNNING_TO_STATION:
            self.model.send_speed(self.MAX_SPEED)
            name = self._current_station_name()  # current_station_index IS our destination after increment
            self.station.send_station(name, valid=False)
            print(f"[{now}]   → Model: SPEED:1.0 (catch-up!) | Station: → {name}")

    # ── Helpers ─────────────────────────────────────────────────────────

    def _is_fasanenpark(self) -> bool:
        """Check if we're currently at the last station (Fasanenpark)."""
        if self.current_station_index is None:
            return False
        return self.current_station_index >= len(self.stations) - 1

    def _current_station_name(self) -> str:
        if self.current_station_index is not None and self.current_station_index < len(self.stations):
            return self.stations[self.current_station_index]['name']
        return "???"

    def _next_station_name(self) -> str:
        if self.current_station_index is not None:
            nxt = self.current_station_index + 1
            if nxt < len(self.stations):
                return self.stations[nxt]['name']
        return "noname"

    def _calculate_speed(self) -> float:
        """Calculate model speed from travel_times for the current station segment."""
        if self.current_station_index is None:
            return self.MIN_SPEED
        station = self.stations[self.current_station_index]
        travel_time = station.get('travel_time_to_next')
        if not travel_time or travel_time <= 0:
            return self.MIN_SPEED
        return self._calculate_speed_for_time(travel_time)

    def _calculate_speed_for_time(self, seconds: float) -> float:
        """speed = TRACK_LOOP_SECONDS / travel_time, clamped to [MIN, MAX]."""
        speed = self.TRACK_LOOP_SECONDS / seconds
        return max(self.MIN_SPEED, min(self.MAX_SPEED, speed))

    def _find_nearest_station(self, coordinates: list) -> int:
        """Find the station closest to the given [lon, lat] coordinates."""
        if not coordinates or len(coordinates) < 2:
            return 0

        lon, lat = coordinates[0], coordinates[1]
        best_idx = 0
        best_dist = float('inf')

        for i, station in enumerate(self.stations):
            slat = station.get('lat', 0)
            slon = station.get('lon', 0)
            dist = self._haversine(lat, lon, slat, slon)
            if dist < best_dist:
                best_dist = dist
                best_idx = i

        return best_idx

    @staticmethod
    def _haversine(lat1, lon1, lat2, lon2) -> float:
        """Distance in meters between two lat/lon points."""
        R = 6371000
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    # ── Status ──────────────────────────────────────────────────────────

    def status(self) -> str:
        """Human-readable status string."""
        if self.state in (State.DRIVING, State.DRIVING_TO_NONAME, State.RUNNING_TO_STATION):
            station = f"{self._current_station_name()} → {self._next_station_name()}"
        elif self.current_station_index is not None:
            station = self._current_station_name()
        else:
            station = "none"
        return (
            f"State: {self.state.name} | Station: {station} "
            f"(idx={self.current_station_index}) | API: {self.last_api_state} | Speed: {self.travel_speed:.2f}"
        )
