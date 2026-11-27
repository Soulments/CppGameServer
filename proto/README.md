# proto

서버(C++)와 클라이언트(C#)가 공유하는 패킷 정의의 원본입니다.

- [`game.proto`](game.proto): 로그인, 방 입장, 입장/퇴장 알림 메시지
- 전송 형식, 패킷 `type` 번호, 상태 규칙, 오류 처리 정책은 [`docs/protocol.md`](../docs/protocol.md)에 있습니다.

## 코드 생성

| 대상 | 방법 | 결과 |
| --- | --- | --- |
| C++ (서버) | 서버 빌드 때 CMake가 자동 생성 | `build/generated/game.pb.{h,cc}` (커밋하지 않음) |
| C# (Unity) | `cmake --build build --target gen_proto_csharp` | `client-unity/Assets/Scripts/Generated/Game.cs` (**커밋함**) |

Unity는 빌드 중에 `protoc`를 실행할 수 없어서 생성된 C# 코드를 커밋합니다.
`protoc`는 서버 빌드가 소스에서 만든 3.21.12 버전이고, Unity의 `Google.Protobuf.dll`(3.21.12)과 버전을 맞춥니다.
CI가 커밋된 C# 코드가 `game.proto`와 일치하는지 검사합니다.

## 변경 규칙

- 필드 번호는 한 번 정하면 바꾸거나 재사용하지 않습니다 (이전 클라이언트와의 호환).
- 메시지를 추가하면 `server/src/net/Packet.h`와 `PacketProtocol.cs`에 `type` 값을 같이 추가하고 `docs/protocol.md` 표를 갱신합니다.
