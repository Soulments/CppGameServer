#pragma once

#include <array>
#include <chrono>
#include <cstdint>
#include <deque>
#include <functional>
#include <memory>
#include <string>
#include <vector>

#include <asio.hpp>

#include "net/Packet.h"

namespace net {

// 클라이언트 연결 1개. Proactor 방식(async_read / async_write 완료 핸들러)으로 동작한다.
// 현재는 io_context 스레드가 1개라서 strand 없이 안전하다. 스레드를 늘릴 때는 strand 로 감싼다.
class Session : public std::enable_shared_from_this<Session> {
public:
    using CloseCallback = std::function<void(std::uint64_t sessionId)>;

    Session(asio::ip::tcp::socket socket, std::uint64_t id,
            std::chrono::seconds idleTimeout, CloseCallback onClose);

    void Start();
    void Close(const char* reason);  // 여러 번 불러도 한 번만 처리한다.

    std::uint64_t id() const { return id_; }

private:
    void ReadHeader();
    void ReadPayload();
    void HandlePacket();

    void Send(PacketType type, const std::uint8_t* data, std::size_t size);
    void DoWrite();

    void ArmIdleTimer();

    asio::ip::tcp::socket socket_;
    asio::steady_timer idleTimer_;
    std::uint64_t id_;
    std::chrono::seconds idleTimeout_;
    CloseCallback onClose_;
    std::string peer_;
    bool closed_ = false;

    std::array<std::uint8_t, kHeaderSize> headerBuf_{};
    PacketHeader header_{};
    std::vector<std::uint8_t> payload_;

    std::deque<std::vector<std::uint8_t>> writeQueue_;
};

}  // namespace net
