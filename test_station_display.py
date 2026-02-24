#!/usr/bin/env python3
"""
Simple test server for the station display.
Allows manual control via keyboard commands.
"""

import asyncio
import sys

# Port must match the station display configuration
STATION_TCP_PORT = 8081

client_writer = None
loop = None


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    global client_writer
    
    peer = writer.get_extra_info("peername")
    print(f"\n📡 Connection from {peer}")
    
    try:
        # Wait for HELLO:STATION
        line = await asyncio.wait_for(reader.readline(), timeout=10.0)
        hello = line.decode().strip()
        print(f"📥 Received: {hello}")
        
        if hello != "HELLO:STATION":
            print(f"❌ Expected HELLO:STATION, got: {hello}")
            writer.close()
            return
        
        # Send ACK
        writer.write(b"ACK\n")
        await writer.drain()
        print("📤 Sent: ACK")
        
        client_writer = writer
        print("\n✅ Station display connected!")
        print_help()
        
        # Read loop
        while True:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=1.0)
                if not line:
                    print("\n⚠️  Connection closed by client")
                    break
                
                msg = line.decode().strip()
                if msg:
                    if msg == "PING":
                        writer.write(b"PONG\n")
                        await writer.drain()
                        print(".", end="", flush=True)  # Show heartbeat
                    else:
                        print(f"\n📥 Received: {msg}")
                        
            except asyncio.TimeoutError:
                continue
                
    except asyncio.TimeoutError:
        print("❌ Client timed out during handshake")
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        client_writer = None
        try:
            writer.close()
            await writer.wait_closed()
        except:
            pass
        print("\n⚠️  Station display disconnected")


def print_help():
    print("\n" + "="*60)
    print("COMMANDS:")
    print("="*60)
    print("  c              - Clear display")
    print("  s <name>       - Show station (valid/arriving)")
    print("  n <name>       - Show next station (invalid)")
    print("  h              - Show this help")
    print("  q              - Quit server")
    print("\nExamples:")
    print("  s Marienplatz")
    print("  n München Hbf")
    print("  s Ostbahnhof")
    print("  c")
    print("="*60 + "\n")


def input_thread_func():
    """Thread to read stdin and send commands"""
    while True:
        try:
            cmd = input().strip()
            
            if not cmd:
                continue
            
            if cmd == 'q':
                print("Quitting...")
                sys.exit(0)
            
            if cmd == 'h':
                print_help()
                continue
            
            if not client_writer:
                print("⚠️  No station display connected")
                continue
            
            # Parse command
            parts = cmd.split(None, 1)
            command = parts[0].lower()
            
            if command == 'c':
                # Clear
                msg = b"STATION:clear\n"
                client_writer.write(msg)
                asyncio.run_coroutine_threadsafe(client_writer.drain(), loop)
                print(f"📤 Sent: {msg.decode().strip()}")
                
            elif command == 's' and len(parts) == 2:
                # Show station (valid)
                station_name = parts[1]
                msg = f"STATION:{station_name}:valid\n".encode()
                client_writer.write(msg)
                asyncio.run_coroutine_threadsafe(client_writer.drain(), loop)
                print(f"📤 Sent: {msg.decode().strip()}")
                
            elif command == 'n' and len(parts) == 2:
                # Next station (invalid)
                station_name = parts[1]
                msg = f"STATION:{station_name}:invalid\n".encode()
                client_writer.write(msg)
                asyncio.run_coroutine_threadsafe(client_writer.drain(), loop)
                print(f"📤 Sent: {msg.decode().strip()}")
                
            else:
                print(f"❌ Unknown command: {cmd}")
                print("Type 'h' for help")
                
        except EOFError:
            break
        except KeyboardInterrupt:
            sys.exit(0)


async def main():
    global loop
    loop = asyncio.get_event_loop()
    
    print("="*60)
    print("  Station Display Test Server")
    print("="*60)
    print(f"\n🌐 Starting TCP server on port {STATION_TCP_PORT}...")
    
    # Start input thread
    import threading
    input_thread = threading.Thread(target=input_thread_func, daemon=True)
    input_thread.start()
    
    # Start server
    server = await asyncio.start_server(
        handle_client,
        "0.0.0.0",
        STATION_TCP_PORT
    )
    
    addr = server.sockets[0].getsockname()
    print(f"✅ Server listening on {addr[0]}:{addr[1]}")
    print(f"\n📱 Connect your PSoC6 station display to this server")
    print(f"   (Set SERVER_IP to this machine's IP address)")
    print_help()
    
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down...")
