"""
TCP-based output for the model train controller.

Architecture: Server runs a plain TCP server. The model controller (MicroPython
on Psoc 6) connects as a TCP client. Messages are newline-terminated text.

Protocol:
    Server → Model:  SPEED:0.50\n   |   STOP\n
    Model → Server:  HELLO:MODEL\n  |   HALL\n
    Server → Model:  ACK\n  (after HELLO)
"""

import asyncio
from outputs import ModelOutput


MODEL_TCP_PORT = 8080


class TcpModelOutput(ModelOutput):
    """Plain-TCP output for model train."""

    def __init__(self):
        self.writer: asyncio.StreamWriter | None = None
        self.connected = False

    def set_writer(self, writer: asyncio.StreamWriter):
        self.writer = writer
        self.connected = True
        print("🔌 Model train connected (TCP)")

    def disconnect(self):
        self.writer = None
        self.connected = False
        print("⚠️  Model train disconnected")

    def _do_send(self, message: str):
        """Queue a message to the model (non-blocking)."""
        if self.writer and self.connected:
            try:
                self.writer.write(message.encode())
                # drain is async; fire-and-forget from sync context
                asyncio.create_task(self.writer.drain())
            except Exception as e:
                print(f"❌ Error sending to model: {e}")
                self.connected = False

    def send_speed(self, speed: float):
        self._do_send(f"SPEED:{speed:.2f}\n")

    def send_stop(self):
        self._do_send("STOP\n")


async def tcp_model_server(model_output: TcpModelOutput, state_machine):
    """
    TCP server that accepts ONE model train connection at a time.
    The model sends newline-terminated commands; we send newline-terminated replies.
    """

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        print(f"📡 TCP connection from {peer}")
        
        PING_TIMEOUT = 15  # seconds - if no PING received, close connection
        last_ping_received = asyncio.get_running_loop().time()

        try:
            # First message must be HELLO:MODEL
            line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            hello = line.decode().strip()

            if hello != "HELLO:MODEL":
                print(f"❌ Expected HELLO:MODEL, got: {hello!r}")
                writer.write(b"ERROR:expected HELLO:MODEL\n")
                await writer.drain()
                writer.close()
                return

            # Acknowledge
            writer.write(b"ACK\n")
            await writer.drain()

            model_output.set_writer(writer)

            # Read loop — model sends HALL / PING
            while True:
                try:
                    # Check watchdog timeout
                    current_time = asyncio.get_running_loop().time()
                    if current_time - last_ping_received > PING_TIMEOUT:
                        print(f"⚠️  No PING received for {PING_TIMEOUT}s - closing connection")
                        break
                    
                    line = await asyncio.wait_for(reader.readline(), timeout=1.0)
                    if not line:
                        # Connection closed
                        break
                    msg = line.decode().strip()
                    if not msg:
                        continue

                    if msg == "HALL":
                        print("🧲 HALL sensor triggered (from model via TCP)")
                        state_machine.on_hall_sensor()
                    elif msg == "PING":
                        last_ping_received = current_time
                        writer.write(b"PONG\n")
                        await writer.drain()
                        print("📤 Sent PONG")
                    else:
                        print(f"⚠️  Unknown message from model: {msg!r}")
                        
                except asyncio.TimeoutError:
                    # No data received in 1s, continue to check watchdog
                    continue

        except asyncio.TimeoutError:
            print("❌ Model client timed out during handshake")
        except Exception as e:
            print(f"❌ TCP model error: {e}")
        finally:
            model_output.disconnect()
            try:
                writer.close()
            except:
                pass

    server = await asyncio.start_server(handle_client, "0.0.0.0", MODEL_TCP_PORT)
    print(f"🌐 TCP model server listening on 0.0.0.0:{MODEL_TCP_PORT}")
    print(f"   Model train should connect to: {MODEL_TCP_PORT}/tcp")
    print(f"   Protocol: Send 'HELLO:MODEL\\n', receive 'SPEED:x.xx\\n' or 'STOP\\n', send 'HALL\\n'")
    return server
