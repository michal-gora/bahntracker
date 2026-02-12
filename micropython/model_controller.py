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
hall_pin = "P9_0"  # TODO: set to your actual HALL sensor pin
hall_debounce_ms = 500  # ignore repeat triggers within this window

# ============================================================
# HARDWARE GLOBALS
# ============================================================

is_led_on = True
pwm = PWM(pwm_pin, freq=1000, duty_u16=0)
reverser = Pin(reverser_pin, Pin.OUT)
led = None
hall_triggered = False
last_hall_ms = 0

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

def hall_interrupt(pin):
    """HALL sensor interrupt handler — runs in IRQ context.
    
    IMPORTANT: Do NOT call pwm.duty_u16() or print() here!
    On Psoc 6, touching peripherals in IRQ context can deadlock.
    We only set a flag; the main loop handles the rest.
    """
    global hall_triggered, last_hall_ms
    now = time.ticks_ms()
    if time.ticks_diff(now, last_hall_ms) >= hall_debounce_ms:
        last_hall_ms = now
        hall_triggered = True

def init_hall_sensor():
    """Set up HALL sensor pin with falling-edge interrupt."""
    hall = Pin(hall_pin, Pin.IN, Pin.PULL_UP)
    hall.irq(trigger=Pin.IRQ_FALLING, handler=hall_interrupt)
    print(f"HALL sensor initialized on pin {hall_pin}")
    return hall

# ============================================================
# LINE BUFFER (non-blocking readline over raw TCP)
# ============================================================

class LineBuffer:
    """Accumulates recv() chunks, yields complete \\n-terminated lines."""
    def __init__(self):
        self.buf = b""

    def feed(self, data):
        self.buf += data

    def pop_line(self):
        """Return next complete line (stripped), or None if incomplete."""
        i = self.buf.find(b"\n")
        if i == -1:
            return None
        line = self.buf[:i]
        self.buf = self.buf[i + 1:]
        return line.decode("utf-8", "ignore").strip()

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
            # Use settimeout(0) for non-blocking — more portable than setblocking(False)
            sock.settimeout(0)
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
        toggle_led()
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
    """Main client loop: connect, receive commands, send HALL events.
    
    Fully non-blocking: checks for server data AND HALL sensor every cycle.
    """
    global hall_triggered

    sock = connect_to_server(server_ip)
    if sock is None:
        return False

    print("Ready! Listening for commands from server...\n")

    lb = LineBuffer()
    empty_recv_streak = 0
    last_ping_ms = time.ticks_ms()
    last_pong_ms = time.ticks_ms()
    ping_interval_ms = 3000
    pong_timeout_ms = 8000

    try:
        while True:
            # --- 1. Non-blocking recv from server ---
            try:
                chunk = sock.recv(512)
                if chunk:  # got data
                    lb.feed(chunk)
                    empty_recv_streak = 0
                # NOTE: on non-blocking sockets, some MicroPython ports
                # return b"" instead of raising EAGAIN when no data.
                # We do NOT treat b"" as "connection closed" here.
                elif chunk == b"":
                    # If we repeatedly see empty reads, assume connection is stale.
                    empty_recv_streak += 1
                    if empty_recv_streak >= 5:
                        print("Empty recv streak — reconnecting")
                        break
            except OSError as e:
                code = e.args[0]
                if code in (errno.EAGAIN, 11):  # EAGAIN / EWOULDBLOCK
                    pass  # No data right now — that's fine
                elif code == errno.ECONNRESET:
                    print("Connection reset - closing")
                    break
                elif code == errno.ETIMEDOUT:
                    print("Connection timed out - closing")
                    break
                else:
                    print(f"Socket error ({code}): {e}")
                    break

            # --- 2. Process any complete lines from server ---
            while True:
                line = lb.pop_line()
                if line is None:
                    break
                if line:
                    print(f"Received: {line}")
                    if line == "PONG":
                        last_pong_ms = time.ticks_ms()
                    else:
                        handle_command(line)

            # --- 3. Check HALL sensor (set by interrupt) ---
            if hall_triggered:
                hall_triggered = False
                stop_motor()  # Safety stop from main context (safe!)
                try:
                    sock.send(b"HALL\n")
                    print("Sent: HALL")
                except OSError as e:
                    print(f"Failed to send HALL: {e}")
                    break

            # --- 4. Keepalive ping to detect broken connections ---
            now = time.ticks_ms()
            if time.ticks_diff(now, last_ping_ms) >= ping_interval_ms:
                last_ping_ms = now
                try:
                    sock.send(b"PING\n")
                except OSError as e:
                    print(f"Keepalive failed: {e}")
                    break

            # --- 5. Reconnect if no PONG within timeout ---
            if time.ticks_diff(now, last_pong_ms) >= pong_timeout_ms:
                print("PONG timeout — reconnecting")
                break

            # --- 4. Yield CPU briefly ---
            time.sleep(0.02)  # 20ms → 50 Hz loop

    except Exception as e:
        print(f"Client error: {e}")
    finally:
        print("Closing connection")
        stop_motor()
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

    # Initialize HALL sensor (interrupt-driven)
    init_hall_sensor()

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
