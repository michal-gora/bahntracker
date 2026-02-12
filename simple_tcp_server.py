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


PORT = 8766


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer = writer.get_extra_info("peername")
    print(f"\n✅ Client connected from {peer}")
    
    try:
        # Wait for HELLO:MODEL
        line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        hello = line.decode().strip()
        print(f"📩 Received: {hello}")
        
        if hello == "HELLO:MODEL":
            writer.write(b"ACK\n")
            await writer.drain()
            print("📤 Sent: ACK")
        
        # Create task to read from client
        async def read_loop():
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
        
        # Start reading in background
        read_task = asyncio.create_task(read_loop())
        
        # Command loop - send commands to client
        print("\nCommands: p=ping, l=led_button, s=speed, r=reverser, q=quit")
        print("Type command and press Enter:")
        
        loop = asyncio.get_running_loop()
        
        while True:
            # Check if client disconnected
            if read_task.done():
                break
                
            # Non-blocking check for user input
            await asyncio.sleep(0.1)
            
    except asyncio.TimeoutError:
        print("❌ Timeout waiting for HELLO")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        writer.close()
        await writer.wait_closed()
        print("\n🔌 Connection closed")


async def send_commands(writer: asyncio.StreamWriter):
    """Interactive command sending"""
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    
    commands = {
        'p': b"ping;\n",
        'l': b"led_button;\n",
        's': b"speed:0.50\n",
        'r': b"reverser:1\n",
    }
    
    while True:
        line = await reader.readline()
        cmd = line.decode().strip().lower()
        
        if cmd == 'q':
            break
        
        if cmd in commands:
            msg = commands[cmd]
            writer.write(msg)
            await writer.drain()
            print(f"📤 Sent: {msg.decode().strip()}")
        else:
            print(f"Unknown command: {cmd}")


async def main():
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
