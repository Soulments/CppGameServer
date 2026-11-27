# iocp-echo

Windows IOCP(I/O Completion Port)의 동작을 직접 확인해 보는 학습용 에코 서버입니다.
메인 서버(`server/`)는 Asio를 사용하며, 이 샘플은 Asio가 Windows에서 내부적으로 감싸는
IOCP 모델을 이해하기 위해 따로 만들었습니다. `server/`의 코드와는 독립적입니다.

> 상태: GitHub Actions(windows-latest, MSVC)에서 빌드와 `test_echo.py` 통과

## 구조

```
main 스레드        accept() 루프. 새 소켓을 완료 포트에 연결하고 첫 WSARecv 를 건다.
워커 스레드 N개    GetQueuedCompletionStatus 로 완료 패킷을 받아 처리한다.
Session            OVERLAPPED + 소켓 + 버퍼. 세션당 비동기 작업은 항상 1개.
```

동작 흐름:

```
WSARecv 완료 -> 받은 바이트를 그대로 WSASend -> WSASend 완료 -> 다시 WSARecv ...
```

- 0바이트 수신 또는 오류 완료 시 세션을 닫고 메모리를 해제합니다.
- WSASend가 일부만 전송되는 경우를 대비해 남은 바이트를 이어서 보냅니다.
- 종료는 워커 수만큼 `PostQueuedCompletionStatus(nullptr)` 를 보내서 처리합니다.

## 빌드 (Windows, C++17)

Visual Studio에서 "폴더 열기"로 이 폴더를 열거나, 명령줄에서:

```bash
cmake -S samples/iocp-echo -B build-iocp
cmake --build build-iocp --config Release
```

## 실행과 테스트

```bash
build-iocp/Release/iocp_echo.exe 9000
```

PowerShell에서 에코 확인:

```powershell
$c = New-Object Net.Sockets.TcpClient('127.0.0.1', 9000)
$s = $c.GetStream()
$w = New-Object IO.StreamWriter($s); $w.AutoFlush = $true
$r = New-Object IO.StreamReader($s)
$w.WriteLine('hello'); $r.ReadLine()
$c.Close()
```

## 알려진 한계 (샘플 범위 밖)

- 종료 시점에 남아 있는 세션은 정리하지 않습니다.
- accept는 블로킹 `accept()` 를 쓰고, `AcceptEx` 는 사용하지 않습니다.
- 버퍼 풀, 세션 관리, 패킷 경계 처리(스트림 재조립)는 구현하지 않았습니다.
- 한 연결에 대해 한 번에 하나의 작업만 걸기 때문에 송신 큐가 없습니다.
