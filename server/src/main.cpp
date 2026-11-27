#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <exception>

#include <asio.hpp>

#include "game/GameHandler.h"
#include "net/Log.h"
#include "net/Server.h"

namespace {

constexpr long kDefaultPort = 7777;
constexpr long kDefaultIdleSeconds = 10;

bool ParseNumber(const char* text, long min, long max, long& out) {
    char* end = nullptr;
    const long value = std::strtol(text, &end, 10);
    if (end == text || *end != '\0' || value < min || value > max) return false;
    out = value;
    return true;
}

}  // namespace

int main(int argc, char** argv) {
    long port = kDefaultPort;
    long idleSeconds = kDefaultIdleSeconds;

    if ((argc >= 2 && !ParseNumber(argv[1], 1, 65535, port)) ||
        (argc >= 3 && !ParseNumber(argv[2], 1, 3600, idleSeconds)) || argc > 3) {
        std::fprintf(stderr, "usage: %s [port 1-65535] [idleTimeoutSeconds 1-3600]\n", argv[0]);
        return 1;
    }

    try {
        asio::io_context io;
        game::GameHandler handler;  // Server 보다 먼저 만들어서 나중에 소멸한다
        net::Server server(io, static_cast<std::uint16_t>(port),
                           std::chrono::seconds(idleSeconds), handler);

        asio::signal_set signals(io, SIGINT, SIGTERM);
        signals.async_wait([&server](std::error_code ec, int /*signal*/) {
            if (ec) return;
            net::Log("shutdown requested");
            server.Stop();
        });

        server.Start();
        io.run();  // 스레드 1개. 모든 완료 핸들러가 이 스레드에서 순차 실행된다.
        net::Log("server stopped");
    } catch (const std::exception& e) {
        std::fprintf(stderr, "fatal: %s\n", e.what());
        return 1;
    }
    return 0;
}
