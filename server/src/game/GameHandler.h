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
// 한 틱(50ms) 동안 받을 수 있는 MoveInput 의 상한. 정상 클라이언트는 틱당 1~2개를 보내고,
// 네트워크 정체 뒤에 몰려 와도 이보다 훨씬 적다. 넘으면 폭주로 보고 연결을 끊는다.
constexpr int kMaxInputsPerTick = 100;

// 로그인, 방 입장/퇴장, 이동 입력을 처리하고 매 틱 이동 시뮬레이션과 스냅샷 전송을 한다.
// 모든 호출이 io_context 스레드 1개에서 순차 실행되므로 잠금이 필요 없다.
class GameHandler : public net::PacketHandler {
public:
    bool OnPacket(net::Session& session, std::uint16_t type, const std::uint8_t* data,
                  std::size_t size) override;
    void OnSessionClosed(net::Session& session) override;

    // 서버 틱 1회: 방마다 이동을 적용하고 WorldSnapshot 을 방의 모든 플레이어에게 보낸다. GameLoop 가 부른다.
    void Tick(std::uint32_t tick);

private:
    struct Room {
        std::vector<std::shared_ptr<net::Session>> members;  // 입장 순서
    };

    bool HandleLogin(net::Session& session, const std::uint8_t* data, std::size_t size);
    bool HandleJoinRoom(net::Session& session, const std::uint8_t* data, std::size_t size);
    bool HandleMoveInput(net::Session& session, const std::uint8_t* data, std::size_t size);
    void LeaveRoom(net::Session& session);

    static bool IsValidNickname(const std::string& nickname);

    std::uint32_t currentTick_ = 0;
    std::uint64_t nextPlayerId_ = 1;
    std::unordered_set<std::string> nicknamesInUse_;
    std::unordered_map<std::uint32_t, Room> rooms_;
};

}  // namespace game
