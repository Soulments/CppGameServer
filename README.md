# CppGameServer

C++ authoritative game server with Unity client (movement sync, server-side skill validation)

C++ 서버 권위(server-authoritative) 구조의 게임 서버와 Unity 클라이언트입니다. 클라이언트를 신뢰하지 않고 서버가 이동과 스킬 결과를 판정하는 구조를 직접 구현해 보는 프로젝트입니다.

> 상태: 초기 세팅 (M1 시작 전)

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

- [ ] 비동기 IO: Boost.Asio vs Windows IOCP 직접 구현
- [ ] 직렬화: protobuf vs FlatBuffers
- [ ] 클라: 전용 샌드박스 씬 (필요한 코드만 이식)

결정되면 이 목록과 `docs/`에 이유를 기록합니다.

## 폴더 구조

```
server/          C++ 서버 (CMake)
proto/           패킷 정의(.proto) 원본
client-unity/    Unity 샌드박스 클라이언트
samples/         학습용 독립 샘플 (iocp-echo: Windows IOCP 에코 서버)
docs/            패킷 정의서, 아키텍처, 트러블슈팅 로그
tools/           지연·패킷 손실 시뮬레이션 등 보조 도구
```

## 빌드 (서버)

```bash
cmake -S server -B build
cmake --build build
./build/cppgameserver
```

현재는 빌드 확인용 placeholder 입니다.
