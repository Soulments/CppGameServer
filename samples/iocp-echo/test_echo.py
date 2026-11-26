#!/usr/bin/env python3
"""iocp_echo 동작 검증: 에코, 큰 데이터(부분 송수신), 동시 접속, 비정상 종료 후 복구.

사용법 (Windows):
    python samples/iocp-echo/test_echo.py --exe build-iocp/Release/iocp_echo.exe

이미 떠 있는 서버를 검사하려면:
    python samples/iocp-echo/test_echo.py --port 9000 --no-launch
"""

import argparse
import os
import socket
import subprocess
import sys
import threading
import time


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def connect(port):
    return socket.create_connection(("127.0.0.1", port), timeout=5)


def echo_roundtrip(sock, data):
    """data 를 보내면서 동시에 받아서, 서버가 되돌려 준 바이트를 돌려준다."""
    received = bytearray()
    error = []

    def reader():
        try:
            sock.settimeout(10)
            while len(received) < len(data):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                received.extend(chunk)
        except Exception as e:  # noqa: BLE001
            error.append(e)

    t = threading.Thread(target=reader)
    t.start()
    sock.sendall(data)
    t.join(timeout=15)
    assert not error, error
    return bytes(received)


def test_small_echo(port):
    s = connect(port)
    try:
        assert echo_roundtrip(s, b"hello iocp") == b"hello iocp"
    finally:
        s.close()


def test_repeated_echo_on_one_connection(port):
    s = connect(port)
    try:
        for i in range(50):
            msg = f"message-{i}".encode()
            assert echo_roundtrip(s, msg) == msg
    finally:
        s.close()


def test_large_payload(port):
    # 서버 버퍼(4096)보다 훨씬 큰 데이터: 여러 번의 Recv/Send 와 부분 전송 경로를 지난다.
    s = connect(port)
    try:
        data = bytes(i % 251 for i in range(1024 * 1024))
        assert echo_roundtrip(s, data) == data
    finally:
        s.close()


def test_concurrent_clients(port, count=30):
    errors = []

    def worker(i):
        try:
            s = connect(port)
            data = bytes((i + n) % 256 for n in range(20000))
            assert echo_roundtrip(s, data) == data
            s.close()
        except Exception as e:  # noqa: BLE001
            errors.append((i, repr(e)))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors[:3]


def test_abrupt_close_then_recover(port):
    broken = connect(port)
    broken.sendall(b"partial data")
    broken.close()  # 응답을 받기 전에 끊는다
    time.sleep(0.3)
    s = connect(port)
    try:
        assert echo_roundtrip(s, b"after-reset") == b"after-reset"
    finally:
        s.close()


TESTS = [
    test_small_echo,
    test_repeated_echo_on_one_connection,
    test_large_payload,
    test_concurrent_clients,
    test_abrupt_close_then_recover,
]


def wait_ready(port, proc, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError("server exited early")
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("server did not start")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", help="iocp_echo 실행 파일 경로")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-launch", action="store_true", help="이미 실행 중인 서버에 접속만 한다")
    args = parser.parse_args()

    proc = None
    port = args.port or free_port()
    if not args.no_launch:
        if not args.exe or not os.path.exists(args.exe):
            print(f"executable not found: {args.exe}")
            return 2
        proc = subprocess.Popen([args.exe, str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    failed = 0
    try:
        wait_ready(port, proc)
        for test in TESTS:
            started = time.time()
            try:
                test(port)
                print(f"PASS  {test.__name__} ({time.time() - started:.1f}s)")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"FAIL  {test.__name__}: {e!r}")
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    if failed:
        print(f"\n{failed} test(s) failed")
        return 1
    print("\nall tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
