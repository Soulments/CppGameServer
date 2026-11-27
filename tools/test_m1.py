#!/usr/bin/env python3
"""M1 통합 테스트: 서버 프로세스를 직접 띄우고 TCP 클라이언트로 연결 계층 동작을 검증한다.

사용법:
    python3 tools/test_m1.py --server build/cppgameserver
    python3 tools/test_m1.py --server build/Release/cppgameserver.exe   (Windows)

패킷 형식은 docs/protocol.md 참고: [payloadSize u16][type u16][payload] (little-endian)
"""

import argparse
import os
import socket
import struct
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testlib import (  # noqa: E402
    MAX_PAYLOAD,
    PING,
    PONG,
    connect,
    expect_closed,
    pack,
    recv_packet,
    run_suite,
)

IDLE_TIMEOUT = 2  # 테스트용으로 짧게 설정한 서버의 유휴 타임아웃(초)


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
    return run_suite(args.server, IDLE_TIMEOUT, TESTS, "M1 connection layer")


if __name__ == "__main__":
    sys.exit(main())
