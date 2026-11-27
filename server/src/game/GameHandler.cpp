#include "game/GameHandler.h"

#include <algorithm>
#include <array>

#include "game.pb.h"
#include "game/Simulation.h"
#include "net/Log.h"
#include "net/Packet.h"

namespace game {

using net::PacketType;

namespace {

void FillPlayerInfo(cppgs::PlayerInfo* info, const net::Session& session) {
    info->set_player_id(session.player().playerId);
    info->set_nickname(session.player().nickname);
}

unsigned long long Sid(const net::Session& session) {
    return static_cast<unsigned long long>(session.id());
}

// payload 가 비어 있으면(예: 모든 필드가 기본값인 메시지) 빈 vector 의 data() 가 nullptr 일 수 있다.
// protobuf 는 이 포인터를 memcpy 에 그대로 넘기므로, nullptr 대신 항상 유효한 주소를 준다 (UBSan 지적 사항).
bool ParsePayload(google::protobuf::MessageLite& message, const std::uint8_t* data,
                  std::size_t size) {
    static const std::uint8_t kEmpty = 0;
    return message.ParseFromArray(size == 0 ? &kEmpty : data, static_cast<int>(size));
}

}  // namespace

bool GameHandler::OnPacket(net::Session& session, std::uint16_t type, const std::uint8_t* data,
                           std::size_t size) {
    switch (static_cast<PacketType>(type)) {
        case PacketType::LoginRequest:
            return HandleLogin(session, data, size);
        case PacketType::JoinRoomRequest:
            return HandleJoinRoom(session, data, size);
        case PacketType::MoveInput:
            return HandleMoveInput(session, data, size);
        default:
            // 모르는 타입이거나 서버 -> 클라 방향 전용 타입을 클라이언트가 보낸 경우.
            net::Log("[session %llu] rejected: unexpected packet type %u", Sid(session),
                     static_cast<unsigned>(type));
            return false;
    }
}

bool GameHandler::HandleLogin(net::Session& session, const std::uint8_t* data, std::size_t size) {
    cppgs::LoginRequest request;
    if (!ParsePayload(request, data, size)) {
        net::Log("[session %llu] rejected: malformed LoginRequest", Sid(session));
        return false;
    }

    cppgs::LoginResponse response;
    net::PlayerState& player = session.player();

    if (player.loggedIn) {
        response.set_result(cppgs::RESULT_INVALID_STATE);
    } else if (!IsValidNickname(request.nickname())) {
        response.set_result(cppgs::RESULT_INVALID_NICKNAME);
    } else if (nicknamesInUse_.count(request.nickname()) > 0) {
        response.set_result(cppgs::RESULT_DUPLICATE_NICKNAME);
    } else {
        player.loggedIn = true;
        player.playerId = nextPlayerId_++;
        player.nickname = request.nickname();
        nicknamesInUse_.insert(player.nickname);

        response.set_result(cppgs::RESULT_OK);
        FillPlayerInfo(response.mutable_player(), session);
        net::Log("[session %llu] login: %s (player %llu)", Sid(session), player.nickname.c_str(),
                 static_cast<unsigned long long>(player.playerId));
    }

    session.SendMessage(PacketType::LoginResponse, response);
    return true;
}

bool GameHandler::HandleJoinRoom(net::Session& session, const std::uint8_t* data,
                                 std::size_t size) {
    cppgs::JoinRoomRequest request;
    if (!ParsePayload(request, data, size)) {
        net::Log("[session %llu] rejected: malformed JoinRoomRequest", Sid(session));
        return false;
    }

    cppgs::JoinRoomResponse response;
    net::PlayerState& player = session.player();
    const std::uint32_t roomId = request.room_id();
    response.set_room_id(roomId);

    if (!player.loggedIn || player.roomId != 0) {
        response.set_result(cppgs::RESULT_INVALID_STATE);
        session.SendMessage(PacketType::JoinRoomResponse, response);
        return true;
    }
    if (roomId == 0 || roomId > kMaxRoomId) {
        response.set_result(cppgs::RESULT_INVALID_ROOM);
        session.SendMessage(PacketType::JoinRoomResponse, response);
        return true;
    }

    auto found = rooms_.find(roomId);
    if (found != rooms_.end() && found->second.members.size() >= kMaxRoomPlayers) {
        response.set_result(cppgs::RESULT_ROOM_FULL);
        session.SendMessage(PacketType::JoinRoomResponse, response);
        return true;
    }

    // 방이 없으면 만든다. 이전 멤버 목록(복사본)으로 응답과 알림을 만든다.
    Room& room = rooms_[roomId];
    const std::vector<std::shared_ptr<net::Session>> others = room.members;

    // 방에서 비어 있는 스폰 슬롯 중 가장 앞의 것을 쓴다 (누가 나가도 남은 사람과 겹치지 않는다).
    std::array<bool, kSpawnSlotCount> slotUsed{};
    for (const auto& member : others) {
        const std::size_t used = member->player().spawnSlot;
        if (used < kSpawnSlotCount) slotUsed[used] = true;
    }
    std::size_t slot = 0;
    while (slot < kSpawnSlotCount && slotUsed[slot]) ++slot;
    if (slot == kSpawnSlotCount) slot = 0;  // 정원 검사 때문에 일어나지 않는다

    const Vec2 spawn = SpawnPosition(slot);
    player.spawnSlot = slot;
    player.x = spawn.x;
    player.z = spawn.z;
    player.dirX = 0.0f;
    player.dirZ = 0.0f;
    player.lastInputSeq = 0;

    room.members.push_back(session.shared_from_this());
    player.roomId = roomId;

    response.set_result(cppgs::RESULT_OK);
    for (const auto& member : others) FillPlayerInfo(response.add_players(), *member);
    FillPlayerInfo(response.add_players(), session);
    net::Log("[session %llu] %s joined room %u (%zu/%zu)", Sid(session), player.nickname.c_str(),
             static_cast<unsigned>(roomId), others.size() + 1, kMaxRoomPlayers);

    // 이 아래에서는 room 참조를 쓰지 않는다: Send 중 세션이 닫히면 방이 지워질 수 있다.
    session.SendMessage(PacketType::JoinRoomResponse, response);
    if (session.IsClosed()) return true;

    cppgs::PlayerJoined joined;
    FillPlayerInfo(joined.mutable_player(), session);
    for (const auto& member : others) {
        member->SendMessage(PacketType::PlayerJoined, joined);
    }
    return true;
}

bool GameHandler::HandleMoveInput(net::Session& session, const std::uint8_t* data,
                                  std::size_t size) {
    cppgs::MoveInput input;
    if (!ParsePayload(input, data, size)) {
        net::Log("[session %llu] rejected: malformed MoveInput", Sid(session));
        return false;
    }

    net::PlayerState& player = session.player();

    // 폭주 감지: 한 틱 동안 받은 입력 수를 센다 (방에 없어도 센다).
    if (player.inputTick != currentTick_) {
        player.inputTick = currentTick_;
        player.inputsInTick = 0;
    }
    if (++player.inputsInTick > kMaxInputsPerTick) {
        net::Log("[session %llu] rejected: MoveInput flood (> %d per tick)", Sid(session),
                 kMaxInputsPerTick);
        return false;
    }

    // 연속으로 흐르는 입력이라 아래 경우에는 오류 응답 없이 조용히 무시한다 (docs/protocol.md 참고).
    if (player.roomId == 0) return true;  // 방에 들어가기 전의 입력

    Vec2 direction;
    if (!SanitizeDirection(input.dir_x(), input.dir_z(), direction)) return true;  // NaN/무한대

    if (input.seq() <= player.lastInputSeq) return true;  // 오래되었거나 중복된 입력

    player.dirX = direction.x;
    player.dirZ = direction.z;
    player.lastInputSeq = input.seq();
    return true;
}

void GameHandler::Tick(std::uint32_t tick) {
    currentTick_ = tick;

    // 방 번호를 복사해 둔다: 전송 중 세션이 닫히면 방이 지워질 수 있다.
    std::vector<std::uint32_t> roomIds;
    roomIds.reserve(rooms_.size());
    for (const auto& entry : rooms_) roomIds.push_back(entry.first);

    for (const std::uint32_t roomId : roomIds) {
        const auto found = rooms_.find(roomId);
        if (found == rooms_.end()) continue;
        const std::vector<std::shared_ptr<net::Session>> members = found->second.members;

        cppgs::WorldSnapshot snapshot;
        snapshot.set_tick(tick);
        for (const auto& member : members) {
            net::PlayerState& player = member->player();
            const Vec2 next = Step({player.x, player.z}, {player.dirX, player.dirZ});
            player.x = next.x;
            player.z = next.z;

            cppgs::PlayerSnapshot* entry = snapshot.add_players();
            entry->set_player_id(player.playerId);
            entry->set_x(player.x);
            entry->set_z(player.z);
            entry->set_last_input_seq(player.lastInputSeq);
        }

        for (const auto& member : members) {
            member->SendMessage(PacketType::WorldSnapshot, snapshot);
        }
    }
}

void GameHandler::OnSessionClosed(net::Session& session) {
    LeaveRoom(session);

    net::PlayerState& player = session.player();
    if (player.loggedIn) {
        nicknamesInUse_.erase(player.nickname);
        player.loggedIn = false;
    }
}

void GameHandler::LeaveRoom(net::Session& session) {
    net::PlayerState& player = session.player();
    if (player.roomId == 0) return;

    const std::uint32_t roomId = player.roomId;
    player.roomId = 0;

    auto found = rooms_.find(roomId);
    if (found == rooms_.end()) return;

    auto& members = found->second.members;
    members.erase(std::remove_if(members.begin(), members.end(),
                                 [&session](const std::shared_ptr<net::Session>& member) {
                                     return member.get() == &session;
                                 }),
                  members.end());

    // 남은 멤버 목록을 복사해 둔다: 알림을 보내다 다른 세션이 닫혀도 안전하게 순회하기 위해서다.
    const std::vector<std::shared_ptr<net::Session>> remaining = members;
    if (remaining.empty()) rooms_.erase(found);

    net::Log("[session %llu] %s left room %u (%zu left)", Sid(session), player.nickname.c_str(),
             static_cast<unsigned>(roomId), remaining.size());

    cppgs::PlayerLeft left;
    left.set_player_id(player.playerId);
    for (const auto& member : remaining) {
        member->SendMessage(PacketType::PlayerLeft, left);
    }
}

bool GameHandler::IsValidNickname(const std::string& nickname) {
    if (nickname.empty() || nickname.size() > kMaxNicknameBytes) return false;
    // 제어 문자(0x00~0x1F, 0x7F)는 허용하지 않는다. 길이는 문자 수가 아니라 바이트 수 기준이다.
    return std::none_of(nickname.begin(), nickname.end(), [](char c) {
        const unsigned char u = static_cast<unsigned char>(c);
        return u < 0x20 || u == 0x7F;
    });
}

}  // namespace game
