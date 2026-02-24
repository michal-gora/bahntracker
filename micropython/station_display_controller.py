import wifi
import socket
import time
from time import sleep_ms
import errno
import machine
from machine import I2C, Pin
from mp_i2c_lcd1602 import I2C_LCD1602

# ============================================================
# CONFIGURATION
# ============================================================
# Network
SERVER_IP = "192.168.178.26"
SERVER_PORT = 8081

# Watchdog timers (must coordinate with server settings)
PING_INTERVAL = 10      # seconds - how often MCU sends PING
PONG_TIMEOUT = 3        # seconds - if no PONG received, reconnect
RECONNECT_DELAY = 5     # seconds - wait before reconnecting
# ============================================================


# ============================================================
# DISPLAY WRAPPER FUNCTIONS
# Replace these with your actual display implementation.
# ============================================================
i2c = I2C(sda=Pin("P6_1"), scl=Pin("P6_0"))
LCD = I2C_LCD1602(i2c)

def display_clear():
    """Clear the display."""
    LCD.clear()
    print("Display: clear")

def display_text(line1: str, line2: str = ""):
    """Show text on the display. line1 = top row, line2 = bottom row."""
    display_clear()
    LCD.puts(f"{line1.strip()[:16]}", y=0)
    LCD.puts(f"{line2.strip()[:16]}", y=1)
    print(f"Display: [{line1}] [{line2}]")

def display_init():
    """Initialize the display hardware. Called once at startup."""
    display_clear()
    display_text("Hello, world!")
    print("Display init")


# ============================================================


def start_socket_client():
    s = None
    last_ping_sent: float = 0.0
    waiting_for_pong: bool = False

    while True:
        # Connection/reconnection loop
        if s is None:
            try:
                print(f"Attempting to connect to {SERVER_IP}:{SERVER_PORT}...")
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.settimeout(5.0)  # 5 second timeout for connect
                s.connect((SERVER_IP, SERVER_PORT))
                s.setblocking(False)  # Set non-blocking after connect

                print(f"Connecting to server at {SERVER_IP}:{SERVER_PORT}")

                # Send HELLO handshake
                s.write(b"HELLO:STATION\n")
                print("Sent HELLO:STATION")

                # Reset watchdog timers
                last_ping_sent = time.time()
                waiting_for_pong = False

            except OSError as e:
                print(f"Connection failed: {e}")
                if s:
                    try:
                        s.close()
                    except:
                        pass
                    s = None
                print(f"Retrying in {RECONNECT_DELAY} seconds...")
                time.sleep(RECONNECT_DELAY)
                continue

        # Main communication loop
        try:
            # Watchdog: send PING
            current_time = time.time()
            if current_time - last_ping_sent >= PING_INTERVAL:
                try:
                    s.write(b"PING\n")
                    last_ping_sent = current_time
                    waiting_for_pong = True
                    print("Sent PING")
                except OSError as e:
                    print(f"Failed to send PING: {e}")
                    raise

            # Watchdog: check PONG timeout
            if waiting_for_pong and (current_time - last_ping_sent > PONG_TIMEOUT):
                print(f"No PONG received within {PONG_TIMEOUT}s after PING - reconnecting")
                try:
                    s.close()
                except:
                    pass
                s = None
                time.sleep(RECONNECT_DELAY)
                continue

            # Read line (non-blocking)
            raw_line = b""
            try:
                raw_line = s.readline()
            except OSError as e:
                if e.args[0] != errno.EAGAIN:
                    raise
                # No data available

            # Check if connection was closed
            if raw_line == b"":
                try:
                    test = s.recv(1)
                    if test == b"":
                        print("Server closed connection - reconnecting")
                        try:
                            s.close()
                        except:
                            pass
                        s = None
                        time.sleep(RECONNECT_DELAY)
                        continue
                except OSError as e:
                    if e.args[0] != errno.EAGAIN:
                        print("Connection lost - reconnecting")
                        try:
                            s.close()
                        except:
                            pass
                        s = None
                        time.sleep(RECONNECT_DELAY)
                        continue

            # Process received line
            if raw_line:
                line_str = raw_line.decode('utf-8', 'ignore').strip()

                if line_str == "PONG":
                    waiting_for_pong = False
                    print("Received PONG")

                elif line_str.startswith("STATION:"):
                    # STATION:name:STATE  → display name with state
                    #   STATE = AT_STATION_VALID | AT_STATION_WAITING | DRIVING | RUNNING_TO_STATION
                    # STATION:clear       → clear display
                    parts = line_str.split(":", 2)
                    if len(parts) == 2 and parts[1] == "clear":
                        display_clear()
                    elif len(parts) == 3:
                        station_name = parts[1]
                        state = parts[2]
                        display_text(station_name, state)
                    else:
                        print(f"Unknown STATION format: {line_str}")

                elif line_str.startswith("ETA:"):
                    # ETA:<unix_timestamp>  → absolute arrival time at Fasanenpark
                    # ETA:none              → no tracked train, no ETA
                    value = line_str[4:]  # strip "ETA:"
                    if value == "none":
                        eta_unix = None
                    else:
                        try:
                            eta_unix = int(value)
                            # print remaining time
                            remaining_seconds = eta_unix - int(time.time())
                            if remaining_seconds > 0:
                                print(f"ETA: {remaining_seconds} seconds")
                            else:
                                print("ETA: arriving now or already passed")
                        except ValueError:
                            print(f"Invalid ETA value: {value}")
                            eta_unix = None
                    # TODO: implement display logic (eta_unix is seconds since epoch,
                    # use time.time() to compute remaining seconds for countdown)
                elif line_str == "ACK":
                    display_text("Connected")
                    print("Successfully connected")
                # Ignore unknown messages silently (could be ACK or other server messages)

        except OSError as e:
            code = e.args[0]
            if code == errno.ECONNRESET:
                print("Connection reset – reconnecting")
            elif code == errno.ETIMEDOUT:
                print("Connection timed out - reconnecting")
            elif code == errno.EAGAIN:
                pass  # No data this cycle
            else:
                print(f"Socket error: {e} - reconnecting")

            if code != errno.EAGAIN:
                try:
                    s.close()
                except:
                    pass
                s = None
                time.sleep(RECONNECT_DELAY)
                continue

        # Do other tasks here...
        time.sleep(0.1)


def main():
    display_init()

    # Connect to WiFi with retry
    max_wifi_retries = 5
    wifi_retry_delay = 3  # seconds

    for attempt in range(max_wifi_retries):
        print(f"Connecting to WiFi... (attempt {attempt + 1}/{max_wifi_retries})")
        try:
            if wifi.network_connect():
                print("WiFi connected")
                break
            else:
                print(f"WiFi connection failed")
                if attempt < max_wifi_retries - 1:
                    print(f"Retrying in {wifi_retry_delay} seconds...")
                    time.sleep(wifi_retry_delay)
        except Exception as e:
            print(f"WiFi error: {e}")
            if attempt < max_wifi_retries - 1:
                print(f"Retrying in {wifi_retry_delay} seconds...")
                time.sleep(wifi_retry_delay)
    else:
        print("Failed to connect to WiFi after all retries. Restarting...")
        time.sleep(5)
        machine.reset()

    # Start client with exception handling
    while True:
        try:
            start_socket_client()
        except Exception as e:
            print(f"Fatal error in socket client: {e}")
            print("Restarting in 5 seconds...")
            time.sleep(5)
            machine.reset()


if __name__ == "__main__":
    main()

