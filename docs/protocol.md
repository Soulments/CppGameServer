# 패킷 프로토콜 (M2)

서버(C++)와 Unity 클라이언트(C#)가 공유하는 통신 규격입니다. 메시지 정의의 원본은 [`proto/game.proto`](../proto/game.proto)이고,
이 문서는 전송 형식, 패킷 종류, 상태 규칙, 오류 처리 정책을 설명합니다.

## 1. 전송 형식

TCP는 바이트 스트림이라 메시지 경계가 없으므로, 모든 패킷 앞에 고정 길이 헤더를 붙입니다.
수신 측은 헤더 4바이트를 먼저 정확히 읽고, 헤더가 알려 주는 길이만큼 payload를 읽습니다.

```
+-------------------+------------+--------------------+
| payloadSize (u16) | type (u16) | payload (N bytes)  |
+-------------------+------------+--------------------+
   little-endian       little-endian
```

| 필드 | 크기 | 설명 |
| --- | --- | --- |
| payloadSize | 2바이트 | 헤더를 제외한 payload 길이. 최대 4096 |
| type | 2바이트 | 패킷 종류 (아래 표) |
| payload | payloadSize 바이트 | Ping/Pong은 임의 바이트, 나머지는 protobuf 메시지 (없으면 0바이트) |

- 헤더의 정수는 **리틀엔디안**으로 한 바이트씩 직렬화합니다. 구조체를 그대로 `send`하지 않아서 컴파일러 패딩이나 엔디안 차이의 영향을 받지 않습니다.
- 한 번의 `recv`에 패킷이 일부만 오거나 여러 개가 붙어서 와도 위 규칙으로 올바르게 분리합니다 (`tools/test_m1.py`의 fragmented / coalesced 테스트).
- 요청과 응답 사이에도 다른 패킷(Ping/Pong, 다른 플레이어의 알림)이 끼어들 수 있으므로, 클라이언트는 `type`으로 구분해서 처리해야 합니다.

예: 닉네임 `ann`으로 로그인 요청 (`LoginRequest{nickname:"ann"}`)

```
05 00 03 00   0a 03 61 6e 6e
└ payloadSize=5, type=3 ┘ └ protobuf: field 1(string) len 3 "ann" ┘
```

## 2. 패킷 종류

| type | 이름 | 방향 | payload |
| --- | --- | --- | --- |
| 1 | Ping | C → S | 임의 바이트 (Unity 클라이언트는 보낸 시각 8바이트를 넣음) |
| 2 | Pong | S → C | Ping의 payload를 그대로 되돌림 |
| 3 | LoginRequest | C → S | `LoginRequest` |
| 4 | LoginResponse | S → C | `LoginResponse` |
| 5 | JoinRoomRequest | C → S | `JoinRoomRequest` |
| 6 | JoinRoomResponse | S → C | `JoinRoomResponse` |
| 7 | PlayerJoined | S → 같은 방의 다른 C | `PlayerJoined` |
| 8 | PlayerLeft | S → 같은 방의 다른 C | `PlayerLeft` |

`type` 값은 서버의 `server/src/net/Packet.h`와 클라이언트의 `PacketProtocol.cs`에 같은 값으로 정의되어 있습니다.

## 3. 메시지

| 메시지 | 필드 | 설명 |
| --- | --- | --- |
| `PlayerInfo` | `uint64 player_id = 1`, `string nickname = 2` | 플레이어 정보 |
| `LoginRequest` | `string nickname = 1` | 로그인 요청 |
| `LoginResponse` | `ResultCode result = 1`, `PlayerInfo player = 2` | `player`는 `RESULT_OK`일 때만 채워짐 |
| `JoinRoomRequest` | `uint32 room_id = 1` | 입장할 방 번호 |
| `JoinRoomResponse` | `ResultCode result = 1`, `uint32 room_id = 2`, `repeated PlayerInfo players = 3` | 성공 시 **본인을 포함한** 방 전체 인원 (입장 순서) |
| `PlayerJoined` | `PlayerInfo player = 1` | 같은 방에 새로 들어온 플레이어 |
| `PlayerLeft` | `uint64 player_id = 1` | 같은 방에서 나간 플레이어 |

### ResultCode

| 값 | 이름 | 의미 |
| --- | --- | --- |
| 0 | `RESULT_OK` | 성공 |
| 1 | `RESULT_INVALID_STATE` | 지금 상태에서 할 수 없는 요청 |
| 2 | `RESULT_INVALID_NICKNAME` | 닉네임 규칙 위반 |
| 3 | `RESULT_DUPLICATE_NICKNAME` | 이미 접속 중인 닉네임 |
| 4 | `RESULT_INVALID_ROOM` | 방 번호가 허용 범위 밖 |
| 5 | `RESULT_ROOM_FULL` | 방 정원 초과 |

## 4. 규칙과 한도

| 항목 | 규칙 |
| --- | --- |
| payload 최대 크기 | 4096바이트 |
| 닉네임 | 1~16**바이트**, 제어 문자(0x00~0x1F, 0x7F) 금지, UTF-8. 한글은 글자당 3바이트라 최대 5자 |
| 닉네임 중복 | 접속 중인 닉네임과 같으면 거부. 접속이 끊기면 해제 |
| 방 번호 | 1~1000. 방은 처음 입장할 때 만들어지고, 마지막 사람이 나가면 사라짐 |
| 방 정원 | 4명 |
| 유휴 타임아웃 | 기본 10초. 어떤 패킷이든 받으면 다시 시작. 클라이언트는 기본 3초 간격으로 Ping을 보냄 |
| 송신 큐 상한 | 1024개 이상 적체되면 느린 클라이언트로 보고 연결 종료 |

## 5. 상태와 허용되는 요청

연결마다 서버가 상태를 관리합니다.

```
[Connected] --LoginRequest(성공)--> [LoggedIn] --JoinRoomRequest(성공)--> [InRoom]
```

| 요청 | Connected | LoggedIn | InRoom |
| --- | --- | --- | --- |
| LoginRequest | 허용 | `RESULT_INVALID_STATE` | `RESULT_INVALID_STATE` |
| JoinRoomRequest | `RESULT_INVALID_STATE` | 허용 | `RESULT_INVALID_STATE` |

- 방에서 나가는 요청은 아직 없습니다. 연결을 끊으면 방에서 나간 것으로 처리하고, 같은 방의 다른 플레이어에게 `PlayerLeft`를 보냅니다.
- 연결이 어떤 이유로든 닫히면(정상 종료, 오류, 타임아웃, 잘못된 패킷) 방과 닉네임이 정리됩니다.

## 6. 잘못된 패킷 처리 정책

두 종류를 구분합니다.

| 구분 | 예 | 서버 동작 |
| --- | --- | --- |
| **프로토콜 위반** (해석할 수 없음) | protobuf 파싱 실패(잘린 필드, 잘못된 태그, 유효하지 않은 UTF-8), 알 수 없는 `type`, 클라이언트가 보낼 수 없는 `type`(S → C 전용), payload가 4096바이트 초과 | **연결 종료** |
| **요청 위반** (해석은 되지만 값/상태가 맞지 않음) | 로그인 전 방 입장, 중복 로그인, 잘못된 닉네임, 범위 밖 방 번호, 정원 초과, 중복 닉네임 | **오류 코드로 응답**, 연결 유지 |

이유: 해석할 수 없는 데이터는 버그이거나 악의적인 클라이언트일 가능성이 높고, 이후 스트림의 경계도 신뢰할 수 없어서 끊는 편이 안전합니다.
반대로 값이 틀린 요청은 정상 클라이언트도 보낼 수 있으므로(예: 닉네임 중복) 사용자에게 이유를 알려 줍니다.
클라이언트도 같은 정책을 따라, 서버가 보낸 payload를 해석하지 못하면 연결을 끊습니다 (`LobbyClient`).

## 7. 서버 실행 옵션

```
cppgameserver [port 1-65535] [idleTimeoutSeconds 1-3600]
```

기본값은 포트 7777, 유휴 타임아웃 10초입니다.

## 8. 검증

- `tools/test_m1.py`: 연결 계층 (프레이밍, 하트비트, 유휴 종료, 크기 제한)
- `tools/test_m2.py`: 로그인, 방 입장/퇴장, 알림, 정원, 잘못된 패킷 정책. 프로토콜 라이브러리 없이 와이어 형식을 직접 인코딩하므로 서버의 protobuf 구현과 독립적으로 형식을 검증합니다.
