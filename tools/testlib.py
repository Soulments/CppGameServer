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
import weakref

# --- 패킷 (docs/protocol.md) ---------------------------------------------------

PING = 1
PONG = 2
LOGIN_REQUEST = 3
LOGIN_RESPONSE = 4
JOIN_ROOM_REQUEST = 5
JOIN_ROOM_RESPONSE = 6
PLAYER_JOINED = 7
PLAYER_LEFT = 8
MOVE_INPUT = 9
WORLD_SNAPSHOT = 10

MAX_PAYLOAD = 4096

# 서버 시뮬레이션 상수 (server/src/game/Simulation.h 와 같아야 한다)
TICK_RATE = 20
TICK_SECONDS = 1.0 / TICK_RATE
MOVE_SPEED = 5.0
ARENA_HALF_SIZE = 20.0
STEP = MOVE_SPEED * TICK_SECONDS  # 한 틱 이동 거리 0.25

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
    """서버가 timeout 안에 연결을 끊으면 걸린 시간을 돌려준다.

    timeout 은 전체 제한 시간이다. 서버가 데이터를 계속 보내는 소켓(방 안의 스냅샷)에서도
    제한 시간이 지나면 실패해야 해서, 수신 한 번마다가 아니라 마감 시각으로 센다.
    """
    start = time.time()
    deadline = start + timeout
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise AssertionError(f"server did not close the connection within {timeout}s")
        sock.settimeout(remaining)
        try:
            if sock.recv(4096) == b"":
                return time.time() - start
        except ConnectionResetError:
            return time.time() - start
        except socket.timeout:
            raise AssertionError(f"server did not close the connection within {timeout}s")


def expect_no_packet(sock, wait=0.4, ignore=()):
    """wait 동안 서버가 ignore 에 든 타입 외에는 아무것도 보내지 않아야 한다.

    방에 입장한 소켓은 매 틱 스냅샷이 오므로 ignore=(WORLD_SNAPSHOT,) 를 넘긴다.
    """
    stream = stream_for(sock)
    deadline = time.time() + wait
    while True:
        packet = stream.read_packet(max(0.0, deadline - time.time()))
        if packet is None:
            return
        if packet[0] not in ignore:
            raise AssertionError(f"unexpected packet from server: type={packet[0]} payload={packet[1]!r}")


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


def field_float(number, value):
    """float(32비트) 필드. 값이 0.0 이면 proto3 규칙대로 생략한다 (NaN 은 0 이 아니므로 포함)."""
    if value == 0.0:
        return b""
    return varint((number << 3) | 5) + struct.pack("<f", value)


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
        elif wire == 5:  # 32비트 고정 길이 (float, fixed32). 원본 4바이트를 돌려준다
            value = data[i : i + 4]
            assert len(value) == 4, "truncated fixed32"
            i += 4
        else:
            raise ValueError(f"unsupported wire type {wire}")
        fields.setdefault(number, []).append(value)
    return fields


def get_varint(fields, number):
    return fields.get(number, [0])[-1]


def get_float(fields, number):
    return struct.unpack("<f", fields[number][-1])[0] if number in fields else 0.0


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


def move_input(seq, dir_x, dir_z):
    return pack(MOVE_INPUT, field_varint(1, seq) + field_float(2, dir_x) + field_float(3, dir_z))


def parse_snapshot(payload):
    """WorldSnapshot 을 (tick, [{id, x, z, seq}, ...]) 로 해석한다."""
    f = decode_message(payload)
    players = []
    for raw in f.get(2, []):
        pf = decode_message(raw)
        players.append(
            {
                "id": get_varint(pf, 1),
                "x": get_float(pf, 2),
                "z": get_float(pf, 3),
                "seq": get_varint(pf, 4),
            }
        )
    return get_varint(f, 1), players


class Stream:
    """소켓에서 패킷을 하나씩 읽는다. 시간 제한으로 중간에 끊겨도 받은 바이트를 보관해서 스트림이 깨지지 않는다."""

    def __init__(self, sock):
        self.sock = sock
        self.buf = b""

    def read_packet(self, timeout):
        """timeout 초 안에 완성된 패킷이 오면 (type, payload), 아니면 None. 연결이 끊기면 ConnectionError."""
        deadline = time.time() + timeout
        while True:
            if len(self.buf) >= 4:
                size, ptype = struct.unpack("<HH", self.buf[:4])
                if len(self.buf) >= 4 + size:
                    payload = self.buf[4 : 4 + size]
                    self.buf = self.buf[4 + size :]
                    return ptype, payload
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                return None
            if not chunk:
                raise ConnectionError("connection closed by server")
            self.buf += chunk


_streams = weakref.WeakKeyDictionary()


def stream_for(sock):
    """소켓마다 Stream 을 하나만 유지한다 (버퍼에 남은 패킷을 잃지 않으려면 같은 객체로 계속 읽어야 한다)."""
    stream = _streams.get(sock)
    if stream is None:
        stream = Stream(sock)
        _streams[sock] = stream
    return stream


def recv_skipping(sock_or_stream, skip=(WORLD_SNAPSHOT,), timeout=3.0):
    """skip 에 든 타입(기본: 틱마다 오는 스냅샷)을 건너뛰고 다음 패킷을 돌려준다.

    방에 입장한 소켓에서 응답/알림을 읽을 때 쓴다. 같은 소켓은 이 함수(또는 stream_for)로만 읽어야 한다.
    """
    stream = sock_or_stream if isinstance(sock_or_stream, Stream) else stream_for(sock_or_stream)
    deadline = time.time() + timeout
    while True:
        packet = stream.read_packet(max(0.0, deadline - time.time()))
        if packet is None:
            raise socket.timeout("no packet within %.1fs" % timeout)
        if packet[0] not in skip:
            return packet


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
