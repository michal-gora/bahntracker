"""
Test WebSocket client to simulate the model train.

Usage: python test_model_client.py [server_ip]
Default server: localhost:8765
"""

import asyncio
import sys
import websockets


async def model_client(server_ip="localhost", port=8765):
    """Connect to server as model train via WebSocket."""
    uri = f"ws://{server_ip}:{port}"
    print(f"🔌 Connecting to {uri}...")

    async with websockets.connect(uri) as websocket:
        # Identify as model
        await websocket.send("HELLO:MODEL")
        print("→ Sent: HELLO:MODEL")

        # Wait for ACK
        response = await websocket.recv()
        print(f"← Received: {response}")

        if response != "ACK":
            print(f"❌ Expected ACK, got: {response}")
            return

        print("✅ Connection established!")
        print("\nListening for commands from server...")
        print("Type h + Enter to send HALL sensor event")
        print("Type q + Enter to quit\n")

        async def listen_server():
            try:
                async for message in websocket:
                    print(f"← Received: {message}")
                    if message.startswith("SPEED:"):
                        speed = float(message.split(":")[1])
                        print(f"   🚂 Setting speed to {speed:.2f}")
                    elif message == "STOP":
                        print(f"   🛑 Stopping motor")
            except Exception as e:
                print(f"[Server connection closed: {e}]")

        async def listen_stdin():
            loop = asyncio.get_event_loop()
            while True:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                cmd = line.strip().lower()
                if cmd == "h":
                    await websocket.send("HALL")
                    print("→ Sent: HALL")
                elif cmd == "q":
                    print("Quitting...")
                    await websocket.close()
                    break

        await asyncio.gather(listen_server(), listen_stdin())


if __name__ == "__main__":
    server_ip = sys.argv[1] if len(sys.argv) > 1 else "localhost"

    try:
        asyncio.run(model_client(server_ip))
    except KeyboardInterrupt:
        print("\nDisconnected.")
