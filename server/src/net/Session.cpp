#include "net/Session.h"

#include <cstring>
#include <utility>

#include "net/Log.h"

namespace net {

namespace {
// 느린 클라이언트가 송신 큐를 무한히 키우지 못하게 하는 상한.
constexpr std::size_t kMaxQueuedPackets = 1024;
}  // namespace

Session::Session(asio::ip::tcp::socket socket, std::uint64_t id,
                 std::chrono::seconds idleTimeout, CloseCallback onClose)
    : socket_(std::move(socket)),
      idleTimer_(socket_.get_executor()),
      id_(id),
      idleTimeout_(idleTimeout),
      onClose_(std::move(onClose)) {
    std::error_code ec;
    const auto endpoint = socket_.remote_endpoint(ec);
    peer_ = ec ? "unknown" : endpoint.address().to_string() + ":" + std::to_string(endpoint.port());
}

void Session::Start() {
    ArmIdleTimer();
    ReadHeader();
}

void Session::Close(const char* reason) {
    if (closed_) return;
    closed_ = true;

    Log("[session %llu] closed (%s) peer=%s", static_cast<unsigned long long>(id_), reason,
        peer_.c_str());

    std::error_code ec;
    idleTimer_.cancel();
    socket_.shutdown(asio::ip::tcp::socket::shutdown_both, ec);
    socket_.close(ec);
    // writeQueue_ 는 여기서 비우지 않는다. 진행 중인 async_write 가 front() 버퍼를 가리키고 있어서,
    // 취소가 완료되기 전에 해제하면 안 된다 (특히 IOCP). 핸들러가 self 를 잡고 있으므로
    // 모든 비동기 작업이 끝난 뒤 세션이 소멸될 때 함께 해제된다.

    if (onClose_) onClose_(id_);
}

void Session::ReadHeader() {
    auto self = shared_from_this();
    asio::async_read(socket_, asio::buffer(headerBuf_),
                     [this, self](std::error_code ec, std::size_t /*bytes*/) {
                         if (ec) {
                             Close(ec == asio::error::eof ? "peer closed" : "read error");
                             return;
                         }

                         header_ = DecodeHeader(headerBuf_.data());
                         if (header_.payloadSize > kMaxPayloadSize) {
                             Close("payload too large");
                             return;
                         }

                         payload_.resize(header_.payloadSize);
                         if (payload_.empty()) {
                             HandlePacket();
                         } else {
                             ReadPayload();
                         }
                     });
}

void Session::ReadPayload() {
    auto self = shared_from_this();
    asio::async_read(socket_, asio::buffer(payload_),
                     [this, self](std::error_code ec, std::size_t /*bytes*/) {
                         if (ec) {
                             Close("read error");
                             return;
                         }
                         HandlePacket();
                     });
}

void Session::HandlePacket() {
    // 어떤 패킷이든 받으면 살아 있는 연결로 보고 타이머를 다시 건다.
    ArmIdleTimer();

    switch (static_cast<PacketType>(header_.type)) {
        case PacketType::Ping:
            Send(PacketType::Pong, payload_.data(), payload_.size());
            break;
        default:
            // M1 에서는 모르는 패킷 타입을 보내는 클라이언트를 바로 끊는다.
            Close("unknown packet type");
            return;
    }

    if (!closed_) ReadHeader();
}

void Session::Send(PacketType type, const std::uint8_t* data, std::size_t size) {
    if (closed_) return;
    if (writeQueue_.size() >= kMaxQueuedPackets) {
        Close("send queue overflow");
        return;
    }

    std::vector<std::uint8_t> buffer(kHeaderSize + size);
    PacketHeader header;
    header.payloadSize = static_cast<std::uint16_t>(size);
    header.type = static_cast<std::uint16_t>(type);
    EncodeHeader(header, buffer.data());
    if (size > 0) std::memcpy(buffer.data() + kHeaderSize, data, size);

    const bool writing = !writeQueue_.empty();
    writeQueue_.push_back(std::move(buffer));
    if (!writing) DoWrite();  // 진행 중인 쓰기가 없을 때만 시작해서 순서를 보장한다.
}

void Session::DoWrite() {
    auto self = shared_from_this();
    asio::async_write(socket_, asio::buffer(writeQueue_.front()),
                      [this, self](std::error_code ec, std::size_t /*bytes*/) {
                          if (ec) {
                              Close("write error");
                              return;
                          }
                          if (closed_) return;
                          writeQueue_.pop_front();
                          if (!writeQueue_.empty()) DoWrite();
                      });
}

void Session::ArmIdleTimer() {
    // expires_after 는 대기 중이던 타이머를 취소하고 새로 건다.
    idleTimer_.expires_after(idleTimeout_);
    auto self = shared_from_this();
    idleTimer_.async_wait([this, self](std::error_code ec) {
        if (ec) return;  // operation_aborted: 타이머가 다시 걸렸거나 세션이 닫힘
        Close("idle timeout");
    });
}

}  // namespace net
