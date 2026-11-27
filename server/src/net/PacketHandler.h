#pragma once

#include <cstddef>
#include <cstdint>

namespace net {

class Session;

// 연결 계층(Session)과 게임 로직 사이의 경계.
// Session 은 프레이밍, Ping/Pong, 유휴 타임아웃만 책임지고, 나머지 패킷은 여기로 넘긴다.
class PacketHandler {
public:
    virtual ~PacketHandler() = default;

    // 패킷 1개를 처리한다. false 를 돌려주면 잘못된 패킷으로 보고 Session 이 연결을 끊는다.
    // (파싱 실패, 이 방향으로 보낼 수 없는 타입 등. 상태가 맞지 않는 요청은 오류 응답으로 처리하고 true 를 돌려준다.)
    virtual bool OnPacket(Session& session, std::uint16_t type, const std::uint8_t* data,
                          std::size_t size) = 0;

    // 세션이 닫힐 때 정확히 한 번 불린다.
    virtual void OnSessionClosed(Session& session) = 0;
};

}  // namespace net
