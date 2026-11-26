# proto

패킷 정의(.proto) 원본을 두는 곳입니다. 서버(C++)와 클라이언트(C#)가 같은 정의를 공유합니다.

- 직렬화 방식(protobuf vs FlatBuffers) 결정 후 정의를 추가합니다.
- C++ 코드는 서버 CMake 빌드에서 생성하고, C# 코드는 생성 스크립트로 만들어
  `client-unity/Assets/Scripts/Generated/`에 커밋합니다 (Unity는 빌드 중 protoc를 실행할 수 없음).
