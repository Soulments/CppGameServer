// IOCP echo server sample (Windows only, C++17)
//
// 목적: Windows IOCP(I/O Completion Port)의 동작 방식을 직접 확인한다.
// 구조: accept 전용 스레드(main) + IOCP 완료를 처리하는 워커 스레드 풀.
// 세션당 비동기 작업은 항상 1개만 걸어 둔다 (Recv -> Send -> Recv ...).

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>

#include <algorithm>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <vector>

#ifdef _MSC_VER
#pragma comment(lib, "ws2_32.lib")
#endif

namespace {

constexpr unsigned short kDefaultPort = 9000;
constexpr int kBufferSize = 4096;

enum class Op { Recv, Send };

// OVERLAPPED를 첫 멤버로 둔다. 완료 시 OVERLAPPED* 로 Session* 을 복원한다.
struct Session {
    OVERLAPPED overlapped{};
    SOCKET socket = INVALID_SOCKET;
    Op op = Op::Recv;
    char buffer[kBufferSize]{};
    WSABUF wsaBuf{};
    DWORD sendTotal = 0;  // 에코해야 할 전체 바이트
    DWORD sendDone = 0;   // 지금까지 보낸 바이트 (부분 전송 대응)
};

std::atomic<bool> g_running{true};
std::atomic<int> g_connections{0};
SOCKET g_listenSocket = INVALID_SOCKET;

BOOL WINAPI ConsoleHandler(DWORD signal) {
    if (signal == CTRL_C_EVENT || signal == CTRL_BREAK_EVENT) {
        g_running = false;
        // 블로킹 중인 accept()를 깨우기 위해 리슨 소켓을 닫는다.
        if (g_listenSocket != INVALID_SOCKET) {
            closesocket(g_listenSocket);
        }
        return TRUE;
    }
    return FALSE;
}

bool PostRecv(Session* s) {
    s->op = Op::Recv;
    s->wsaBuf.buf = s->buffer;
    s->wsaBuf.len = sizeof(s->buffer);
    DWORD flags = 0;
    ZeroMemory(&s->overlapped, sizeof(s->overlapped));
    const int rc = WSARecv(s->socket, &s->wsaBuf, 1, nullptr, &flags, &s->overlapped, nullptr);
    return rc != SOCKET_ERROR || WSAGetLastError() == WSA_IO_PENDING;
}

bool PostSend(Session* s) {
    s->op = Op::Send;
    s->wsaBuf.buf = s->buffer + s->sendDone;
    s->wsaBuf.len = s->sendTotal - s->sendDone;
    ZeroMemory(&s->overlapped, sizeof(s->overlapped));
    const int rc = WSASend(s->socket, &s->wsaBuf, 1, nullptr, 0, &s->overlapped, nullptr);
    return rc != SOCKET_ERROR || WSAGetLastError() == WSA_IO_PENDING;
}

void CloseSession(Session* s) {
    std::printf("[disconnect] socket=%llu (connections=%d)\n",
                static_cast<unsigned long long>(s->socket), --g_connections);
    closesocket(s->socket);
    delete s;
}

void WorkerLoop(HANDLE iocp) {
    for (;;) {
        DWORD transferred = 0;
        ULONG_PTR key = 0;
        OVERLAPPED* ov = nullptr;
        const BOOL ok = GetQueuedCompletionStatus(iocp, &transferred, &key, &ov, INFINITE);

        if (ov == nullptr) {
            return;  // 종료 신호 (PostQueuedCompletionStatus 로 보낸 nullptr)
        }

        Session* s = CONTAINING_RECORD(ov, Session, overlapped);

        // 실패했거나, 상대가 연결을 끊었거나(0바이트), 진전이 없으면 세션 종료.
        if (!ok || transferred == 0) {
            CloseSession(s);
            continue;
        }

        if (s->op == Op::Recv) {
            s->sendTotal = transferred;
            s->sendDone = 0;
            if (!PostSend(s)) CloseSession(s);
        } else {
            s->sendDone += transferred;
            if (s->sendDone < s->sendTotal) {
                if (!PostSend(s)) CloseSession(s);  // 남은 부분 전송
            } else if (!PostRecv(s)) {
                CloseSession(s);
            }
        }
    }
}

}  // namespace

int main(int argc, char** argv) {
    unsigned short port = kDefaultPort;
    if (argc >= 2) {
        const long p = std::strtol(argv[1], nullptr, 10);
        if (p < 1 || p > 65535) {
            std::fprintf(stderr, "usage: %s [port 1-65535]\n", argv[0]);
            return 1;
        }
        port = static_cast<unsigned short>(p);
    }

    WSADATA wsa{};
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
        std::fprintf(stderr, "WSAStartup failed\n");
        return 1;
    }

    // 오버랩드 소켓으로 만들어야 IOCP에서 쓸 수 있다. accept()된 소켓도 속성을 이어받는다.
    g_listenSocket = WSASocketW(AF_INET, SOCK_STREAM, IPPROTO_TCP, nullptr, 0, WSA_FLAG_OVERLAPPED);
    if (g_listenSocket == INVALID_SOCKET) {
        std::fprintf(stderr, "WSASocket failed: %d\n", WSAGetLastError());
        WSACleanup();
        return 1;
    }

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons(port);
    if (bind(g_listenSocket, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == SOCKET_ERROR ||
        listen(g_listenSocket, SOMAXCONN) == SOCKET_ERROR) {
        std::fprintf(stderr, "bind/listen failed: %d\n", WSAGetLastError());
        closesocket(g_listenSocket);
        WSACleanup();
        return 1;
    }

    HANDLE iocp = CreateIoCompletionPort(INVALID_HANDLE_VALUE, nullptr, 0, 0);
    if (iocp == nullptr) {
        std::fprintf(stderr, "CreateIoCompletionPort failed: %lu\n", GetLastError());
        closesocket(g_listenSocket);
        WSACleanup();
        return 1;
    }

    SetConsoleCtrlHandler(ConsoleHandler, TRUE);

    const unsigned workerCount = std::max(2u, std::thread::hardware_concurrency());
    std::vector<std::thread> workers;
    workers.reserve(workerCount);
    for (unsigned i = 0; i < workerCount; ++i) {
        workers.emplace_back(WorkerLoop, iocp);
    }

    std::printf("IOCP echo server listening on port %u (workers=%u). Ctrl+C to stop.\n",
                static_cast<unsigned>(port), workerCount);

    while (g_running) {
        SOCKET client = accept(g_listenSocket, nullptr, nullptr);
        if (client == INVALID_SOCKET) {
            if (!g_running) break;  // Ctrl+C 로 리슨 소켓이 닫힘
            std::fprintf(stderr, "accept failed: %d\n", WSAGetLastError());
            continue;
        }

        // 클라이언트 소켓을 완료 포트에 연결한다.
        if (CreateIoCompletionPort(reinterpret_cast<HANDLE>(client), iocp, 0, 0) != iocp) {
            std::fprintf(stderr, "associate failed: %lu\n", GetLastError());
            closesocket(client);
            continue;
        }

        auto* session = new Session();
        session->socket = client;
        std::printf("[connect] socket=%llu (connections=%d)\n",
                    static_cast<unsigned long long>(client), ++g_connections);

        if (!PostRecv(session)) {
            CloseSession(session);
        }
    }

    // 워커 종료: 스레드마다 nullptr 완료 패킷을 하나씩 보낸다.
    // (샘플이라 종료 시점에 남아 있는 세션은 정리하지 않는다. README의 한계 참고)
    for (size_t i = 0; i < workers.size(); ++i) {
        PostQueuedCompletionStatus(iocp, 0, 0, nullptr);
    }
    for (auto& t : workers) t.join();

    CloseHandle(iocp);
    WSACleanup();
    std::printf("server stopped.\n");
    return 0;
}
