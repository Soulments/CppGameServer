#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "net/PacketHandler.h"
#include "net/Session.h"

namespace game {

constexpr std::size_t kMaxRoomPlayers = 4;
constexpr std::uint32_t kMaxRoomId = 1000;
constexpr std::size_t kMaxNicknameBytes = 16;

// 로그인과 방 입장/퇴장을 처리한다. 모든 호출이 io_context 스레드 1개에서 순차 실행되므로 잠금이 필요 없다.
class GameHandler : public net::PacketHandler {
public:
    bool OnPacket(net::Session& session, std::uint16_t type, const std::uint8_t* data,
                  std::size_t size) override;
    void OnSessionClosed(net::Session& session) override;

private:
    struct Room {
        std::vector<std::shared_ptr<net::Session>> members;  // 입장 순서
    };

    bool HandleLogin(net::Session& session, const std::uint8_t* data, std::size_t size);
    bool HandleJoinRoom(net::Session& session, const std::uint8_t* data, std::size_t size);
    void LeaveRoom(net::Session& session);

    static bool IsValidNickname(const std::string& nickname);

    std::uint64_t nextPlayerId_ = 1;
    std::unordered_set<std::string> nicknamesInUse_;
    std::unordered_map<std::uint32_t, Room> rooms_;
};

}  // namespace game
