#pragma once

#include <chrono>
#include <cstdint>
#include <memory>
#include <unordered_map>

#include <asio.hpp>

#include "net/Session.h"

namespace net {

// 접속을 받고 세션을 관리한다.
class Server {
public:
    Server(asio::io_context& io, std::uint16_t port, std::chrono::seconds idleTimeout);

    void Start();
    void Stop();  // 새 접속을 막고 모든 세션을 닫는다.

    std::size_t SessionCount() const { return sessions_.size(); }

private:
    void Accept();
    void OnSessionClosed(std::uint64_t sessionId);

    asio::io_context& io_;
    asio::ip::tcp::acceptor acceptor_;
    std::chrono::seconds idleTimeout_;
    std::uint64_t nextSessionId_ = 1;
    std::unordered_map<std::uint64_t, std::shared_ptr<Session>> sessions_;
};

}  // namespace net
