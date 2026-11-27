#!/usr/bin/env python3
"""M3 서버 시뮬레이션 통합 테스트: 틱 주기, 이동 입력, 스냅샷, 속도/경계 제한, 입력 규칙, 폭주 방어.

사용법:
    python3 tools/test_m3.py --server build/cppgameserver
    python3 tools/test_m3.py --server build/Release/cppgameserver.exe   (Windows)

기준 값(server/src/game/Simulation.h): 20Hz 틱, 속도 5 unit/s (한 틱 0.25), 아레나 [-20, 20], 스폰 4곳.
"""

import argparse
import itertools
import os
import sys
import threading
import time
from collections import namedtuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testlib import (  # noqa: E402
    ARENA_HALF_SIZE,
    PING,
    PLAYER_JOINED,
    PLAYER_LEFT,
    PONG,
    RESULT_OK,
    STEP,
    MOVE_INPUT,
    WORLD_SNAPSHOT,
    connect,
    expect_closed,
    expect_no_packet,
    join_room,
    login,
    move_input,
    pack,
    parse_player_joined,
    parse_player_left,
    parse_snapshot,
    run_suite,
    stream_for,
)

IDLE_TIMEOUT = 10  # 스냅샷만 받는 테스트 클라이언트가 유휴로 끊기지 않게 넉넉하게
Snap = namedtuple("Snap", "t tick players")

_names = itertools.count(1)
_rooms = itertools.count(200)  # 테스트마다 다른 방 번호를 쓴다


def new_room():
    return next(_rooms)


def get_player(snapshot, player_id):
    for p in snapshot.players:
        if p["id"] == player_id:
            return p
    raise AssertionError(f"player {player_id} not in snapshot {snapshot}")


class Client:
    """로그인하고 (선택) 방에 입장한 테스트 클라이언트. 스냅샷을 읽고 알림을 기록한다."""

    def __init__(self, port, room=None):
        self.sock = connect(port)
        result, self.player = login(self.sock, "t%d" % next(_names))
        assert result == RESULT_OK, result
        self.joined = []  # PLAYER_JOINED 로 받은 플레이어
        self.left = []  # PLAYER_LEFT 로 받은 player_id
        self._seq = 0
        if room is not None:
            result, _, _ = join_room(self.sock, room)
            assert result == RESULT_OK, result
        self.stream = stream_for(self.sock)

    @property
    def id(self):
        return self.player[0]

    def send_input(self, dir_x, dir_z, seq=None):
        if seq is None:
            self._seq += 1
            seq = self._seq
        else:
            self._seq = max(self._seq, seq)
        self.sock.sendall(move_input(seq, dir_x, dir_z))
        return seq

    def iter_snapshots(self, duration):
        """duration 초 동안 도착한 스냅샷을 차례로 돌려준다. 알림 패킷은 self.joined / self.left 에 기록한다."""
        end = time.time() + duration
        while True:
            remaining = end - time.time()
            if remaining <= 0:
                return
            packet = self.stream.read_packet(remaining)
            if packet is None:
                return
            now = time.time()
            ptype, payload = packet
            if ptype == WORLD_SNAPSHOT:
                tick, players = parse_snapshot(payload)
                yield Snap(now, tick, players)
            elif ptype == PLAYER_JOINED:
                self.joined.append(parse_player_joined(payload))
            elif ptype == PLAYER_LEFT:
                self.left.append(parse_player_left(payload))
            elif ptype == PONG:
                pass
            else:
                raise AssertionError(f"unexpected packet type {ptype}")

    def wait_snapshot(self, predicate, timeout=3.0):
        for snap in self.iter_snapshots(timeout):
            if predicate(snap):
                return snap
        raise AssertionError(f"condition not reached within {timeout}s")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class Clients:
    """with 문으로 여러 클라이언트를 쓰고 끝나면 모두 닫는다."""

    def __init__(self, *clients):
        self.clients = clients

    def __enter__(self):
        return self.clients

    def __exit__(self, *exc):
        for c in self.clients:
            c.close()


def displacements(c, seq, duration):
    """입력 seq 가 적용된 연속 스냅샷 사이의 (dx, dz) 목록. 각 쌍은 정확히 한 틱 간격이어야 한다."""
    snaps = [s for s in c.iter_snapshots(duration) if get_player(s, c.id)["seq"] == seq]
    result = []
    for a, b in zip(snaps, snaps[1:]):
        assert b.tick - a.tick == 1, (a.tick, b.tick)
        pa, pb = get_player(a, c.id), get_player(b, c.id)
        result.append((pb["x"] - pa["x"], pb["z"] - pa["z"]))
    return result


def assert_all_close(values, expected, eps=1e-3):
    assert len(values) >= 8, f"too few samples: {len(values)}"
    for dx, dz in values:
        assert abs(dx - expected[0]) < eps and abs(dz - expected[1]) < eps, (dx, dz, expected)


# --- 틱과 스냅샷 -----------------------------------------------------------------


def test_snapshot_cadence(port):
    with Clients(Client(port, new_room())) as (c,):
        snaps = list(c.iter_snapshots(1.5))
        assert 25 <= len(snaps) <= 35, len(snaps)  # 20Hz x 1.5s = 30
        ticks = [s.tick for s in snaps]
        assert all(b - a == 1 for a, b in zip(ticks, ticks[1:])), ticks  # 틱 번호는 1씩 증가
        interval = (snaps[-1].t - snaps[0].t) / (len(snaps) - 1)
        assert 0.040 <= interval <= 0.060, interval  # 평균 50ms
        assert all([p["id"] for p in s.players] == [c.id] for s in snaps)


def test_spawn_positions_are_distinct(port):
    room = new_room()
    with Clients(*[Client(port, room) for _ in range(4)]) as cs:
        snap = cs[0].wait_snapshot(lambda s: len(s.players) == 4)
        assert [p["id"] for p in snap.players] == [c.id for c in cs]  # 입장 순서
        positions = {(p["x"], p["z"]) for p in snap.players}
        assert len(positions) == 4, positions
        for p in snap.players:
            assert abs(p["x"]) < ARENA_HALF_SIZE and abs(p["z"]) < ARENA_HALF_SIZE


def test_spawn_slot_is_reused_after_leave(port):
    room = new_room()
    a, b = Client(port, room), Client(port, room)
    with Clients(a, b) as _:
        snap = a.wait_snapshot(lambda s: len(s.players) == 2)
        b_spawn = (get_player(snap, b.id)["x"], get_player(snap, b.id)["z"])
        b.close()
        a.wait_snapshot(lambda s: len(s.players) == 1)

        c = Client(port, room)  # B 가 쓰던 자리가 비어 있으니 거기에 배치되어야 한다
        with Clients(c) as _:
            snap = c.wait_snapshot(lambda s: len(s.players) == 2)
            c_pos = (get_player(snap, c.id)["x"], get_player(snap, c.id)["z"])
            a_pos = (get_player(snap, a.id)["x"], get_player(snap, a.id)["z"])
            assert c_pos == b_spawn, (c_pos, b_spawn)
            assert c_pos != a_pos


def test_snapshots_only_for_same_room(port):
    a, b = Client(port, new_room()), Client(port, new_room())
    with Clients(a, b) as _:
        for c in (a, b):
            snaps = list(c.iter_snapshots(0.5))
            assert snaps
            assert all([p["id"] for p in s.players] == [c.id] for s in snaps)


# --- 이동 ------------------------------------------------------------------------


def test_move_distance_per_tick(port):
    with Clients(Client(port, new_room())) as (c,):
        c.wait_snapshot(lambda s: True)
        seq = c.send_input(1, 0)
        assert_all_close(displacements(c, seq, 1.5), (STEP, 0.0))  # 한 틱에 정확히 0.25


def test_direction_is_clamped_and_normalized(port):
    with Clients(Client(port, new_room())) as (c,):
        c.wait_snapshot(lambda s: True)

        seq = c.send_input(100, 0)  # 크기를 부풀려도 속도는 그대로
        assert_all_close(displacements(c, seq, 0.7), (STEP, 0.0))

        seq = c.send_input(3, 4)  # (0.6, 0.8) 로 정규화되어 이동 거리는 여전히 0.25
        assert_all_close(displacements(c, seq, 0.7), (STEP * 0.6, STEP * 0.8))

        seq = c.send_input(0.5, 0)  # 1 이하의 입력은 그대로 (천천히 이동)
        assert_all_close(displacements(c, seq, 0.7), (STEP * 0.5, 0.0))

        seq = c.send_input(1e30, 0)  # 오버플로 위험이 있는 값도 정상 속도
        assert_all_close(displacements(c, seq, 0.7), (STEP, 0.0))

        seq = c.send_input(0, 0)  # 정지
        assert_all_close(displacements(c, seq, 0.7), (0.0, 0.0))


def test_arena_bounds(port):
    with Clients(Client(port, new_room())) as (c,):
        first = c.wait_snapshot(lambda s: True)
        start_x = get_player(first, c.id)["x"]
        start_z = get_player(first, c.id)["z"]
        c.send_input(-1, 0)
        snaps = list(c.iter_snapshots(4.2))  # 스폰 x=-5 에서 -20 까지 약 3초
        xs = [get_player(s, c.id)["x"] for s in snaps]
        assert min(xs) >= -ARENA_HALF_SIZE - 1e-4, min(xs)  # 경계를 넘지 않는다
        assert abs(xs[-1] - (-ARENA_HALF_SIZE)) < 1e-4, xs[-1]  # 경계에서 멈춘다
        assert all(b <= a + 1e-6 for a, b in zip(xs, xs[1:]))  # 뒤로 튀지 않는다
        assert all(abs(get_player(s, c.id)["z"] - start_z) < 1e-4 for s in snaps)  # 다른 축은 그대로
        assert start_x > xs[-1]


def test_stale_duplicate_and_invalid_inputs_are_ignored(port):
    with Clients(Client(port, new_room())) as (c,):
        c.send_input(1, 0, seq=5)
        c.wait_snapshot(lambda s: get_player(s, c.id)["seq"] == 5)

        c.send_input(-1, 0, seq=3)  # 오래된 번호
        c.send_input(0, 1, seq=5)  # 같은 번호(중복/재전송)
        c.send_input(float("nan"), 0, seq=6)  # NaN
        c.send_input(float("inf"), 0, seq=7)  # 무한대
        snaps = list(c.iter_snapshots(0.6))
        assert snaps
        assert all(get_player(s, c.id)["seq"] == 5 for s in snaps)  # 어느 것도 반영되지 않았다
        first, last = get_player(snaps[0], c.id), get_player(snaps[-1], c.id)
        assert last["x"] - first["x"] > 0.5  # 계속 +x 로 이동 중
        assert abs(last["z"] - first["z"]) < 1e-4

        c.send_input(0, 0, seq=8)  # 이후의 유효한 입력은 정상 반영
        c.wait_snapshot(lambda s: get_player(s, c.id)["seq"] == 8)


def test_players_see_each_other_move_and_leave(port):
    room = new_room()
    a, b = Client(port, room), Client(port, room)
    with Clients(a, b) as _:
        snap = b.wait_snapshot(lambda s: len(s.players) == 2)
        a_x0 = get_player(snap, a.id)["x"]
        b_x0 = get_player(snap, b.id)["x"]

        a.send_input(1, 0)
        snap = b.wait_snapshot(lambda s: get_player(s, a.id)["x"] > a_x0 + 1.0)  # B 가 A 의 이동을 본다
        assert abs(get_player(snap, b.id)["x"] - b_x0) < 1e-4  # B 는 움직이지 않았다

        a.close()
        b.wait_snapshot(lambda s: len(s.players) == 1)
        assert a.id in b.left  # 퇴장 알림이 먼저 오고 이후 스냅샷에서 빠진다


# --- 입력 규칙과 방어 ------------------------------------------------------------


def test_input_before_joining_a_room_is_ignored(port):
    s = connect(port)
    try:
        assert login(s, "t%d" % next(_names))[0] == RESULT_OK
        s.sendall(move_input(1, 1, 0))  # 방에 들어가기 전: 오류 응답도 없이 무시
        s.sendall(pack(PING, b"x"))
        assert stream_for(s).read_packet(2) == (PONG, b"x")  # 연결은 정상이고 응답은 Pong 뿐
        expect_no_packet(s, 0.3)  # 방에 없으므로 스냅샷도 오지 않는다
    finally:
        s.close()


def test_input_flood_disconnects(port):
    with Clients(Client(port, new_room())) as (c,):
        flood = b"".join(move_input(i + 1, 1, 0) for i in range(3000))
        try:
            c.sock.sendall(flood)
        except (BrokenPipeError, ConnectionError):
            pass  # 서버가 먼저 끊은 경우
        # 유휴 타임아웃(10초)이 아니라 폭주 방어 때문에 바로 끊겨야 한다
        elapsed = expect_closed(c.sock, 2)
        assert elapsed < 2, elapsed


def test_malformed_move_input_disconnects(port):
    for payload in (b"\xff\xff", b"\x0a\x05ab", b"\x15\x00\x00"):  # 잘못된 태그, 잘린 필드, 잘린 float
        with Clients(Client(port, new_room())) as (c,):
            c.sock.sendall(pack(MOVE_INPUT, payload))
            expect_closed(c.sock, 2)  # 스냅샷이 계속 오는 소켓이어도 2초 안에 끊겨야 한다


# --- 부하 ------------------------------------------------------------------------


def test_many_rooms_keep_ticking(port):
    # 5개 방 x 4명이 모두 이동 중일 때도 틱이 한 틱씩 이어지고 방마다 4명이 보인다
    clients = []
    for r in range(5):
        room = new_room()
        clients += [Client(port, room) for _ in range(4)]
    results = {}
    errors = []

    def worker(c):
        try:
            c.send_input(0.3, 0.1)
            results[c.id] = list(c.iter_snapshots(1.5))
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    with Clients(*clients) as _:
        threads = [threading.Thread(target=worker, args=(c,)) for c in clients]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, errors[:3]
        for c in clients:
            snaps = results[c.id]
            assert 22 <= len(snaps) <= 35, (c.id, len(snaps))
            ticks = [s.tick for s in snaps]
            assert all(b - a == 1 for a, b in zip(ticks, ticks[1:])), ticks
            assert all(len(s.players) == 4 for s in snaps[3:]), [len(s.players) for s in snaps]


TESTS = [
    test_snapshot_cadence,
    test_spawn_positions_are_distinct,
    test_spawn_slot_is_reused_after_leave,
    test_snapshots_only_for_same_room,
    test_move_distance_per_tick,
    test_direction_is_clamped_and_normalized,
    test_arena_bounds,
    test_stale_duplicate_and_invalid_inputs_are_ignored,
    test_players_see_each_other_move_and_leave,
    test_input_before_joining_a_room_is_ignored,
    test_input_flood_disconnects,
    test_malformed_move_input_disconnects,
    test_many_rooms_keep_ticking,
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True, help="서버 실행 파일 경로")
    args = parser.parse_args()
    return run_suite(args.server, IDLE_TIMEOUT, TESTS, "M3 movement")


if __name__ == "__main__":
    sys.exit(main())
