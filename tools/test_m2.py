#!/usr/bin/env python3
"""M2 통합 테스트: 로그인, 방 입장/퇴장, 알림, 잘못된 패킷 처리를 검증한다.

사용법:
    python3 tools/test_m2.py --server build/cppgameserver
    python3 tools/test_m2.py --server build/Release/cppgameserver.exe   (Windows)

잘못된 패킷 정책 (docs/protocol.md):
  - protobuf 파싱 실패, 서버 -> 클라 전용 타입, 알 수 없는 타입  => 연결 종료
  - 파싱은 되지만 상태/값이 맞지 않는 요청                        => 오류 코드로 응답, 연결 유지
"""

import argparse
import itertools
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testlib import (  # noqa: E402
    JOIN_ROOM_RESPONSE,
    LOGIN_REQUEST,
    LOGIN_RESPONSE,
    PING,
    PLAYER_JOINED,
    PLAYER_LEFT,
    PONG,
    WORLD_SNAPSHOT,
    RESULT_DUPLICATE_NICKNAME,
    RESULT_INVALID_NICKNAME,
    RESULT_INVALID_ROOM,
    RESULT_INVALID_STATE,
    RESULT_OK,
    RESULT_ROOM_FULL,
    connect,
    expect_closed,
    expect_no_packet,
    field_string,
    join_room,
    join_room_request,
    login,
    login_request,
    pack,
    parse_join_room_response,
    parse_login_response,
    parse_player_joined,
    parse_player_left,
    recv_packet,
    recv_skipping,
    run_suite,
    JOIN_ROOM_REQUEST,
)

IDLE_TIMEOUT = 5
_counter = itertools.count(1)


def uniq(prefix="p"):
    """테스트끼리 닉네임이 겹치지 않게 한다 (16바이트 이하)."""
    return f"{prefix}{next(_counter)}"


def logged_in(port, prefix="p"):
    """접속하고 로그인한 소켓과 (player_id, nickname) 을 돌려준다."""
    s = connect(port)
    result, player = login(s, uniq(prefix))
    assert result == RESULT_OK, result
    return s, player


def close_all(*socks):
    for s in socks:
        try:
            s.close()
        except OSError:
            pass


# --- 로그인 -----------------------------------------------------------------------


def test_login_ok(port):
    s = connect(port)
    try:
        nickname = uniq("alice")
        result, player = login(s, nickname)
        assert result == RESULT_OK
        assert player is not None and player[0] > 0 and player[1] == nickname, player
    finally:
        s.close()


def test_player_ids_are_unique(port):
    a, pa = logged_in(port)
    b, pb = logged_in(port)
    try:
        assert pa[0] != pb[0], (pa, pb)
    finally:
        close_all(a, b)


def test_duplicate_nickname_and_reuse_after_disconnect(port):
    nickname = uniq("dup")
    a, b = connect(port), connect(port)
    try:
        assert login(a, nickname)[0] == RESULT_OK
        assert login(b, nickname)[0] == RESULT_DUPLICATE_NICKNAME

        a.close()  # 접속이 끊기면 닉네임이 해제된다
        time.sleep(0.3)
        assert login(b, nickname)[0] == RESULT_OK  # 같은 연결에서 다시 시도해도 된다
    finally:
        close_all(a, b)


def test_invalid_nicknames_keep_connection(port):
    s = connect(port)
    try:
        bad = ["", "x" * 17, "bad\nname", "tab\tname", "del\x7fname", "한글한글한글"]  # 마지막은 18바이트
        for nickname in bad:
            result, player = login(s, nickname)
            assert result == RESULT_INVALID_NICKNAME, (nickname, result)
            assert player is None
        # 경계값: 정확히 16바이트와 멀티바이트 문자는 허용
        assert login(s, ("n%d" % next(_counter)).ljust(16, "x"))[0] == RESULT_OK
    finally:
        s.close()


def test_multibyte_nickname_ok(port):
    s = connect(port)
    try:
        nickname = "용사" + str(next(_counter))
        result, player = login(s, nickname)
        assert result == RESULT_OK and player[1] == nickname, (result, player)
    finally:
        s.close()


def test_login_twice_is_invalid_state(port):
    s, _ = logged_in(port)
    try:
        assert login(s, uniq("again"))[0] == RESULT_INVALID_STATE
    finally:
        s.close()


def test_large_valid_message_is_handled(port):
    # payload 가 큰(4000바이트) 정상 protobuf: 거부가 아니라 값 검증 오류로 응답해야 한다
    s = connect(port)
    try:
        result, _ = login(s, "a" * 4000)
        assert result == RESULT_INVALID_NICKNAME
        assert login(s, uniq("after"))[0] == RESULT_OK
    finally:
        s.close()


# --- 방 입장/퇴장 -----------------------------------------------------------------


def test_join_before_login_is_invalid_state(port):
    s = connect(port)
    try:
        result, _, players = join_room(s, 1)
        assert result == RESULT_INVALID_STATE and players == []
    finally:
        s.close()


def test_join_room_flow_with_notifications(port):
    room = 10
    a, pa = logged_in(port, "ann")
    b, pb = logged_in(port, "bob")
    try:
        result, room_id, players = join_room(a, room)
        assert (result, room_id, players) == (RESULT_OK, room, [pa]), (result, room_id, players)

        result, room_id, players = join_room(b, room)
        assert (result, room_id) == (RESULT_OK, room)
        assert players == [pa, pb], players  # 본인 포함, 입장 순서

        ptype, payload = recv_skipping(a)  # A 는 B 의 입장을 통지받는다 (틱마다 오는 스냅샷은 건너뜀)
        assert ptype == PLAYER_JOINED and parse_player_joined(payload) == pb

        b.close()  # B 가 나가면 A 가 퇴장을 통지받는다
        ptype, payload = recv_skipping(a)
        assert ptype == PLAYER_LEFT and parse_player_left(payload) == pb[0]
    finally:
        close_all(a, b)


def test_join_room_twice_is_invalid_state(port):
    s, _ = logged_in(port)
    try:
        assert join_room(s, 11)[0] == RESULT_OK
        assert join_room(s, 12)[0] == RESULT_INVALID_STATE
    finally:
        s.close()


def test_invalid_room_ids(port):
    s, _ = logged_in(port)
    try:
        assert join_room(s, 0)[0] == RESULT_INVALID_ROOM
        assert join_room(s, 1001)[0] == RESULT_INVALID_ROOM
        assert join_room(s, 4294967295)[0] == RESULT_INVALID_ROOM
        assert join_room(s, 1000)[0] == RESULT_OK  # 경계값은 허용
    finally:
        s.close()


def test_room_full_and_slot_reuse(port):
    room = 20
    members = [logged_in(port, "m") for _ in range(4)]
    extra, _ = logged_in(port, "x")
    try:
        for sock, _ in members:
            assert join_room(sock, room)[0] == RESULT_OK
            # 앞서 입장한 멤버들이 받은 PlayerJoined 는 아래에서 비운다

        result, _, players = join_room(extra, room)
        assert result == RESULT_ROOM_FULL and players == []

        # 한 명이 나가면 자리가 생기고, 남은 멤버들은 PlayerLeft 를 받는다
        leaver_sock, leaver = members[0]
        leaver_sock.close()
        time.sleep(0.3)
        assert join_room(extra, room)[0] == RESULT_OK  # 입장 실패 후에도 같은 연결로 재시도 가능
    finally:
        close_all(extra, *[m[0] for m in members])


def test_rooms_are_isolated(port):
    a, _ = logged_in(port)
    b, pb = logged_in(port)
    c, pc = logged_in(port)
    try:
        assert join_room(a, 30)[0] == RESULT_OK
        assert join_room(b, 31)[0] == RESULT_OK
        assert join_room(c, 31)[0] == RESULT_OK

        ptype, payload = recv_skipping(b)  # 같은 방의 B 는 통지를 받고
        assert ptype == PLAYER_JOINED and parse_player_joined(payload) == pc
        # 다른 방의 A 는 (자기 방 스냅샷 외에는) 아무것도 받지 않는다
        expect_no_packet(a, ignore=(WORLD_SNAPSHOT,))
    finally:
        close_all(a, b, c)


def test_room_is_recreated_after_everyone_leaves(port):
    a, _ = logged_in(port)
    try:
        assert join_room(a, 40)[0] == RESULT_OK
    finally:
        a.close()
    time.sleep(0.3)
    b, pb = logged_in(port)
    try:
        result, _, players = join_room(b, 40)
        assert result == RESULT_OK and players == [pb]  # 이전 멤버가 남아 있지 않다
    finally:
        b.close()


def test_many_players_across_rooms(port):
    # 20명이 연결을 유지한 채 5개 방(방당 4명)에 입장한다. 방마다 인원이 1, 2, 3, 4로 늘어야 한다.
    socks = []
    try:
        for i in range(20):
            s, player = logged_in(port, "w")
            socks.append(s)
            room = 100 + i % 5
            result, room_id, players = join_room(s, room)
            assert (result, room_id) == (RESULT_OK, room), (i, result)
            assert len(players) == i // 5 + 1, (i, players)
            assert players[-1] == player
    finally:
        close_all(*socks)


def test_concurrent_logins_with_same_nickname(port):
    # 여러 연결이 동시에 같은 닉네임으로 로그인하면 정확히 한 명만 성공해야 한다
    nickname = uniq("race")
    results = []
    lock = threading.Lock()

    def worker():
        s = connect(port)
        try:
            r = login(s, nickname)[0]
            with lock:
                results.append(r)
            time.sleep(0.3)  # 성공한 쪽이 연결을 유지해서 닉네임이 계속 점유되게 한다
        finally:
            s.close()

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(RESULT_OK) == 1, results
    assert results.count(RESULT_DUPLICATE_NICKNAME) == 9, results


# --- 연결 계층과의 상호작용 ---------------------------------------------------------


def test_ping_between_game_packets(port):
    s = connect(port)
    try:
        s.sendall(pack(PING, b"1"))
        assert recv_packet(s) == (PONG, b"1")
        assert login(s, uniq("pinger"))[0] == RESULT_OK
        s.sendall(pack(PING, b"2"))
        assert recv_packet(s) == (PONG, b"2")
        assert join_room(s, 50)[0] == RESULT_OK
    finally:
        s.close()


def test_pipelined_requests_answered_in_order(port):
    s = connect(port)
    try:
        # 로그인과 방 입장과 Ping 을 한 번에 보낸다 (TCP 에서 한 덩어리로 도착할 수 있다)
        s.sendall(login_request(uniq("pipe")) + join_room_request(51) + pack(PING, b"z"))
        ptype, payload = recv_skipping(s)
        assert ptype == LOGIN_RESPONSE and parse_login_response(payload)[0] == RESULT_OK
        ptype, payload = recv_skipping(s)
        assert ptype == JOIN_ROOM_RESPONSE and parse_join_room_response(payload)[0] == RESULT_OK
        assert recv_skipping(s) == (PONG, b"z")  # 사이에 스냅샷이 끼어들 수 있다
    finally:
        s.close()


# --- 잘못된 패킷 -----------------------------------------------------------------


def test_malformed_protobuf_disconnects(port):
    malformed_payloads = [
        (LOGIN_REQUEST, b"\xff\xff\xff\xff"),  # 잘못된 태그
        (LOGIN_REQUEST, b"\x0a\x0aab"),  # 길이 10을 선언했지만 2바이트뿐 (잘린 필드)
        (LOGIN_REQUEST, b"\x0a"),  # 길이가 없는 필드
        (JOIN_ROOM_REQUEST, b"\x08"),  # 값이 없는 varint 필드
        (JOIN_ROOM_REQUEST, b"\x08\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff"),  # 끝나지 않는 varint
    ]
    for ptype, payload in malformed_payloads:
        s = connect(port)
        try:
            s.sendall(pack(ptype, payload))
            expect_closed(s, 2)
        finally:
            s.close()


def test_invalid_utf8_nickname_disconnects(port):
    # proto3 string 은 UTF-8 이어야 한다: 파싱 단계에서 실패하므로 잘못된 패킷으로 취급
    s = connect(port)
    try:
        s.sendall(pack(LOGIN_REQUEST, field_string(1, b"\xff\xfe\xfd")))
        expect_closed(s, 2)
    finally:
        s.close()


def test_server_to_client_types_are_rejected(port):
    for ptype in (PONG, LOGIN_RESPONSE, JOIN_ROOM_RESPONSE, PLAYER_JOINED, PLAYER_LEFT, WORLD_SNAPSHOT, 99):
        s = connect(port)
        try:
            s.sendall(pack(ptype, b""))
            expect_closed(s, 2)
        finally:
            s.close()


def test_forced_disconnect_cleans_up_state(port):
    # 방에 있는 클라이언트가 잘못된 패킷을 보내 강제로 끊기면, 방과 닉네임이 정리되어야 한다
    room = 60
    a, _ = logged_in(port, "stay")
    nickname = uniq("bad")
    b = connect(port)
    try:
        assert login(b, nickname)[0] == RESULT_OK
        result, _, players = join_room(b, room)
        assert result == RESULT_OK
        pb = players[-1]
        assert join_room(a, room)[0] == RESULT_OK
        ptype, payload = recv_skipping(b)  # B 는 A 의 입장을 통지받는다
        assert ptype == PLAYER_JOINED

        b.sendall(pack(LOGIN_REQUEST, b"\xff\xff"))  # 잘못된 패킷
        expect_closed(b, 2)

        ptype, payload = recv_skipping(a)  # A 는 B 의 퇴장을 통지받고
        assert ptype == PLAYER_LEFT and parse_player_left(payload) == pb[0]

        c = connect(port)  # 닉네임도 다시 쓸 수 있다
        try:
            assert login(c, nickname)[0] == RESULT_OK
        finally:
            c.close()
    finally:
        close_all(a, b)


TESTS = [
    test_login_ok,
    test_player_ids_are_unique,
    test_duplicate_nickname_and_reuse_after_disconnect,
    test_invalid_nicknames_keep_connection,
    test_multibyte_nickname_ok,
    test_login_twice_is_invalid_state,
    test_large_valid_message_is_handled,
    test_join_before_login_is_invalid_state,
    test_join_room_flow_with_notifications,
    test_join_room_twice_is_invalid_state,
    test_invalid_room_ids,
    test_room_full_and_slot_reuse,
    test_rooms_are_isolated,
    test_room_is_recreated_after_everyone_leaves,
    test_many_players_across_rooms,
    test_concurrent_logins_with_same_nickname,
    test_ping_between_game_packets,
    test_pipelined_requests_answered_in_order,
    test_malformed_protobuf_disconnects,
    test_invalid_utf8_nickname_disconnects,
    test_server_to_client_types_are_rejected,
    test_forced_disconnect_cleans_up_state,
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True, help="서버 실행 파일 경로")
    args = parser.parse_args()
    return run_suite(args.server, IDLE_TIMEOUT, TESTS, "M2 protocol")


if __name__ == "__main__":
    sys.exit(main())
