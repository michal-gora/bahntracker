import wifi
import socket
import sys
import time
import errno
import ujson
from machine import Pin
from machine import PWM

# ============================================================
# CONFIGURATION
# ============================================================

SERVER_PORT = 8766

led_pin = "P5_3"
pwm_pin = "P9_7"
reverser_pin = "P9_6"

# ============================================================
# HARDWARE GLOBALS
# ============================================================

is_led_on = True
pwm = PWM(pwm_pin, freq=1000, duty_u16=0)
reverser = Pin(reverser_pin, Pin.OUT)
led = None

# ============================================================
# HARDWARE FUNCTIONS
# ============================================================

def toggle_led():
    global is_led_on, led
    if led is None:
        print("Error: led is None")
        return
    is_led_on = not is_led_on
    led.value(is_led_on)
    print(f"LED is now {'ON' if is_led_on else 'OFF'}")

def set_speed(speed: float):
    """Set motor PWM. speed: 0.0 to 1.0"""
    global pwm
    speed = max(0.0, min(speed, 1.0))
    pwm.duty_u16(int(speed * 65535.0))
    print(f"Set pwm duty cycle to {speed:.2f}")

def stop_motor():
    """Stop motor immediately."""
    global pwm
    pwm.duty_u16(0)
    print("Motor stopped")

def set_reverser(reversed: bool):
    global reverser
    reverser.value(reversed)

# ============================================================
# SERVER CONFIG
# ============================================================

def load_server_config():
    """Load server IP from server_config.json."""
    try:
        with open("server_config.json") as f:
            cfg = ujson.load(f)
            return cfg["server_ip"]
    except Exception as e:
        print(f"Could not load server_config.json: {e}")
        return None

# ============================================================
# PLAIN TCP CLIENT (no WebSocket!)
# ============================================================

def connect_to_server(server_ip):
    """Connect to server via plain TCP. Returns socket or None."""
    try:
        addr = socket.getaddrinfo(server_ip, SERVER_PORT)[0][-1]
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(addr)
        print(f"TCP connected to {server_ip}:{SERVER_PORT}")

        # Identify ourselves
        sock.send(b"HELLO:MODEL\n")
        print("Sent: HELLO:MODEL")

        # Wait for ACK
        sock.settimeout(5.0)
        response = sock.recv(1024).decode().strip()
        print(f"Received: {response}")

        if response == "ACK":
            print("Server acknowledged connection")
            sock.setblocking(False)
            return sock
        else:
            print(f"Expected ACK, got: {response}")
            sock.close()
            return None

    except Exception as e:
        print(f"Connection error: {e}")
        try:
            sock.close()
        except:
            pass
        return None

def handle_command(line_str):
    """Handle a command received from the server."""
    if line_str.startswith("SPEED:"):
        try:
            value = float(line_str.split(':')[1])
            set_speed(value)
        except (IndexError, ValueError):
            print(f"Invalid SPEED format: {line_str}")
    elif line_str == "STOP":
        stop_motor()
    else:
        print(f"Unknown command: {line_str}")

def run_client(server_ip):
    """Main client loop: connect, receive commands, send HALL events."""
    sock = connect_to_server(server_ip)
    if sock is None:
        return False

    print("Ready! Listening for commands from server...\n")

    recv_buf = b""

    try:
        while True:
            try:
                chunk = sock.recv(1024)
                if chunk:
                    recv_buf += chunk
                    # Process complete lines
                    while b"\n" in recv_buf:
                        line, recv_buf = recv_buf.split(b"\n", 1)
                        line_str = line.decode('utf-8', 'ignore').strip()
                        if line_str:
                            print(f"Received: {line_str}")
                            handle_command(line_str)
                elif chunk == b"":
                    # Connection closed
                    print("Server closed connection")
                    break

            except OSError as e:
                code = e.args[0]
                if code == errno.ECONNRESET:
                    print("Connection reset - closing")
                    break
                elif code == errno.EAGAIN:
                    # No data this cycle - that's fine
                    pass
                elif code == errno.ETIMEDOUT:
                    print("Connection timed out - closing")
                    break
                else:
                    print(f"Socket error: {e}")
                    break

            # TODO: Check HALL sensor here and send if triggered
            # if hall_triggered:
            #     hall_triggered = False
            #     sock.send(b"HALL\n")
            #     print("Sent: HALL")
            #     stop_motor()  # Safety stop

            time.sleep(0.05)

    except Exception as e:
        print(f"Client error: {e}")
    finally:
        print("Closing connection")
        try:
            sock.close()
        except:
            pass

    return True

# ============================================================
# MAIN
# ============================================================

def main():
    global led, is_led_on
    led_pwm = PWM(led_pin, freq=4, duty_u16=35555)
    reverser.value(False)

    # Connect to WiFi
    print("Connecting to WiFi...")
    try:
        if not wifi.network_connect():
            print("Couldn't establish WiFi connection. Stopping.")
            led_pwm.deinit()
            sys.exit()
    except Exception as e:
        print(f"WiFi error: {e}")
        led_pwm.deinit()
        sys.exit()

    led_pwm.deinit()
    led = Pin(led_pin, Pin.OUT)
    led.value(True)
    is_led_on = True

    # Load server IP
    server_ip = load_server_config()
    if not server_ip:
        print("No server IP configured. Create server_config.json with {\"server_ip\": \"x.x.x.x\"}")
        return

    print(f"Server: {server_ip}:{SERVER_PORT}")

    # Connect to server with reconnection loop
    while True:
        stop_motor()  # Safety: ensure motor is off before connecting
        print(f"\nConnecting to server {server_ip}:{SERVER_PORT}...")
        run_client(server_ip)
        print("Reconnecting in 5 seconds...")
        time.sleep(5)

if __name__ == "__main__":
    main()
