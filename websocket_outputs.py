"""
WebSocket-based output implementations for model train and station display.

Architecture: Server acts as WebSocket server, model/station connect as clients.
"""

import asyncio
import json
from outputs import ModelOutput, StationOutput


class WebSocketModelOutput(ModelOutput):
    """WebSocket output for model train (server mode)."""

    def __init__(self):
        self.websocket = None
        self.connected = False

    def set_websocket(self, ws):
        """Called when model connects."""
        self.websocket = ws
        self.connected = True
        print("🔌 Model train connected")

    def disconnect(self):
        """Called when model disconnects."""
        self.websocket = None
        self.connected = False
        print("⚠️  Model train disconnected")

    async def _send(self, message: str):
        """Send message to model if connected."""
        if self.websocket and self.connected:
            try:
                await self.websocket.send(message)
            except Exception as e:
                print(f"❌ Error sending to model: {e}")
                self.connected = False

    def send_speed(self, speed: float):
        """Send SPEED:x command (0.0 to 1.0)."""
        if self.websocket:
            asyncio.create_task(self._send(f"SPEED:{speed:.2f}\n"))
        # Still print for debugging
        # print(f"   → Model: SPEED:{speed:.2f}")

    def send_stop(self):
        """Send STOP command."""
        if self.websocket:
            asyncio.create_task(self._send("STOP\n"))
        # Still print for debugging
        # print(f"   → Model: STOP")


class WebSocketStationOutput(StationOutput):
    """WebSocket output for station display (server mode)."""

    def __init__(self):
        self.websocket = None
        self.connected = False

    def set_websocket(self, ws):
        """Called when station connects."""
        self.websocket = ws
        self.connected = True
        print("🔌 Station display connected")

    def disconnect(self):
        """Called when station disconnects."""
        self.websocket = None
        self.connected = False
        print("⚠️  Station display disconnected")

    async def _send(self, message: str):
        """Send message to station if connected."""
        if self.websocket and self.connected:
            try:
                await self.websocket.send(message)
            except Exception as e:
                print(f"❌ Error sending to station: {e}")
                self.connected = False

    def send_station(self, name: str, valid: bool):
        """Send STATION:name:valid or STATION:name:invalid."""
        validity = "valid" if valid else "invalid"
        if self.websocket:
            asyncio.create_task(self._send(f"STATION:{name}:{validity}\n"))
        # Still print for debugging
        # print(f"   → Station: {name} {'✅' if valid else '❌'}")

    def send_clear(self):
        """Send STATION:clear."""
        if self.websocket:
            asyncio.create_task(self._send("STATION:clear\n"))
        # Still print for debugging
        # print(f"   → Station: clear")


async def websocket_server_handler(websocket, path, model_output: WebSocketModelOutput, 
                                   station_output: WebSocketStationOutput, state_machine):
    """
    Handle WebSocket connections from model train and station display.
    
    Protocol identification:
    - Model sends: HELLO:MODEL
    - Station sends: HELLO:STATION
    - Model sends: HALL (when sensor triggers)
    """
    client_type = None
    
    try:
        # Wait for identification
        async for message in websocket:
            msg = message.strip()
            
            # Identify client type
            if msg.startswith("HELLO:"):
                client_type = msg.split(":")[1]
                if client_type == "MODEL":
                    model_output.set_websocket(websocket)
                    await websocket.send("ACK\n")
                elif client_type == "STATION":
                    station_output.set_websocket(websocket)
                    await websocket.send("ACK\n")
                continue
            
            # Handle messages from identified clients
            if client_type == "MODEL":
                if msg == "HALL":
                    print(f"🧲 HALL sensor triggered (from model via WebSocket)")
                    state_machine.on_hall_sensor()
            
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
    finally:
        # Cleanup on disconnect
        if client_type == "MODEL":
            model_output.disconnect()
        elif client_type == "STATION":
            station_output.disconnect()
