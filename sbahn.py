import asyncio
import json
import os
import signal
from datetime import datetime

import websockets

WS_URL = "wss://api.geops.io/realtime-ws/v1/?key=5cc87b12d7c5370001c1d655112ec5c21e0f441792cfc2fafe3e7a1e"


async def consume_realtime(url: str):
    """Connect to the geops realtime websocket and print received messages.

    Since the message format is unknown, this logs:
    - message type (text/binary)
    - first 500 chars of payload
    - attempts JSON parsing if payload looks like JSON
    """
    async with websockets.connect(url, max_size=10 * 1024 * 1024) as ws:
        print(f"[{datetime.now().isoformat()}] Connected to {url}")

        # Send timetable query for Fasanenpark
        # Try both UIC codes - 8001963 (from documentation) and 624435 (from GET station response)
        test_command = "GET timetable_8001963"
        await ws.send(test_command)
        print(f"[{datetime.now().isoformat()}] Sent: {test_command}")

        try:
            async for msg in ws:
                ts = datetime.now().isoformat()
                if isinstance(msg, (bytes, bytearray)):
                    preview = msg[:500]
                    print(f"[{ts}] binary {len(msg)} bytes; preview={preview!r}")
                else:
                    text = msg
                    preview = text[:500]
                    print(f"[{ts}] text len={len(text)}; preview=\n{preview}")
                    # Try to parse JSON safely
                    if preview.strip().startswith("{") or preview.strip().startswith("["):
                        try:
                            obj = json.loads(text)
                            # Print concise structure info
                            if isinstance(obj, dict):
                                keys = list(obj.keys())[:10]
                                print(f"[{ts}] json object keys={keys}")
                            elif isinstance(obj, list):
                                print(f"[{ts}] json array size={len(obj)}; first item type={type(obj[0]).__name__ if obj else 'n/a'}")
                        except Exception as e:
                            print(f"[{ts}] json parse error: {e}")
        except websockets.ConnectionClosedOK:
            print(f"[{datetime.now().isoformat()}] Connection closed OK")
        except websockets.ConnectionClosedError as e:
            print(f"[{datetime.now().isoformat()}] Connection closed with error: {e}")


def main():
    loop = asyncio.get_event_loop()

    # Graceful shutdown on Ctrl+C
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, loop.stop)
        except NotImplementedError:
            # Signals may not be supported (e.g., on Windows)
            pass

    try:
        loop.run_until_complete(consume_realtime(WS_URL))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
