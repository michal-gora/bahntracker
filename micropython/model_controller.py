import wifi
import socket
import sys
import time
import errno
import machine
from machine import Pin
from machine import PWM

# ============================================================
# CONFIGURATION
# ============================================================
# Network
SERVER_IP = "192.168.178.26"
SERVER_PORT = 8080

# Watchdog timers (must coordinate with server settings)
PING_INTERVAL = 10      # seconds - how often MCU sends PING
PONG_TIMEOUT = 3        # seconds - if no PONG received, reconnect
RECONNECT_DELAY = 5    # seconds - wait before reconnecting

# Hardware pins
LED_PIN = "P5_3"
PWM_PIN = "P9_7"
REVERSER_PIN = "P9_6"
# ============================================================

is_led_on = True
led_pin = LED_PIN
pwm_pin = PWM_PIN
reverser_pin = REVERSER_PIN

pwm = PWM(pwm_pin, freq=1000, duty_u16=0)
reverser = Pin(reverser_pin, Pin.OUT)
led = None

def toggle_led():
    global is_led_on, led
    if led == None:
        print(f"Error: led is None")
        return
    is_led_on = not is_led_on
    led.value(is_led_on)
    print(f"LED is now {'ON' if is_led_on else 'OFF'}")
    
def set_speed(speed : float):
    """
    Args:
        speed: [0, 1], sets the PWM between 0% and 100%
    """
    global pwm
    
    # Clipping speed to [0, 1]
    speed = max(0., min(speed, 1.))
    
    pwm.duty_u16(int(speed * 65535.0))
    print(f"Set pwm duty cycle to {speed}")
    return
    
def set_reverser(reversed : bool):
    global reverser
    reverser.value(reversed)

            
def start_socket_client():
    s = None
    last_ping_sent = 0
    waiting_for_pong = False
    
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
                
                print(f"✓ Connected to server at {SERVER_IP}:{SERVER_PORT}")
                
                # Send HELLO handshake
                s.write(b"HELLO:MODEL\n")
                print("Sent HELLO:MODEL")
                
                # Reset watchdog timers
                last_ping_sent = time.time()
                waiting_for_pong = False
                
            except OSError as e:
                print(f"✗ Connection failed: {e}")
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
            # Watchdog: Check if we need to send PING
            current_time = time.time()
            if current_time - last_ping_sent >= PING_INTERVAL:
                try:
                    s.write(b"PING\n")
                    last_ping_sent = current_time
                    waiting_for_pong = True
                    print("→ Sent PING")
                except OSError as e:
                    print(f"✗ Failed to send PING: {e}")
                    raise
            
            # Watchdog: Check if we're waiting for PONG and it's overdue
            if waiting_for_pong and (current_time - last_ping_sent > PONG_TIMEOUT):
                print(f"✗ No PONG received within {PONG_TIMEOUT}s after PING - reconnecting")
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
            
            # Check if connection was closed (readline returns empty bytes)
            if raw_line == b"":
                # Empty read could mean closed connection, check again
                try:
                    # Try another read to confirm
                    test = s.recv(1)
                    if test == b"":
                        print("✗ Server closed connection - reconnecting")
                        try:
                            s.close()
                        except:
                            pass
                        s = None
                        time.sleep(RECONNECT_DELAY)
                        continue
                except OSError as e:
                    if e.args[0] != errno.EAGAIN:
                        # Connection is dead
                        print("✗ Connection lost - reconnecting")
                        try:
                            s.close()
                        except:
                            pass
                        s = None
                        time.sleep(RECONNECT_DELAY)
                        continue
            
            # Only process if we got data
            if raw_line:
                line_str = raw_line.decode('utf-8', 'ignore').strip()
                
                """
                Train Control Protocol:
                    RegEx: <command name>[":"<value>|";"]
                    Commands should be snake_case.
                    Values are preferred as int > float > String
                    Summary:
                    Commands that simply send a signal without passing arguments, end with ";"
                    Commands that pass an argument, separate name from value with a ":"
                """
                if line_str == "PONG":
                    waiting_for_pong = False
                    print("← Received PONG")
                elif line_str == "led_button;":
                    print("Received Button")
                    toggle_led()
                    s.write(b"LED toggled!\n")
                elif line_str.startswith("speed:"):
                    print("Received slider")
                    s.write(b"Slider received!\n")
                    try:
                        value = float(line_str.split(':')[1])
                        set_speed(value)
                        print(f"Slider value: {value}")
                    except (IndexError, ValueError):
                        print("Invalid slider format")
                elif line_str.startswith("reverser:"):
                    reverser_state = bool(int(line_str.split(":")[1]))
                    print("Reverser state:", reverser_state)
                    set_reverser(reverser_state)
                # Ignore unknown messages silently (could be ACK or other server messages)

        except OSError as e:
            code = e.args[0]
            if code == errno.ECONNRESET:
                print("✗ Connection reset/broken pipe – reconnecting")
                try:
                    s.close()
                except:
                    pass
                s = None
                time.sleep(RECONNECT_DELAY)
                continue
            elif code == errno.EAGAIN:
                # No data this cycle — skip work
                pass
            elif code == errno.ETIMEDOUT:
                print("✗ Connection timed out - reconnecting")
                try:
                    s.close()
                except:
                    pass
                s = None
                time.sleep(RECONNECT_DELAY)
                continue
            else:
                print(f"✗ Socket error: {e} - reconnecting")
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
    global led, is_led_on
    led_pwm = PWM(led_pin, freq=4, duty_u16=35555)
    reverser.value(False)

    # Connect to WiFi with retry
    max_wifi_retries = 5
    wifi_retry_delay = 3  # seconds
    
    for attempt in range(max_wifi_retries):
        print(f"Connecting to WiFi... (attempt {attempt + 1}/{max_wifi_retries})")
        try:
            if wifi.network_connect():
                print("✓ WiFi connected")
                break
            else:
                print(f"✗ WiFi connection failed")
                if attempt < max_wifi_retries - 1:
                    print(f"Retrying in {wifi_retry_delay} seconds...")
                    time.sleep(wifi_retry_delay)
        except Exception as e:
            print(f"✗ WiFi error: {e}")
            if attempt < max_wifi_retries - 1:
                print(f"Retrying in {wifi_retry_delay} seconds...")
                time.sleep(wifi_retry_delay)
    else:
        # All retries failed
        print("✗ Failed to connect to WiFi after all retries. Restarting...")
        led_pwm.deinit()
        time.sleep(5)
        machine.reset()

    led_pwm.deinit()
    led = Pin(led_pin, Pin.OUT)
    led.value(True)
    is_led_on = True

    # Start client with exception handling
    while True:
        try:
            start_socket_client()
        except Exception as e:
            print(f"✗ Fatal error in socket client: {e}")
            print("Restarting in 5 seconds...")
            time.sleep(5)
            import machine
            machine.reset()

if __name__ == "__main__":
    main()

### TODO:
# - Add hall effect sensor reading and send "HALL\n" to server when triggered
# - Add error handling for malformed commands
# - Finally adjust it in sbahn server script to send speed and reverser commands based on state machine logic