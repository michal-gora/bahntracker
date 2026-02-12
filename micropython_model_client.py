"""
MicroPython WebSocket Client for Model Train Controller (Psoc 6)

Connects to the server's WebSocket, receives SPEED/STOP commands,
sends HALL sensor events.

Hardware connections:
- Motor PWM: Pin TBD
- HALL sensor: Pin TBD (interrupt-driven)

Configuration:
1. Set SERVER_IP to your server's IP address
2. Set WIFI_SSID and WIFI_PASSWORD
3. Configure motor and HALL sensor pins
"""

import network
import time
import socket
import struct
import hashlib
import binascii
from machine import Pin, PWM

# ============================================================
# CONFIGURATION - EDIT THESE
# ============================================================

SERVER_IP = "192.168.1.100"  # TODO: Change to your server IP
SERVER_PORT = 8765

WIFI_SSID = "YourWiFiSSID"      # TODO: Change to your WiFi
WIFI_PASSWORD = "YourPassword"   # TODO: Change to your WiFi password

# Hardware pins (TODO: adjust for your Psoc 6 setup)
MOTOR_PWM_PIN = 0   # PWM pin for motor speed control
HALL_SENSOR_PIN = 1 # Digital input for HALL sensor

# PWM settings
PWM_FREQ = 1000  # 1kHz PWM frequency
PWM_MAX = 65535  # 16-bit PWM resolution

# ============================================================
# GLOBALS
# ============================================================

motor_pwm = None
hall_sensor = None
websocket_connected = False
ws_socket = None
hall_triggered = False


# ============================================================
# SIMPLE WEBSOCKET CLIENT (MicroPython compatible)
# ============================================================

def websocket_handshake(sock, host, path):
    """Perform WebSocket handshake."""
    key = binascii.b2a_base64(struct.pack("I", int(time.time())))[:-1].decode()
    
    handshake = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"\r\n"
    )
    
    sock.send(handshake.encode())
    
    # Read response
    response = b""
    while b"\r\n\r\n" not in response:
        response += sock.recv(1024)
    
    # Check for 101 Switching Protocols
    if b"101" not in response:
        raise Exception("WebSocket handshake failed")
    
    return True


def websocket_send(sock, message):
    """Send WebSocket text frame."""
    payload = message.encode()
    length = len(payload)
    
    # Frame format: FIN=1, opcode=1 (text), mask=1
    frame = bytearray([0x81])  # FIN + text opcode
    
    if length < 126:
        frame.append(0x80 | length)  # Mask bit + length
    elif length < 65536:
        frame.append(0x80 | 126)
        frame.extend(struct.pack(">H", length))
    else:
        frame.append(0x80 | 127)
        frame.extend(struct.pack(">Q", length))
    
    # Masking key (4 random bytes)
    mask_key = struct.pack("I", int(time.ticks_ms()))
    frame.extend(mask_key)
    
    # Masked payload
    masked = bytearray(length)
    for i in range(length):
        masked[i] = payload[i] ^ mask_key[i % 4]
    frame.extend(masked)
    
    sock.send(frame)


def websocket_recv(sock):
    """Receive WebSocket frame (simplified, text frames only)."""
    try:
        # Read first 2 bytes
        header = sock.recv(2)
        if len(header) < 2:
            return None
        
        opcode = header[0] & 0x0F
        masked = (header[1] & 0x80) != 0
        length = header[1] & 0x7F
        
        # Handle extended length
        if length == 126:
            length = struct.unpack(">H", sock.recv(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", sock.recv(8))[0]
        
        # Read mask key if present (server shouldn't mask, but check)
        if masked:
            mask_key = sock.recv(4)
        
        # Read payload
        payload = sock.recv(length)
        
        # Unmask if needed
        if masked:
            unmasked = bytearray(length)
            for i in range(length):
                unmasked[i] = payload[i] ^ mask_key[i % 4]
            payload = unmasked
        
        # Close frame
        if opcode == 8:
            return None
        
        # Text frame
        if opcode == 1:
            return payload.decode()
        
        return None
        
    except Exception as e:
        print(f"Error receiving: {e}")
        return None


# ============================================================
# MOTOR CONTROL
# ============================================================

def init_motor():
    """Initialize motor PWM."""
    global motor_pwm
    motor_pwm = PWM(Pin(MOTOR_PWM_PIN))
    motor_pwm.freq(PWM_FREQ)
    motor_pwm.duty_u16(0)
    print("✅ Motor initialized")


def set_speed(speed):
    """Set motor speed (0.0 to 1.0)."""
    global motor_pwm
    if motor_pwm:
        duty = int(speed * PWM_MAX)
        motor_pwm.duty_u16(duty)
        print(f"🚂 Speed set to {speed:.2f} (duty={duty})")


def stop_motor():
    """Stop motor."""
    global motor_pwm
    if motor_pwm:
        motor_pwm.duty_u16(0)
        print("🛑 Motor stopped")


# ============================================================
# HALL SENSOR
# ============================================================

def hall_interrupt(pin):
    """HALL sensor interrupt handler."""
    global hall_triggered
    hall_triggered = True
    stop_motor()  # Safety: stop immediately
    print("🧲 HALL sensor triggered!")


def init_hall_sensor():
    """Initialize HALL sensor with interrupt."""
    global hall_sensor
    hall_sensor = Pin(HALL_SENSOR_PIN, Pin.IN, Pin.PULL_UP)
    hall_sensor.irq(trigger=Pin.IRQ_FALLING, handler=hall_interrupt)
    print("✅ HALL sensor initialized")


# ============================================================
# WIFI CONNECTION
# ============================================================

def connect_wifi():
    """Connect to WiFi."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    if not wlan.isconnected():
        print(f"📡 Connecting to WiFi: {WIFI_SSID}...")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        
        timeout = 30
        while not wlan.isconnected() and timeout > 0:
            time.sleep(1)
            timeout -= 1
            print(".", end="")
        
        print()
    
    if wlan.isconnected():
        print(f"✅ WiFi connected: {wlan.ifconfig()[0]}")
        return True
    else:
        print("❌ WiFi connection failed")
        return False


# ============================================================
# WEBSOCKET CLIENT LOOP
# ============================================================

def connect_to_server():
    """Connect to server WebSocket."""
    global ws_socket, websocket_connected
    
    try:
        # Create socket
        addr = socket.getaddrinfo(SERVER_IP, SERVER_PORT)[0][-1]
        ws_socket = socket.socket()
        ws_socket.connect(addr)
        
        print(f"🔌 Connected to {SERVER_IP}:{SERVER_PORT}")
        
        # WebSocket handshake
        websocket_handshake(ws_socket, SERVER_IP, "/")
        print("✅ WebSocket handshake complete")
        
        # Send HELLO:MODEL
        websocket_send(ws_socket, "HELLO:MODEL")
        print("→ Sent: HELLO:MODEL")
        
        # Wait for ACK
        response = websocket_recv(ws_socket)
        if response == "ACK":
            print("← Received: ACK")
            websocket_connected = True
            return True
        else:
            print(f"❌ Expected ACK, got: {response}")
            return False
            
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return False


def handle_message(message):
    """Handle incoming message from server."""
    if message.startswith("SPEED:"):
        try:
            speed = float(message.split(":")[1])
            set_speed(speed)
        except:
            print(f"❌ Invalid SPEED command: {message}")
    
    elif message == "STOP":
        stop_motor()
    
    else:
        print(f"⚠️  Unknown command: {message}")


def main_loop():
    """Main event loop."""
    global hall_triggered, websocket_connected, ws_socket
    
    while True:
        try:
            # Check for incoming messages (non-blocking)
            ws_socket.setblocking(False)
            try:
                message = websocket_recv(ws_socket)
                if message:
                    print(f"← Received: {message}")
                    handle_message(message)
                elif message is None:
                    # Connection closed
                    print("⚠️  Connection closed by server")
                    websocket_connected = False
                    break
            except OSError:
                # No data available (non-blocking)
                pass
            finally:
                ws_socket.setblocking(True)
            
            # Check if HALL sensor was triggered
            if hall_triggered:
                hall_triggered = False
                websocket_send(ws_socket, "HALL")
                print("→ Sent: HALL")
            
            time.sleep(0.05)  # 50ms loop
            
        except Exception as e:
            print(f"❌ Error in main loop: {e}")
            websocket_connected = False
            break


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def main():
    """Main entry point."""
    print("=" * 50)
    print("  Model Train WebSocket Client")
    print("=" * 50)
    
    # Initialize hardware
    init_motor()
    init_hall_sensor()
    
    # Connect to WiFi
    if not connect_wifi():
        print("❌ Cannot proceed without WiFi")
        return
    
    # Connect to server
    while True:
        if connect_to_server():
            print("\n✅ Ready! Listening for commands...\n")
            main_loop()
        
        # Reconnect after 5 seconds
        print("\n⏳ Reconnecting in 5 seconds...")
        time.sleep(5)


# Run on boot
if __name__ == "__main__":
    main()
