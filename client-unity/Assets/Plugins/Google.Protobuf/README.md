# Google.Protobuf (C# runtime)

서버(C++, protobuf 3.21.12)와 같은 버전의 C# 런타임입니다. `Assets/Scripts/Generated/Game.cs`가 이 라이브러리를 사용합니다.

- 출처: NuGet 패키지 `Google.Protobuf` 3.21.12, `lib/netstandard2.0/Google.Protobuf.dll`
  (https://www.nuget.org/packages/Google.Protobuf/3.21.12)
- SHA-256: `433e006bd07cf08274ee78fc5c10b3d7aee2c4a15d66ec0de1d72a2decd76e61`
- 라이선스: BSD-3-Clause (`LICENSE.txt`)
- 이 DLL은 `System.Memory` 등을 참조합니다. Unity 2021.2 이상(.NET Standard 2.1 프로필)에서 쓰는 것을 권장합니다.
  참조 오류가 나면 NuGet의 `System.Memory`, `System.Runtime.CompilerServices.Unsafe`를 함께 추가하세요.
  (이 저장소에서는 Unity 에디터에서 직접 확인하지 못했고, Mono 런타임에서 서버와 통신하는 것까지 확인했습니다.)

`proto/game.proto`를 바꾸면 C# 코드를 다시 생성하세요 (런타임과 같은 3.21.12 버전의 protoc가 쓰입니다):

```bash
cmake --build build --target gen_proto_csharp
```
