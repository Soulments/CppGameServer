#pragma once

#include <cstddef>
#include <cstdint>

namespace net {

// Wire format (little-endian, 구조체를 그대로 보내지 않고 바이트 단위로 직렬화한다):
//
//   +----------------+-----------+------------------+
//   | payloadSize u16| type u16  | payload (N bytes)|
//   +----------------+-----------+------------------+
//
// payloadSize 는 헤더를 제외한 payload 길이다. M2 에서 payload 를 protobuf 로 바꾼다.
constexpr std::size_t kHeaderSize = 4;
constexpr std::size_t kMaxPayloadSize = 4096;

enum class PacketType : std::uint16_t {
    Ping = 1,  // 클라 -> 서버 (하트비트). payload 는 임의 바이트, Pong 이 그대로 되돌려 준다.
    Pong = 2,  // 서버 -> 클라
};

struct PacketHeader {
    std::uint16_t payloadSize = 0;
    std::uint16_t type = 0;
};

inline void EncodeHeader(const PacketHeader& header, std::uint8_t* out) {
    out[0] = static_cast<std::uint8_t>(header.payloadSize & 0xFF);
    out[1] = static_cast<std::uint8_t>((header.payloadSize >> 8) & 0xFF);
    out[2] = static_cast<std::uint8_t>(header.type & 0xFF);
    out[3] = static_cast<std::uint8_t>((header.type >> 8) & 0xFF);
}

inline PacketHeader DecodeHeader(const std::uint8_t* in) {
    PacketHeader header;
    header.payloadSize = static_cast<std::uint16_t>(in[0] | (in[1] << 8));
    header.type = static_cast<std::uint16_t>(in[2] | (in[3] << 8));
    return header;
}

}  // namespace net
