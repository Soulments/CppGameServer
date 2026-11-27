"""통합 테스트 공용 헬퍼: 서버 프로세스 실행, 패킷 송수신, protobuf 와이어 인코딩/디코딩.

protobuf 라이브러리 없이 와이어 형식을 직접 다룬다. 의존성을 줄이고, 서버(C++ protobuf)와
독립적으로 형식을 검증하는 효과도 있다. 지원 범위는 이 프로젝트가 쓰는 필드 종류(varint, 길이 지정)뿐이다.
"""

import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time

# --- 패킷 (docs/protocol.md) ---------------------------------------------------

PING = 1
PONG = 2
LOGIN_REQUEST = 3
LOGIN_RESPONSE = 4
JOIN_ROOM_REQUEST = 5
JOIN_ROOM_RESPONSE = 6
PLAYER_JOINED = 7
PLAYER_LEFT = 8

MAX_PAYLOAD = 4096

RESULT_OK = 0
RESULT_INVALID_STATE = 1
RESULT_INVALID_NICKNAME = 2
RESULT_DUPLICATE_NICKNAME = 3
RESULT_INVALID_ROOM = 4
RESULT_ROOM_FULL = 5


def pack(ptype, payload=b""):
    return struct.pack("<HH", len(payload), ptype) + payload


def recv_exact(sock, n, timeout=3.0):
    sock.settimeout(timeout)
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("connection closed by server")
        data += chunk
    return data


def recv_packet(sock, timeout=3.0):
    size, ptype = struct.unpack("<HH", recv_exact(sock, 4, timeout))
    return ptype, recv_exact(sock, size, timeout) if size else b""


def expect_closed(sock, timeout):
    """서버가 timeout 안에 연결을 끊으면 걸린 시간을 돌려준다."""
    start = time.time()
    sock.settimeout(timeout)
    try:
        while True:
            if sock.recv(4096) == b"":
                return time.time() - start
    except ConnectionResetError:
        return time.time() - start
    except socket.timeout:
        raise AssertionError(f"server did not close the connection within {timeout}s")


def expect_no_packet(sock, wait=0.4):
    """wait 동안 서버가 아무것도 보내지 않아야 한다."""
    sock.settimeout(wait)
    try:
        data = sock.recv(4096)
    except socket.timeout:
        return
    raise AssertionError(f"unexpected data from server: {data!r}")


def connect(port):
    s = socket.create_connection(("127.0.0.1", port), timeout=3)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- protobuf 와이어 형식 ------------------------------------------------------


def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def field_varint(number, value):
    """값이 0 이면 proto3 규칙대로 생략한다."""
    return varint(number << 3) + varint(value) if value else b""


def field_bytes(number, data):
    return varint((number << 3) | 2) + varint(len(data)) + data if data else b""


def field_string(number, text):
    return field_bytes(number, text if isinstance(text, bytes) else text.encode("utf-8"))


def decode_message(data):
    """{필드 번호: [값, ...]} 로 디코딩한다. varint 는 int, 길이 지정 필드는 bytes."""
    fields = {}
    i = 0
    while i < len(data):
        key = 0
        shift = 0
        while True:
            b = data[i]
            i += 1
            key |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                break
        number, wire = key >> 3, key & 7
        if wire == 0:
            value = 0
            shift = 0
            while True:
                b = data[i]
                i += 1
                value |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    break
        elif wire == 2:
            length = 0
            shift = 0
            while True:
                b = data[i]
                i += 1
                length |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    break
            value = data[i : i + length]
            assert len(value) == length, "truncated field"
            i += length
        else:
            raise ValueError(f"unsupported wire type {wire}")
        fields.setdefault(number, []).append(value)
    return fields


def get_varint(fields, number):
    return fields.get(number, [0])[-1]


# --- 메시지 (proto/game.proto) --------------------------------------------------


def login_request(nickname):
    return pack(LOGIN_REQUEST, field_string(1, nickname))


def join_room_request(room_id):
    return pack(JOIN_ROOM_REQUEST, field_varint(1, room_id))


def parse_player_info(data):
    f = decode_message(data)
    return get_varint(f, 1), f.get(2, [b""])[-1].decode("utf-8")


def parse_login_response(payload):
    f = decode_message(payload)
    result = get_varint(f, 1)
    player = parse_player_info(f[2][-1]) if 2 in f else None
    return result, player


def parse_join_room_response(payload):
    f = decode_message(payload)
    players = [parse_player_info(p) for p in f.get(3, [])]
    return get_varint(f, 1), get_varint(f, 2), players


def parse_player_joined(payload):
    return parse_player_info(decode_message(payload)[1][-1])


def parse_player_left(payload):
    return get_varint(decode_message(payload), 1)


def login(sock, nickname):
    """로그인하고 (result, player) 를 돌려준다."""
    sock.sendall(login_request(nickname))
    ptype, payload = recv_packet(sock)
    assert ptype == LOGIN_RESPONSE, ptype
    return parse_login_response(payload)


def join_room(sock, room_id):
    """방에 입장하고 (result, room_id, players) 를 돌려준다."""
    sock.sendall(join_room_request(room_id))
    ptype, payload = recv_packet(sock)
    assert ptype == JOIN_ROOM_RESPONSE, ptype
    return parse_join_room_response(payload)


# --- 서버 프로세스 ---------------------------------------------------------------


class ServerProcess:
    def __init__(self, path, port, idle):
        self.port = port
        self.log = tempfile.NamedTemporaryFile(mode="w+", suffix=".log", delete=False)
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        self.proc = subprocess.Popen(
            [path, str(port), str(idle)], stdout=self.log, stderr=subprocess.STDOUT, **kwargs
        )

    def wait_ready(self, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("server exited early:\n" + self.output())
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.5).close()
                return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("server did not start:\n" + self.output())

    def output(self):
        self.log.flush()
        with open(self.log.name, encoding="utf-8", errors="replace") as f:
            return f.read()

    def stop(self):
        """정상 종료를 요청하고 (exit code, 로그)를 돌려준다."""
        if self.proc.poll() is None:
            if sys.platform == "win32":
                self.proc.terminate()
            else:
                self.proc.send_signal(signal.SIGINT)
        try:
            code = self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            code = self.proc.wait()
            return -999, self.output()
        return code, self.output()


def run_suite(server_path, idle_timeout, tests, title):
    """서버를 띄워 tests 를 차례로 실행하고 종료 코드를 돌려준다."""
    import os

    if not os.path.exists(server_path):
        print(f"server binary not found: {server_path}")
        return 2

    port = free_port()
    server = ServerProcess(server_path, port, idle_timeout)
    failed = 0
    try:
        server.wait_ready()
        for test in tests:
            started = time.time()
            try:
                test(port)
                print(f"PASS  {test.__name__} ({time.time() - started:.1f}s)")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"FAIL  {test.__name__}: {e!r}")
    finally:
        code, output = server.stop()

    if sys.platform != "win32":
        if code != 0:
            failed += 1
            print(f"FAIL  graceful_shutdown: exit code {code}")
        elif "server stopped" not in output:
            failed += 1
            print("FAIL  graceful_shutdown: 'server stopped' not logged")
        else:
            print("PASS  graceful_shutdown")

    if failed:
        print("\n--- server log ---\n" + output)
        print(f"\n{failed} test(s) failed ({title})")
        return 1
    print(f"\nall tests passed ({title})")
    return 0
