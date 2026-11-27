# client-tests

Unity 에디터 없이 클라이언트 로직을 검증하는 .NET 8 프로젝트입니다. `client-unity/Assets/Scripts`의 소스를 복사하지 않고 그대로 컴파일합니다.

```bash
# 보간기와 입력 전송 규칙의 단위 테스트 (서버 불필요)
dotnet run --project tools/client-tests -c Release -- unit

# 실행 중인 서버에 클라이언트 2개를 붙인 통합 테스트
./build/cppgameserver 7777 10 &
dotnet run --project tools/client-tests -c Release -- e2e 7777
```

## 검증하는 것과 못 하는 것

- 검증함: `SnapshotInterpolator`(보간, 외삽, 시계 추정), `MoveInputSender`, `GameClient`/`LobbyClient`와 C++ 서버 사이의 실제 통신
- 컴파일만 함: `GameNetworkManager`, `SyncDemoController`. `UnityStubs.cs`의 최소 `UnityEngine` 스텁으로 문법과 타입만 검사하며, 실제 Unity API와 시그니처가 다를 수 있습니다. Unity 에디터에서의 동작은 검증하지 않습니다.
