import wifi
import socket
import websocket
import hashlib
import binascii
import sys
import time
import errno
from machine import Pin
from machine import PWM

is_led_on = True
led_pin = "P5_3"
pwm_pin = "P9_7"
reverser_pin = "P9_6"

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

def websocket_handshake(request):
    lines = request.split('\r\n')
    websocket_key = None
    
    for line in lines:
        if line.startswith('Sec-WebSocket-Key:'):
            websocket_key = line.split(': ')[1].strip()
            break
    
    if not websocket_key:
        return None
    
    magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    accept_string = websocket_key + magic
    sha1_hash = hashlib.sha1(accept_string.encode('utf-8')).digest()
    accept_key = binascii.b2a_base64(sha1_hash).decode('utf-8').strip()
    
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_key}\r\n"
        "\r\n"
    )
    
    return response
            
def start_websocket_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 4014))
    s.listen(1)
    
    print("WebSocket server started on port 4014")
    
    while True:
        try:
            conn, addr = s.accept()
            print(f"Connection from {addr}")

            # Non-blocking mode
            conn.setblocking(False)  # immediately return from reads with EAGAIN if no data
            conn.settimeout(5.0)
            request = b""
            try:
                request = conn.recv(1024).decode('utf-8')
            except OSError:
                # No data yet
                pass

            if 'websocket' in request.lower() and 'upgrade' in request.lower():
                handshake_response = websocket_handshake(request)
                if handshake_response:
                    conn.send(handshake_response.encode('utf-8'))
                    print("WebSocket connected")
                    
                    ws = websocket.websocket(conn)

                    try:
                        while True:
                            try:
                                raw_line = ws.readline()
                                if not raw_line:
                                    print("Client disconnected (EOF)")
                                    break  # exit work loop
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
                                if line_str == "ping;":
                                    print("Received Ping")
                                    ws.write(b"pong\n")
                                elif line_str == "led_button;":
                                    print("Received Button")
                                    toggle_led()
                                    ws.write(b"LED toggled!\n")
                                elif line_str.startswith("speed:"):
                                    print("Received slider")
                                    ws.write(b"Slider received!\n")
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
                                else:
                                    print(f"Received else: {line_str}")
                                    ws.write(b"Line received\n")

                            except OSError as e:
                                code = e.args[0]
                                if code == errno.ECONNRESET:
                                    print("Connection reset/broken pipe – closing")
                                    break
                                elif code == errno.EAGAIN:
                                    # No data this cycle — skip work
                                    pass
                                elif code == errno.ETIMEDOUT:
                                    print("Connection timed out - closing")
                                    break
                                else:
                                    print("Other socket error:", e)
                                    break

                            # Do other tasks here...
                            time.sleep(0.1)
                    except Exception as e:
                        print(f"WebSocket error: {e}")
                    finally:
                        print("Closing connection")
                        try:
                            ws.close()
                        except:
                            pass
                        try:
                            conn.close()
                        except:
                            pass
                else:
                    conn.close()
            else:
                conn.close()
                
        except Exception as e:
            print(f"Server error: {e}")

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
        led_pwm.deinit()
        sys.exit()

    led_pwm.deinit()
    led = Pin(led_pin, Pin.OUT)
    led.value(True)
    is_led_on = True

    start_websocket_server()

if __name__ == "__main__":
    main()
