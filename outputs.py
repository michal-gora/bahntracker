"""
Output interfaces for model train and station display.

These are "dumb I/O" - they just forward commands.
Start with PrintStub implementations for testing, replace with WiFi/GPIO later.
"""

from abc import ABC, abstractmethod


# ── Model Train Interface ───────────────────────────────────────────────

class ModelOutput(ABC):
    """Abstract interface: Server → Model Train."""

    @abstractmethod
    def send_speed(self, speed: float):
        """Send SPEED:x command (0.0 to 1.0)."""
        ...

    @abstractmethod
    def send_stop(self):
        """Send STOP command."""
        ...


class PrintModelOutput(ModelOutput):
    """Print-stub: logs commands to console."""

    def send_speed(self, speed: float):
        pass  # State machine already prints; avoid double-logging

    def send_stop(self):
        pass  # State machine already prints


# ── Station Display Interface ───────────────────────────────────────────

class StationOutput(ABC):
    """Abstract interface: Server → Station Display."""

    @abstractmethod
    def send_station(self, name: str, valid: bool):
        """Send STATION:name:valid or STATION:name:invalid."""
        ...

    @abstractmethod
    def send_clear(self):
        """Send STATION:clear."""
        ...


class PrintStationOutput(StationOutput):
    """Print-stub: logs commands to console."""

    def send_station(self, name: str, valid: bool):
        pass  # State machine already prints

    def send_clear(self):
        pass  # State machine already prints
