import wifi
import socket
import sys
import time
import errno
import ujson
import binascii
import hashlib
import struct
import urandom
from machine import Pin
from machine import PWM

# ============================================================
# CONFIGURATION
# ============================================================

SERVER_PORT = 8765
WS_PATH = "/"

led_pin = "P5_3"
pwm_pin = "P9_7"
reverser_pin = "P9_6"
hall_pin = "P9_0"  # TODO: set to your actual HALL sensor pin
hall_debounce_ms = 200  # ignore repeat triggers within this window

debug_enabled = True
debug_interval_ms = 2000  # rate-limit debug prints

# ============================================================
# HARDWARE GLOBALS
# ============================================================

is_led_on = True
pwm = PWM(pwm_pin, freq=1000, duty_u16=0)
reverser = Pin(reverser_pin, Pin.OUT)
led = None
hall_triggered = False
last_hall_ms = 0
last_debug_ms = 0

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
# WEBSOCKET CLIENT
# ============================================================

MAGIC_WS = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _ws_key():
    raw = bytes([urandom.getrandbits(8) for _ in range(16)])
    return binascii.b2a_base64(raw).strip()


def _ws_accept(key_b64: bytes) -> str:
    accept_src = key_b64.decode() + MAGIC_WS
    sha1 = hashlib.sha1(accept_src.encode()).digest()
    return binascii.b2a_base64(sha1).strip().decode()


def ws_handshake(sock, host, port, path="/"):
    key = _ws_key()
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key.decode()}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.send(req.encode())

    sock.settimeout(5.0)
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(512)
        if not chunk:
            break
        data += chunk

    if b"101" not in data:
        print("Handshake failed:", data)
        return False

    expected = _ws_accept(key)
    if expected.encode() not in data:
        print("Handshake accept mismatch")

    print("WebSocket handshake complete")
    return True


def ws_send(sock, opcode, payload=b""):
    fin = 0x80
    mask_bit = 0x80
    length = len(payload)
    header = bytearray()
    header.append(fin | (opcode & 0x0F))

    if length < 126:
        header.append(mask_bit | length)
    elif length < 65536:
        header.append(mask_bit | 126)
        header.extend(struct.pack(">H", length))
    else:
        header.append(mask_bit | 127)
        header.extend(length.to_bytes(8, "big"))

    mask = bytes([urandom.getrandbits(8) for _ in range(4)])
    header.extend(mask)

    masked = bytearray(length)
    for i in range(length):
        masked[i] = payload[i] ^ mask[i % 4]

    sock.send(header + masked)


def ws_send_text(sock, text: str):
    ws_send(sock, 0x1, text.encode())


def ws_send_ping(sock, payload=b""):
    ws_send(sock, 0x9, payload)


def ws_send_pong(sock, payload=b""):
    ws_send(sock, 0xA, payload)


class WsBuffer:
    def __init__(self):
        self.buf = bytearray()

    def feed(self, data: bytes):
        self.buf.extend(data)

    def pop_frame(self):
        if len(self.buf) < 2:
            return None
        b1 = self.buf[0]
        b2 = self.buf[1]
        opcode = b1 & 0x0F
        masked = (b2 & 0x80) != 0
        length = b2 & 0x7F
        idx = 2

        if length == 126:
            if len(self.buf) < idx + 2:
                return None
            length = struct.unpack(">H", bytes(self.buf[idx:idx + 2]))[0]
            idx += 2
        elif length == 127:
            if len(self.buf) < idx + 8:
                return None
            length = int.from_bytes(self.buf[idx:idx + 8], "big")
            idx += 8

        if masked:
            if len(self.buf) < idx + 4:
                return None
            mask = self.buf[idx:idx + 4]
            idx += 4
        else:
            mask = None

        if len(self.buf) < idx + length:
            return None

        payload = bytes(self.buf[idx:idx + length])
        del self.buf[:idx + length]

        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

        return opcode, payload


def connect_ws(server_ip):
    try:
        addr = socket.getaddrinfo(server_ip, SERVER_PORT)[0][-1]
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(addr)
        print(f"TCP connected to {server_ip}:{SERVER_PORT}")

        if not ws_handshake(sock, server_ip, SERVER_PORT, WS_PATH):
            sock.close()
            return None, None

        sock.settimeout(0.1)

        ws_send_text(sock, "HELLO:MODEL")
        print("Sent: HELLO:MODEL")

        wsbuf = WsBuffer()
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < 5000:
            try:
                chunk = sock.recv(512)
                if chunk:
                    wsbuf.feed(chunk)
            except OSError as e:
                if e.args[0] in (errno.EAGAIN, 11, errno.ETIMEDOUT):
                    pass
                else:
                    print(f"Handshake recv error: {e}")
                    break

            while True:
                frame = wsbuf.pop_frame()
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == 0x1:
                    msg = payload.decode().strip()
                    print(f"Received: {msg}")
                    if msg == "ACK":
                        print("Server acknowledged connection")
                        return sock, wsbuf
                elif opcode == 0x9:
                    ws_send_pong(sock, payload)
                elif opcode == 0xA:
                    pass

            time.sleep(0.02)

        print("No ACK received")
        sock.close()
        return None, None

    except Exception as e:
        print(f"Connection error: {e}")
        try:
            sock.close()
        except:
            pass
        return None, None


def handle_command(line_str):
    if line_str.startswith("SPEED:"):
        toggle_led()
        try:
            value = float(line_str.split(":")[1])
            set_speed(value)
        except (IndexError, ValueError):
            print(f"Invalid SPEED format: {line_str}")
    elif line_str == "STOP":
        stop_motor()
    else:
        print(f"Unknown command: {line_str}")


def run_client(server_ip):
    global hall_triggered

    sock, wsbuf = connect_ws(server_ip)
    if sock is None:
        return False

    print("Ready! Listening for commands from server...\n")

    last_ping_ms = time.ticks_ms()
    last_pong_ms = time.ticks_ms()
    ping_interval_ms = 3000
    pong_timeout_ms = 8000

    def dbg(msg):
        global last_debug_ms
        if not debug_enabled:
            return
        now = time.ticks_ms()
        if time.ticks_diff(now, last_debug_ms) >= debug_interval_ms:
            last_debug_ms = now
            print(f"[{now}ms] {msg}")

    def log_event(msg):
        now = time.ticks_ms()
        print(f"[{now}ms] {msg}")

    try:
        while True:
            try:
                chunk = sock.recv(512)
                if chunk:
                    wsbuf.feed(chunk)
            except OSError as e:
                if e.args[0] in (errno.EAGAIN, 11, errno.ETIMEDOUT):
                    pass
                else:
                    print(f"Socket error: {e}")
                    break

            while True:
                frame = wsbuf.pop_frame()
                if frame is None:
                    break
                opcode, payload = frame

                if opcode == 0x1:  # text
                    msg = payload.decode().strip()
                    print(f"Received: {msg}")
                    handle_command(msg)
                elif opcode == 0x9:  # ping
                    ws_send_pong(sock, payload)
                elif opcode == 0xA:  # pong
                    last_pong_ms = time.ticks_ms()
                    log_event("PONG received")
                elif opcode == 0x8:  # close
                    print("Server closed connection")
                    return False

            if hall_triggered:
                hall_triggered = False
                stop_motor()
                try:
                    log_event("send HALL")
                    ws_send_text(sock, "HALL")
                    log_event("HALL sent")
                except OSError as e:
                    print(f"Failed to send HALL: {e}")
                    break

            now = time.ticks_ms()
            if time.ticks_diff(now, last_ping_ms) >= ping_interval_ms:
                last_ping_ms = now
                try:
                    log_event("send PING")
                    ws_send_ping(sock)
                    log_event("PING sent")
                except OSError as e:
                    print(f"Keepalive failed: {e}")
                    break

            if time.ticks_diff(now, last_pong_ms) >= pong_timeout_ms:
                log_event(f"PONG timeout — reconnecting (age={time.ticks_diff(now, last_pong_ms)}ms)")
                break

            dbg(f"[dbg] loop ok | pong_age={time.ticks_diff(now, last_pong_ms)}ms")
            time.sleep(0.02)

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

    init_hall_sensor()

    server_ip = load_server_config()
    if not server_ip:
        print("No server IP configured. Create server_config.json with {\"server_ip\": \"x.x.x.x\"}")
        return

    print(f"Server: {server_ip}:{SERVER_PORT}")

    while True:
        stop_motor()
        print(f"\nConnecting to server {server_ip}:{SERVER_PORT}...")
        run_client(server_ip)
        print("Reconnecting in 5 seconds...")
        time.sleep(5)


if __name__ == "__main__":
    main()
import wifi
import socket
import sys
import time
import errno
import ujson
import binascii
import hashlib
import struct
import urandom
from machine import Pin
from machine import PWM

# ============================================================
# CONFIGURATION
# ============================================================

SERVER_PORT = 8765
WS_PATH = "/"

led_pin = "P5_3"
pwm_pin = "P9_7"
reverser_pin = "P9_6"
hall_pin = "P9_0"  # TODO: set to your actual HALL sensor pin
hall_debounce_ms = 200  # ignore repeat triggers within this window

debug_enabled = True
debug_interval_ms = 2000  # rate-limit debug prints

# ============================================================
# HARDWARE GLOBALS
# ============================================================

is_led_on = True
pwm = PWM(pwm_pin, freq=1000, duty_u16=0)
reverser = Pin(reverser_pin, Pin.OUT)
led = None
hall_triggered = False
last_hall_ms = 0
last_debug_ms = 0

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
# WEBSOCKET CLIENT
# ============================================================

MAGIC_WS = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _ws_key():
    raw = bytes([urandom.getrandbits(8) for _ in range(16)])
    return binascii.b2a_base64(raw).strip()


def _ws_accept(key_b64: bytes) -> str:
    accept_src = key_b64.decode() + MAGIC_WS
    sha1 = hashlib.sha1(accept_src.encode()).digest()
    return binascii.b2a_base64(sha1).strip().decode()


def ws_handshake(sock, host, port, path="/"):
    key = _ws_key()
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key.decode()}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.send(req.encode())

    sock.settimeout(5.0)
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(512)
        if not chunk:
            break
        data += chunk

    if b"101" not in data:
        print("Handshake failed:", data)
        return False

    expected = _ws_accept(key)
    if expected.encode() not in data:
        print("Handshake accept mismatch")

    print("WebSocket handshake complete")
    return True


def ws_send(sock, opcode, payload=b""):
    fin = 0x80
    mask_bit = 0x80
    length = len(payload)
    header = bytearray()
    header.append(fin | (opcode & 0x0F))

    if length < 126:
        header.append(mask_bit | length)
    elif length < 65536:
        header.append(mask_bit | 126)
        header.extend(struct.pack(">H", length))
    else:
        header.append(mask_bit | 127)
        header.extend(length.to_bytes(8, "big"))

    mask = bytes([urandom.getrandbits(8) for _ in range(4)])
    header.extend(mask)

    masked = bytearray(length)
    for i in range(length):
        masked[i] = payload[i] ^ mask[i % 4]

    sock.send(header + masked)


def ws_send_text(sock, text: str):
    ws_send(sock, 0x1, text.encode())


def ws_send_ping(sock, payload=b""):
    ws_send(sock, 0x9, payload)


def ws_send_pong(sock, payload=b""):
    ws_send(sock, 0xA, payload)


class WsBuffer:
    def __init__(self):
        self.buf = bytearray()

    def feed(self, data: bytes):
        self.buf.extend(data)

    def pop_frame(self):
        if len(self.buf) < 2:
            return None
        b1 = self.buf[0]
        b2 = self.buf[1]
        opcode = b1 & 0x0F
        masked = (b2 & 0x80) != 0
        length = b2 & 0x7F
        idx = 2

        if length == 126:
            if len(self.buf) < idx + 2:
                return None
            length = struct.unpack(">H", bytes(self.buf[idx:idx + 2]))[0]
            idx += 2
        elif length == 127:
            if len(self.buf) < idx + 8:
                return None
            length = int.from_bytes(self.buf[idx:idx + 8], "big")
            idx += 8

        if masked:
            if len(self.buf) < idx + 4:
                return None
            mask = self.buf[idx:idx + 4]
            idx += 4
        else:
            mask = None

        if len(self.buf) < idx + length:
            return None

        payload = bytes(self.buf[idx:idx + length])
        del self.buf[:idx + length]

        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

        return opcode, payload


def connect_ws(server_ip):
    try:
        addr = socket.getaddrinfo(server_ip, SERVER_PORT)[0][-1]
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(addr)
        print(f"TCP connected to {server_ip}:{SERVER_PORT}")

        if not ws_handshake(sock, server_ip, SERVER_PORT, WS_PATH):
            sock.close()
            return None, None

        sock.settimeout(0.1)

        ws_send_text(sock, "HELLO:MODEL")
        print("Sent: HELLO:MODEL")

        wsbuf = WsBuffer()
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < 5000:
            try:
                chunk = sock.recv(512)
                if chunk:
                    wsbuf.feed(chunk)
            except OSError as e:
                if e.args[0] in (errno.EAGAIN, 11, errno.ETIMEDOUT):
                    pass
                else:
                    print(f"Handshake recv error: {e}")
                    break

            while True:
                frame = wsbuf.pop_frame()
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == 0x1:
                    msg = payload.decode().strip()
                    print(f"Received: {msg}")
                    if msg == "ACK":
                        print("Server acknowledged connection")
                        return sock, wsbuf
                elif opcode == 0x9:
                    ws_send_pong(sock, payload)
                elif opcode == 0xA:
                    pass

            time.sleep(0.02)

        print("No ACK received")
        sock.close()
        return None, None

    except Exception as e:
        print(f"Connection error: {e}")
        try:
            sock.close()
        except:
            pass
        return None, None


def handle_command(line_str):
    if line_str.startswith("SPEED:"):
        toggle_led()
        try:
            value = float(line_str.split(":")[1])
            set_speed(value)
        except (IndexError, ValueError):
            print(f"Invalid SPEED format: {line_str}")
    elif line_str == "STOP":
        stop_motor()
    else:
        print(f"Unknown command: {line_str}")


def run_client(server_ip):
    global hall_triggered

    sock, wsbuf = connect_ws(server_ip)
    if sock is None:
        return False

    print("Ready! Listening for commands from server...\n")

    last_ping_ms = time.ticks_ms()
    last_pong_ms = time.ticks_ms()
    ping_interval_ms = 3000
    pong_timeout_ms = 8000

    def dbg(msg):
        global last_debug_ms
        if not debug_enabled:
            return
        now = time.ticks_ms()
        if time.ticks_diff(now, last_debug_ms) >= debug_interval_ms:
            last_debug_ms = now
            print(f"[{now}ms] {msg}")

    def log_event(msg):
        now = time.ticks_ms()
        print(f"[{now}ms] {msg}")

    try:
        while True:
            try:
                chunk = sock.recv(512)
                if chunk:
                    wsbuf.feed(chunk)
            except OSError as e:
                if e.args[0] in (errno.EAGAIN, 11, errno.ETIMEDOUT):
                    pass
                else:
                    print(f"Socket error: {e}")
                    break

            while True:
                frame = wsbuf.pop_frame()
                if frame is None:
                    break
                opcode, payload = frame

                if opcode == 0x1:  # text
                    msg = payload.decode().strip()
                    print(f"Received: {msg}")
                    handle_command(msg)
                elif opcode == 0x9:  # ping
                    ws_send_pong(sock, payload)
                elif opcode == 0xA:  # pong
                    last_pong_ms = time.ticks_ms()
                    log_event("PONG received")
                elif opcode == 0x8:  # close
                    print("Server closed connection")
                    return False

            if hall_triggered:
                hall_triggered = False
                stop_motor()
                try:
                    log_event("send HALL")
                    ws_send_text(sock, "HALL")
                    log_event("HALL sent")
                except OSError as e:
                    print(f"Failed to send HALL: {e}")
                    break

            now = time.ticks_ms()
            if time.ticks_diff(now, last_ping_ms) >= ping_interval_ms:
                last_ping_ms = now
                try:
                    log_event("send PING")
                    ws_send_ping(sock)
                    log_event("PING sent")
                except OSError as e:
                    print(f"Keepalive failed: {e}")
                    break

            if time.ticks_diff(now, last_pong_ms) >= pong_timeout_ms:
                log_event(f"PONG timeout — reconnecting (age={time.ticks_diff(now, last_pong_ms)}ms)")
                break

            dbg(f"[dbg] loop ok | pong_age={time.ticks_diff(now, last_pong_ms)}ms")
            time.sleep(0.02)

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

    init_hall_sensor()

    server_ip = load_server_config()
    if not server_ip:
        print("No server IP configured. Create server_config.json with {\"server_ip\": \"x.x.x.x\"}")
        return

    print(f"Server: {server_ip}:{SERVER_PORT}")

    while True:
        stop_motor()
        print(f"\nConnecting to server {server_ip}:{SERVER_PORT}...")
        run_client(server_ip)
        print("Reconnecting in 5 seconds...")
        time.sleep(5)


if __name__ == "__main__":
    main()import wifi
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
        import wifi
        import socket
        import sys
        import time
        import errno
        import ujson
        import binascii
        import hashlib
        import struct
        import urandom
        from machine import Pin
        from machine import PWM

        # ============================================================
        # CONFIGURATION
        # ============================================================

        SERVER_PORT = 8765
        WS_PATH = "/"

        led_pin = "P5_3"
        pwm_pin = "P9_7"
        reverser_pin = "P9_6"
        hall_pin = "P9_0"  # TODO: set to your actual HALL sensor pin
        hall_debounce_ms = 200  # ignore repeat triggers within this window

        debug_enabled = True
        debug_interval_ms = 2000  # rate-limit debug prints

        # ============================================================
        # HARDWARE GLOBALS
        # ============================================================

        is_led_on = True
        pwm = PWM(pwm_pin, freq=1000, duty_u16=0)
        reverser = Pin(reverser_pin, Pin.OUT)
        led = None
        hall_triggered = False
        last_hall_ms = 0
        last_debug_ms = 0

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
        # WEBSOCKET CLIENT
        # ============================================================

        MAGIC_WS = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


        def _ws_key():
            raw = bytes([urandom.getrandbits(8) for _ in range(16)])
            return binascii.b2a_base64(raw).strip()


        def _ws_accept(key_b64: bytes) -> str:
            accept_src = key_b64.decode() + MAGIC_WS
            sha1 = hashlib.sha1(accept_src.encode()).digest()
            return binascii.b2a_base64(sha1).strip().decode()


        def ws_handshake(sock, host, port, path="/"):
            key = _ws_key()
            req = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key.decode()}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                "\r\n"
            )
            sock.send(req.encode())

            sock.settimeout(5.0)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = sock.recv(512)
                if not chunk:
                    break
                data += chunk

            if b"101" not in data:
                print("Handshake failed:", data)
                return False

            # Optional: verify Sec-WebSocket-Accept
            expected = _ws_accept(key)
            if expected.encode() not in data:
                print("Handshake accept mismatch")
                # Still proceed; some servers may not echo in same buffer

            print("WebSocket handshake complete")
            return True


        def ws_send(sock, opcode, payload=b""):
            fin = 0x80
            mask_bit = 0x80
            length = len(payload)
            header = bytearray()
            header.append(fin | (opcode & 0x0F))

            if length < 126:
                header.append(mask_bit | length)
            elif length < 65536:
                header.append(mask_bit | 126)
                header.extend(struct.pack(">H", length))
            else:
                header.append(mask_bit | 127)
                header.extend(length.to_bytes(8, "big"))

            mask = bytes([urandom.getrandbits(8) for _ in range(4)])
            header.extend(mask)

            masked = bytearray(length)
            for i in range(length):
                masked[i] = payload[i] ^ mask[i % 4]

            sock.send(header + masked)


        def ws_send_text(sock, text: str):
            ws_send(sock, 0x1, text.encode())


        def ws_send_ping(sock, payload=b""):
            ws_send(sock, 0x9, payload)


        def ws_send_pong(sock, payload=b""):
            ws_send(sock, 0xA, payload)


        class WsBuffer:
            def __init__(self):
                self.buf = bytearray()

            def feed(self, data: bytes):
                self.buf.extend(data)

            def pop_frame(self):
                if len(self.buf) < 2:
                    return None
                b1 = self.buf[0]
                b2 = self.buf[1]
                opcode = b1 & 0x0F
                masked = (b2 & 0x80) != 0
                length = b2 & 0x7F
                idx = 2

                if length == 126:
                    if len(self.buf) < idx + 2:
                        return None
                    length = struct.unpack(">H", bytes(self.buf[idx:idx + 2]))[0]
                    idx += 2
                elif length == 127:
                    if len(self.buf) < idx + 8:
                        return None
                    length = int.from_bytes(self.buf[idx:idx + 8], "big")
                    idx += 8

                if masked:
                    if len(self.buf) < idx + 4:
                        return None
                    mask = self.buf[idx:idx + 4]
                    idx += 4
                else:
                    mask = None

                if len(self.buf) < idx + length:
                    return None

                payload = bytes(self.buf[idx:idx + length])
                del self.buf[:idx + length]

                if mask:
                    payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

                return opcode, payload


        def connect_ws(server_ip):
            try:
                addr = socket.getaddrinfo(server_ip, SERVER_PORT)[0][-1]
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect(addr)
                print(f"TCP connected to {server_ip}:{SERVER_PORT}")

                if not ws_handshake(sock, server_ip, SERVER_PORT, WS_PATH):
                    sock.close()
                    return None, None

                # Short timeout for periodic loop
                sock.settimeout(0.1)

                # Identify as model
                ws_send_text(sock, "HELLO:MODEL")
                print("Sent: HELLO:MODEL")

                # Wait for ACK
                wsbuf = WsBuffer()
                start = time.ticks_ms()
                while time.ticks_diff(time.ticks_ms(), start) < 5000:
                    try:
                        chunk = sock.recv(512)
                        if chunk:
                            wsbuf.feed(chunk)
                    except OSError as e:
                        if e.args[0] in (errno.EAGAIN, 11, errno.ETIMEDOUT):
                            pass
                        else:
                            print(f"Handshake recv error: {e}")
                            break

                    while True:
                        frame = wsbuf.pop_frame()
                        if frame is None:
                            break
                        opcode, payload = frame
                        if opcode == 0x1:
                            msg = payload.decode().strip()
                            print(f"Received: {msg}")
                            if msg == "ACK":
                                print("Server acknowledged connection")
                                return sock, wsbuf
                        elif opcode == 0x9:
                            ws_send_pong(sock, payload)
                        elif opcode == 0xA:
                            pass

                    time.sleep(0.02)

                print("No ACK received")
                sock.close()
                return None, None

            except Exception as e:
                print(f"Connection error: {e}")
                try:
                    sock.close()
                except:
                    pass
                return None, None


        def handle_command(line_str):
            if line_str.startswith("SPEED:"):
                toggle_led()
                try:
                    value = float(line_str.split(":")[1])
                    set_speed(value)
                except (IndexError, ValueError):
                    print(f"Invalid SPEED format: {line_str}")
            elif line_str == "STOP":
                stop_motor()
            else:
                print(f"Unknown command: {line_str}")


        def run_client(server_ip):
            global hall_triggered

            sock, wsbuf = connect_ws(server_ip)
            if sock is None:
                return False

            print("Ready! Listening for commands from server...\n")

            last_ping_ms = time.ticks_ms()
            last_pong_ms = time.ticks_ms()
            ping_interval_ms = 3000
            pong_timeout_ms = 8000

            def dbg(msg):
                global last_debug_ms
                if not debug_enabled:
                    return
                now = time.ticks_ms()
                if time.ticks_diff(now, last_debug_ms) >= debug_interval_ms:
                    last_debug_ms = now
                    print(f"[{now}ms] {msg}")

            def log_event(msg):
                now = time.ticks_ms()
                print(f"[{now}ms] {msg}")

            try:
                while True:
                    # --- 1. Receive frames ---
                    try:
                        chunk = sock.recv(512)
                        if chunk:
                            wsbuf.feed(chunk)
                    except OSError as e:
                        if e.args[0] in (errno.EAGAIN, 11, errno.ETIMEDOUT):
                            pass
                        else:
                            print(f"Socket error: {e}")
                            break

                    while True:
                        frame = wsbuf.pop_frame()
                        if frame is None:
                            break
                        opcode, payload = frame

                        if opcode == 0x1:  # text
                            msg = payload.decode().strip()
                            print(f"Received: {msg}")
                            handle_command(msg)
                        elif opcode == 0x9:  # ping
                            ws_send_pong(sock, payload)
                        elif opcode == 0xA:  # pong
                            last_pong_ms = time.ticks_ms()
                            log_event("PONG received")
                        elif opcode == 0x8:  # close
                            print("Server closed connection")
                            return False

                    # --- 2. HALL sensor ---
                    if hall_triggered:
                        hall_triggered = False
                        stop_motor()
                        try:
                            log_event("send HALL")
                            ws_send_text(sock, "HALL")
                            log_event("HALL sent")
                        except OSError as e:
                            print(f"Failed to send HALL: {e}")
                            break

                    # --- 3. Keepalive ping ---
                    now = time.ticks_ms()
                    if time.ticks_diff(now, last_ping_ms) >= ping_interval_ms:
                        last_ping_ms = now
                        try:
                            log_event("send PING")
                            ws_send_ping(sock)
                            log_event("PING sent")
                        except OSError as e:
                            print(f"Keepalive failed: {e}")
                            break

                    if time.ticks_diff(now, last_pong_ms) >= pong_timeout_ms:
                        log_event(f"PONG timeout — reconnecting (age={time.ticks_diff(now, last_pong_ms)}ms)")
                        break

                    dbg(f"[dbg] loop ok | pong_age={time.ticks_diff(now, last_pong_ms)}ms")
                    time.sleep(0.02)

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

            init_hall_sensor()

            server_ip = load_server_config()
            if not server_ip:
                print("No server IP configured. Create server_config.json with {\"server_ip\": \"x.x.x.x\"}")
                return

            print(f"Server: {server_ip}:{SERVER_PORT}")

            while True:
                stop_motor()
                print(f"\nConnecting to server {server_ip}:{SERVER_PORT}...")
                run_client(server_ip)
                print("Reconnecting in 5 seconds...")
                time.sleep(5)


        if __name__ == "__main__":
            main()
