#!/usr/bin/env python3
"""M1 통합 테스트: 서버 프로세스를 직접 띄우고 TCP 클라이언트로 동작을 검증한다.

사용법:
    python3 tools/test_m1.py --server build/cppgameserver
    python3 tools/test_m1.py --server build/Release/cppgameserver.exe   (Windows)

패킷 형식은 docs/protocol.md 참고: [payloadSize u16][type u16][payload] (little-endian)
"""

import argparse
import os
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

PING = 1
PONG = 2
MAX_PAYLOAD = 4096
IDLE_TIMEOUT = 2  # 테스트용으로 짧게 설정한 서버의 유휴 타임아웃(초)


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


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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


def connect(port):
    s = socket.create_connection(("127.0.0.1", port), timeout=3)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s


# --- 테스트 케이스 -------------------------------------------------------------


def test_two_clients_hold_connection(port):
    """완료 기준: 클라 2개가 유휴 타임아웃보다 오래 동시에 접속을 유지한다."""
    a, b = connect(port), connect(port)
    try:
        start = time.time()
        seq = 0
        while time.time() - start < IDLE_TIMEOUT * 2 + 1:  # 타임아웃의 2배 이상
            for name, sock in (("A", a), ("B", b)):
                payload = f"{name}-{seq}".encode()
                sock.sendall(pack(PING, payload))
                ptype, body = recv_packet(sock)
                assert ptype == PONG and body == payload, (name, ptype, body)
            seq += 1
            time.sleep(0.5)
    finally:
        a.close()
        b.close()


def test_idle_client_is_disconnected(port):
    s = connect(port)
    try:
        elapsed = expect_closed(s, IDLE_TIMEOUT + 3)
        assert elapsed >= IDLE_TIMEOUT - 0.3, f"closed too early: {elapsed:.2f}s"
    finally:
        s.close()


def test_oversized_payload_is_rejected(port):
    s = connect(port)
    try:
        s.sendall(struct.pack("<HH", MAX_PAYLOAD + 1, PING))
        expect_closed(s, 2)
    finally:
        s.close()


def test_unknown_packet_type_is_rejected(port):
    s = connect(port)
    try:
        s.sendall(pack(99, b"x"))
        expect_closed(s, 2)
    finally:
        s.close()


def test_fragmented_packet(port):
    s = connect(port)
    try:
        data = pack(PING, b"fragmented")
        for i in range(len(data)):  # 1바이트씩 쪼개서 전송
            s.sendall(data[i : i + 1])
            time.sleep(0.01)
        assert recv_packet(s) == (PONG, b"fragmented")
    finally:
        s.close()


def test_coalesced_packets(port):
    s = connect(port)
    try:
        s.sendall(pack(PING, b"one") + pack(PING, b"two") + pack(PING, b""))
        assert recv_packet(s) == (PONG, b"one")
        assert recv_packet(s) == (PONG, b"two")
        assert recv_packet(s) == (PONG, b"")
    finally:
        s.close()


def test_max_size_payload(port):
    s = connect(port)
    try:
        payload = bytes(i % 251 for i in range(MAX_PAYLOAD))
        s.sendall(pack(PING, payload))
        assert recv_packet(s, timeout=5) == (PONG, payload)
    finally:
        s.close()


def test_abrupt_disconnect_does_not_affect_others(port):
    healthy = connect(port)
    try:
        broken = connect(port)
        broken.sendall(struct.pack("<H", 10))  # 헤더를 절반만 보내고 끊는다
        broken.close()
        time.sleep(0.2)

        healthy.sendall(pack(PING, b"still-alive"))
        assert recv_packet(healthy) == (PONG, b"still-alive")

        fresh = connect(port)  # 이후 새 접속도 정상 처리
        fresh.sendall(pack(PING, b"fresh"))
        assert recv_packet(fresh) == (PONG, b"fresh")
        fresh.close()
    finally:
        healthy.close()


def test_many_concurrent_clients(port, count=50):
    errors = []

    def worker(i):
        try:
            s = connect(port)
            for n in range(5):
                payload = f"c{i}-{n}".encode()
                s.sendall(pack(PING, payload))
                assert recv_packet(s) == (PONG, payload)
            s.close()
        except Exception as e:  # noqa: BLE001
            errors.append((i, repr(e)))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors[:3]


TESTS = [
    test_two_clients_hold_connection,
    test_idle_client_is_disconnected,
    test_oversized_payload_is_rejected,
    test_unknown_packet_type_is_rejected,
    test_fragmented_packet,
    test_coalesced_packets,
    test_max_size_payload,
    test_abrupt_disconnect_does_not_affect_others,
    test_many_concurrent_clients,
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True, help="서버 실행 파일 경로")
    args = parser.parse_args()
    if not os.path.exists(args.server):
        print(f"server binary not found: {args.server}")
        return 2

    port = free_port()
    server = ServerProcess(args.server, port, IDLE_TIMEOUT)
    failed = 0
    try:
        server.wait_ready()
        for test in TESTS:
            started = time.time()
            try:
                test(port)
                print(f"PASS  {test.__name__} ({time.time() - started:.1f}s)")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"FAIL  {test.__name__}: {e!r}")
    finally:
        code, output = server.stop()

    if code not in (0,) and sys.platform != "win32":
        failed += 1
        print(f"FAIL  graceful_shutdown: exit code {code}")
    elif sys.platform != "win32" and "server stopped" not in output:
        failed += 1
        print("FAIL  graceful_shutdown: 'server stopped' not logged")
    elif sys.platform != "win32":
        print("PASS  graceful_shutdown")

    if failed:
        print("\n--- server log ---\n" + output)
        print(f"\n{failed} test(s) failed")
        return 1
    print("\nall tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
