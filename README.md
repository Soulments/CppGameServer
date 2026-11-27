# CppGameServer

C++ authoritative game server with Unity client (movement sync, server-side skill validation)

C++ 서버 권위(server-authoritative) 구조의 게임 서버와 Unity 클라이언트입니다. 클라이언트를 신뢰하지 않고 서버가 이동과 스킬 결과를 판정하는 구조를 직접 구현해 보는 프로젝트입니다.

## 진행 상황

| 마일스톤 | 상태 |
| --- | --- |
| M1 접속 기반 | 서버와 테스트 완료 (Linux/Windows CI 통과). **Unity 에디터에서의 실제 접속 확인이 남음** |
| M2 프로토콜 | 서버, 패킷 정의서, 테스트 완료. C# 클라이언트는 .NET에서 서버와의 통신을 확인함. **Unity 에디터 확인이 남음** |
| M3 동기화 | 예정 |
| M4 스킬 검증 | 예정 |
| M5 마무리 | 예정 |

## 목표

- 비동기 IO 기반 C++ TCP 서버 구현
- protobuf 패킷 프로토콜 설계
- 룸 단위(2~4인) 이동 동기화와 클라이언트 보간
- 스킬 요청을 서버가 검증(쿨타임, 거리)하고 결과만 클라이언트에 반영

## 마일스톤

| 마일스톤 | 내용 | 완료 기준 |
| --- | --- | --- |
| M1 접속 기반 | C++ TCP 서버(비동기 IO)와 Unity 클라 접속, 하트비트, 연결 종료 처리 | 클라 2개가 동시에 접속을 유지 |
| M2 프로토콜 | protobuf 패킷 정의, 직렬화, 로그인·방 입장 | 패킷 정의서 작성, 잘못된 패킷 처리 확인 |
| M3 동기화 | 룸 단위 2~4인 이동 동기화, 서버 권위, 클라 보간 | 두 클라에서 서로의 이동이 끊김 없이 보임 |
| M4 스킬 검증 | 스킬 요청을 서버가 검증(쿨타임·거리), 결과만 클라에 반영 | 조작된 요청을 서버가 거부하는 테스트 통과 |
| M5 마무리 | 지연·패킷 손실 시뮬레이션 측정, 아키텍처 문서, 트러블슈팅 로그, 데모 영상 | 문서 + 영상 + Git 태그 |

## 범위 밖

- DB 영속화 (선택 확장)
- 매치메이킹, 라이브 운영, 배포 자동화
- 인증·보안 심화, 대규모 부하 테스트

## 기술 결정

- [x] 비동기 IO: **standalone Asio**. IOCP는 학습용 샘플(`samples/iocp-echo`)로 별도 구현해 비교
- [x] 직렬화: **protobuf 3.21.12** (C++은 lite 런타임, Unity는 Google.Protobuf)
- [x] 클라: 전용 샌드박스 씬 (필요한 코드만 이식)

선택한 이유와 포기한 것은 [docs/decisions.md](docs/decisions.md)에 정리했습니다.

## 폴더 구조

```
server/          C++ 서버 (CMake)
proto/           패킷 정의(.proto) 원본
client-unity/    Unity 샌드박스 클라이언트
samples/         학습용 독립 샘플 (iocp-echo: Windows IOCP 에코 서버)
docs/            패킷 프로토콜, 기술 결정 기록 (이후 아키텍처, 트러블슈팅 로그)
tools/           통합 테스트 (이후 지연·패킷 손실 시뮬레이션 등)
```

## 빌드와 실행 (서버)

C++17 컴파일러와 CMake 3.20 이상이 필요합니다. Asio와 protobuf는 CMake 설정 단계에서 GitHub에서 자동으로 받아 빌드합니다
(처음에는 protobuf 컴파일 때문에 몇 분 걸립니다).

```bash
cmake -S server -B build
cmake --build build --config Release
./build/cppgameserver [port] [idleTimeoutSeconds]    # 기본: 7777, 10초
```

Windows(Visual Studio)에서는 실행 파일이 `build/Release/cppgameserver.exe`에 만들어집니다.

## 테스트

서버를 직접 띄우고 TCP 클라이언트로 검증하는 통합 테스트입니다 (Python 3 필요, 추가 패키지 없음).

```bash
python3 tools/test_m1.py --server build/cppgameserver    # 연결 계층
python3 tools/test_m2.py --server build/cppgameserver    # 로그인, 방, 잘못된 패킷
```

- M1: 클라이언트 2개의 동시 접속 유지(하트비트), 유휴 연결 종료, 크기 제한, 쪼개져 오거나 붙어서 오는 패킷, 비정상 종료 후 복구, 50개 동시 접속, 정상 종료
- M2: 로그인과 닉네임 규칙·중복, 방 입장/퇴장과 알림, 정원 초과, 방 격리, 잘못된 protobuf·잘못된 방향의 패킷 처리, 강제 종료 후 상태 정리

Linux와 Windows(MSVC)에서 GitHub Actions로 자동 실행합니다.

## Unity 클라이언트

`client-unity/Assets/Scripts/Network/`에 접속 코드가 있습니다.

- `GameClient`: 접속, 수신, 하트비트. Unity API에 의존하지 않는 순수 C#
- `LobbyClient`: 로그인과 방 입장 프로토콜 (`GameClient` 위에서 동작)
- `GameNetworkManager`: 씬의 빈 GameObject에 붙이면 접속, 로그인, 방 입장을 자동으로 진행

`Assets/Plugins/Google.Protobuf/`에 protobuf C# 런타임 DLL이 들어 있고, `Assets/Scripts/Generated/Game.cs`는 `proto/game.proto`에서 생성한 코드입니다
(다시 생성하려면 `cmake --build build --target gen_proto_csharp`).

Unity 프로젝트 파일(`ProjectSettings/`, `Packages/`)은 아직 없습니다. Unity Hub로 임시 위치에 새 프로젝트를 만든 뒤
`ProjectSettings/`와 `Packages/`를 `client-unity/`로 복사하고, Unity Hub의 "Add project from disk"로 `client-unity/`를 열면 됩니다.
접속 확인은 서버를 먼저 실행한 뒤 플레이하고, 클라이언트 2개는 에디터와 빌드를 함께 실행해서 확인합니다.

## 문서

- [docs/protocol.md](docs/protocol.md): 패킷 형식, 메시지, 상태 규칙, 잘못된 패킷 처리 정책
- [docs/decisions.md](docs/decisions.md): 기술 결정과 그 이유
