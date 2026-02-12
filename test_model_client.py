"""
Test TCP client to simulate the model train.

Usage: python test_model_client.py [server_ip]
Default server: localhost:8766
"""

import asyncio
import sys


async def model_client(server_ip="localhost", port=8766):
    """Connect to server as model train via plain TCP."""
    print(f"🔌 Connecting to {server_ip}:{port} (TCP)...")

    reader, writer = await asyncio.open_connection(server_ip, port)
    print("✅ TCP connected")

    # Identify as model
    writer.write(b"HELLO:MODEL\n")
    await writer.drain()
    print("→ Sent: HELLO:MODEL")

    # Wait for ACK
    response = await reader.readline()
    resp = response.decode().strip()
    print(f"← Received: {resp}")

    if resp != "ACK":
        print(f"❌ Expected ACK, got: {resp}")
        writer.close()
        return

    print("✅ Connection established!")
    print("\nListening for commands from server...")
    print("Type h + Enter to send HALL sensor event")
    print("Type q + Enter to quit\n")

    async def listen_server():
        try:
            while True:
                line = await reader.readline()
                if not line:
                    print("[Server closed connection]")
                    break
                msg = line.decode().strip()
                if not msg:
                    continue
                print(f"← Received: {msg}")
                if msg.startswith("SPEED:"):
                    speed = float(msg.split(":")[1])
                    print(f"   🚂 Setting speed to {speed:.2f}")
                elif msg == "STOP":
                    print(f"   🛑 Stopping motor")
        except Exception as e:
            print(f"[Server connection closed: {e}]")

    async def listen_stdin():
        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            cmd = line.strip().lower()
            if cmd == "h":
                writer.write(b"HALL\n")
                await writer.drain()
                print("→ Sent: HALL")
            elif cmd == "q":
                print("Quitting...")
                writer.close()
                break

    await asyncio.gather(listen_server(), listen_stdin())


if __name__ == "__main__":
    server_ip = sys.argv[1] if len(sys.argv) > 1 else "localhost"

    try:
        asyncio.run(model_client(server_ip))
    except KeyboardInterrupt:
        print("\nDisconnected.")
