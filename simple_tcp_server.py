#!/usr/bin/env python3
"""
Simple TCP server for testing the MicroPython client.
Sends test commands and echoes received messages.

Usage:
    python simple_tcp_server.py
    
Commands (type and press Enter):
    p - send ping;
    l - send led_button;
    s - send speed:0.50
    r - send reverser:1
    q - quit
"""

import asyncio
import sys
import threading


PORT = 8766
client_writer = None


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    global client_writer
    peer = writer.get_extra_info("peername")
    print(f"\n✅ Client connected from {peer}")
    client_writer = writer
    
    try:
        # Wait for HELLO:MODEL
        line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        hello = line.decode().strip()
        print(f"📩 Received: {hello}")
        
        if hello == "HELLO:MODEL":
            writer.write(b"ACK\n")
            await writer.drain()
            print("📤 Sent: ACK")
        
        print("\nCommands: p=ping, l=led_button, s=speed, r=reverser, q=quit")
        print("Type command and press Enter:\n")
        
        # Read from client in loop
        while True:
            try:
                line = await reader.readline()
                if not line:
                    print("\n⚠️  Client disconnected")
                    break
                msg = line.decode().strip()
                print(f"📩 Received: {msg}")
            except Exception as e:
                print(f"\n❌ Read error: {e}")
                break
            
    except asyncio.TimeoutError:
        print("❌ Timeout waiting for HELLO")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        client_writer = None
        writer.close()
        await writer.wait_closed()
        print("\n🔌 Connection closed")


def input_thread():
    """Thread to read stdin and send commands"""
    commands = {
        'p': b"ping;\n",
        'l': b"led_button;\n",
        's': b"speed:0.50\n",
        'r': b"reverser:1\n",
    }
    
    while True:
        try:
            cmd = input().strip().lower()
            
            if cmd == 'q':
                print("Quitting...")
                sys.exit(0)
            
            if cmd in commands:
                if client_writer:
                    msg = commands[cmd]
                    client_writer.write(msg)
                    asyncio.run_coroutine_threadsafe(client_writer.drain(), loop)
                    print(f"📤 Sent: {msg.decode().strip()}")
                else:
                    print("⚠️  No client connected")
            elif cmd:
                print(f"Unknown command: {cmd}")
        except EOFError:
            break
        except Exception as e:
            print(f"Input error: {e}")


async def main():
    global loop
    loop = asyncio.get_running_loop()
    
    # Start input thread
    thread = threading.Thread(target=input_thread, daemon=True)
    thread.start()
    
    server = await asyncio.start_server(handle_client, "0.0.0.0", PORT)
    addr = server.sockets[0].getsockname()
    print(f"🚀 TCP server listening on {addr[0]}:{addr[1]}")
    print("Waiting for client connection...")
    
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Server stopped")
