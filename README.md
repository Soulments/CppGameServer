# CppGameServer

C++ authoritative game server with Unity client (movement sync, server-side skill validation)

C++ 서버 권위(server-authoritative) 구조의 게임 서버와 Unity 클라이언트입니다. 클라이언트를 신뢰하지 않고 서버가 이동과 스킬 결과를 판정하는 구조를 직접 구현해 보는 프로젝트입니다.

> 상태: M1 진행 중. 서버와 테스트는 구현·검증했고, Unity 프로젝트에서의 실제 접속 확인이 남아 있습니다.

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

## 기술 결정 (진행 중)

- [x] 비동기 IO: **standalone Asio** (메인 서버). IOCP는 학습용 샘플(`samples/iocp-echo`)로 별도 구현해 비교
  - Asio는 Windows에서 IOCP, Linux에서 epoll로 동작해서 같은 코드로 두 OS를 지원합니다.
  - `io_context` 1개와 스레드 1개로 시작하고, 필요해지면(M5) 스레드와 strand를 추가합니다.
  - 콜백(Proactor) 방식을 사용합니다. C++17로 충분하고 컴파일러 버전에 덜 민감합니다.
- [ ] 직렬화: protobuf vs FlatBuffers (M2)
- [x] 클라: 전용 샌드박스 씬 (필요한 코드만 이식)

결정 이유는 `docs/`에 이어서 기록합니다.

## 폴더 구조

```
server/          C++ 서버 (CMake)
proto/           패킷 정의(.proto) 원본
client-unity/    Unity 샌드박스 클라이언트
samples/         학습용 독립 샘플 (iocp-echo: Windows IOCP 에코 서버)
docs/            패킷 정의서, 아키텍처, 트러블슈팅 로그
tools/           지연·패킷 손실 시뮬레이션 등 보조 도구
```

## 빌드와 실행 (서버)

C++17 컴파일러와 CMake 3.20 이상이 필요합니다. Asio는 CMake 설정 단계에서 GitHub에서 자동으로 받습니다.

```bash
cmake -S server -B build
cmake --build build --config Release
./build/cppgameserver [port] [idleTimeoutSeconds]    # 기본: 7777, 10초
```

Windows(Visual Studio)에서는 실행 파일이 `build/Release/cppgameserver.exe`에 만들어집니다.

## 테스트

서버를 직접 띄우고 TCP 클라이언트로 검증하는 통합 테스트입니다 (Python 3 필요).

```bash
python3 tools/test_m1.py --server build/cppgameserver
```

검증 항목: 클라이언트 2개의 동시 접속 유지(하트비트), 유휴 연결 종료, 잘못된 패킷 거부,
쪼개져 오거나 붙어서 오는 패킷 처리, 비정상 종료 후 복구, 50개 동시 접속, 정상 종료.
Linux와 Windows(MSVC)에서 GitHub Actions로 자동 실행합니다.

## Unity 클라이언트

`client-unity/Assets/Scripts/Network/`에 접속 코드가 있습니다.
`GameClient`는 Unity API에 의존하지 않는 순수 C#이고, `GameNetworkManager`를 씬의 빈 GameObject에 붙이면 접속과 하트비트를 시작합니다.
Unity 프로젝트 파일(`ProjectSettings/`, `Packages/`)은 아직 없습니다. Unity Hub로 임시 위치에 새 프로젝트를 만든 뒤
`ProjectSettings/`와 `Packages/`를 `client-unity/`로 복사하고, Unity Hub의 "Add project from disk"로 `client-unity/`를 열면 됩니다.
접속 확인은 서버를 먼저 실행한 뒤 플레이하고, 클라이언트 2개는 에디터와 빌드를 함께 실행해서 확인합니다.

패킷 형식은 [docs/protocol.md](docs/protocol.md)를 참고하세요.
