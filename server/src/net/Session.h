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
#include "net/PacketHandler.h"

namespace google {
namespace protobuf {
class MessageLite;
}
}  // namespace google

namespace net {

// 세션에 붙는 플레이어 상태. 게임 로직(GameHandler)이 채우고 읽는다.
struct PlayerState {
    bool loggedIn = false;
    std::uint64_t playerId = 0;
    std::string nickname;
    std::uint32_t roomId = 0;  // 0 = 어느 방에도 없음

    // 이동 시뮬레이션 상태 (GameHandler 가 관리한다)
    float x = 0.0f;
    float z = 0.0f;
    float dirX = 0.0f;  // 마지막으로 받은 유효한 입력 방향 (이미 정규화/제한됨)
    float dirZ = 0.0f;
    std::uint32_t lastInputSeq = 0;
    std::size_t spawnSlot = 0;
    std::uint32_t inputTick = 0;   // inputsInTick 을 센 틱 번호
    int inputsInTick = 0;          // 그 틱 동안 받은 MoveInput 수 (폭주 감지)
};

// 클라이언트 연결 1개. Proactor 방식(async_read / async_write 완료 핸들러)으로 동작한다.
// 현재는 io_context 스레드가 1개라서 strand 없이 안전하다. 스레드를 늘릴 때는 strand 로 감싼다.
class Session : public std::enable_shared_from_this<Session> {
public:
    using CloseCallback = std::function<void(std::uint64_t sessionId)>;

    Session(asio::ip::tcp::socket socket, std::uint64_t id, std::chrono::seconds idleTimeout,
            PacketHandler& handler, CloseCallback onClose);

    void Start();
    void Close(const char* reason);  // 여러 번 불러도 한 번만 처리한다.

    // protobuf 메시지를 직렬화해서 [헤더 + payload] 패킷으로 보낸다.
    void SendMessage(PacketType type, const google::protobuf::MessageLite& message);

    std::uint64_t id() const { return id_; }
    bool IsClosed() const { return closed_; }
    PlayerState& player() { return player_; }
    const PlayerState& player() const { return player_; }

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
    PacketHandler& handler_;
    CloseCallback onClose_;
    std::string peer_;
    bool closed_ = false;
    PlayerState player_;

    std::array<std::uint8_t, kHeaderSize> headerBuf_{};
    PacketHeader header_{};
    std::vector<std::uint8_t> payload_;

    std::deque<std::vector<std::uint8_t>> writeQueue_;
};

}  // namespace net
