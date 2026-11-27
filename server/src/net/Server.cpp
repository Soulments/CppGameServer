#include "net/Server.h"

#include <vector>

#include "net/Log.h"

namespace net {

Server::Server(asio::io_context& io, std::uint16_t port, std::chrono::seconds idleTimeout)
    : io_(io), acceptor_(io), idleTimeout_(idleTimeout) {
    const asio::ip::tcp::endpoint endpoint(asio::ip::tcp::v4(), port);
    acceptor_.open(endpoint.protocol());
#ifndef _WIN32
    // Windows 의 SO_REUSEADDR 는 다른 프로세스가 같은 포트를 가로챌 수 있어서 쓰지 않는다.
    acceptor_.set_option(asio::ip::tcp::acceptor::reuse_address(true));
#endif
    acceptor_.bind(endpoint);
    acceptor_.listen();
}

void Server::Start() {
    Log("listening on port %u (idle timeout %llds)",
        static_cast<unsigned>(acceptor_.local_endpoint().port()),
        static_cast<long long>(idleTimeout_.count()));
    Accept();
}

void Server::Stop() {
    std::error_code ec;
    acceptor_.close(ec);

    // Close() 가 OnSessionClosed 로 맵을 수정하므로 복사본을 순회한다.
    std::vector<std::shared_ptr<Session>> snapshot;
    snapshot.reserve(sessions_.size());
    for (auto& entry : sessions_) snapshot.push_back(entry.second);
    for (auto& session : snapshot) session->Close("server shutdown");
}

void Server::Accept() {
    acceptor_.async_accept([this](std::error_code ec, asio::ip::tcp::socket socket) {
        if (ec == asio::error::operation_aborted) return;  // Stop() 으로 닫힘

        if (!ec) {
            std::error_code optionError;
            socket.set_option(asio::ip::tcp::no_delay(true), optionError);

            const std::uint64_t id = nextSessionId_++;
            auto session = std::make_shared<Session>(
                std::move(socket), id, idleTimeout_,
                [this](std::uint64_t closedId) { OnSessionClosed(closedId); });
            sessions_.emplace(id, session);
            Log("[session %llu] connected (sessions=%zu)", static_cast<unsigned long long>(id),
                sessions_.size());
            session->Start();
        } else {
            Log("accept error: %s", ec.message().c_str());
        }

        Accept();
    });
}

void Server::OnSessionClosed(std::uint64_t sessionId) {
    sessions_.erase(sessionId);
    Log("[session %llu] removed (sessions=%zu)", static_cast<unsigned long long>(sessionId),
        sessions_.size());
}

}  // namespace net
