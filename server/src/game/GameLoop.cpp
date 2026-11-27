#include "game/GameLoop.h"

#include "game/Simulation.h"
#include "net/Log.h"

namespace game {

namespace {
constexpr auto kInterval = std::chrono::milliseconds(1000 / kTickRate);
constexpr int kMaxCatchUpTicks = 5;
}  // namespace

GameLoop::GameLoop(asio::io_context& io, GameHandler& handler) : timer_(io), handler_(handler) {}

void GameLoop::Start() {
    running_ = true;
    next_ = std::chrono::steady_clock::now() + kInterval;
    Schedule();
}

void GameLoop::Stop() {
    running_ = false;
    timer_.cancel();
}

void GameLoop::Schedule() {
    timer_.expires_at(next_);
    timer_.async_wait([this](const std::error_code& ec) { OnTimer(ec); });
}

void GameLoop::OnTimer(const std::error_code& ec) {
    if (ec || !running_) return;  // 취소됨

    const auto now = std::chrono::steady_clock::now();
    int ran = 0;
    while (next_ <= now && ran < kMaxCatchUpTicks) {
        handler_.Tick(++tick_);
        next_ += kInterval;
        ++ran;
    }

    if (next_ <= now) {
        // 따라잡을 수 있는 한도를 넘게 밀렸다: 밀린 틱은 포기하고 지금부터 다시 시작한다.
        net::Log("tick loop is behind; resynchronizing (tick %u)", static_cast<unsigned>(tick_));
        next_ = now + kInterval;
    }

    if (running_) Schedule();
}

}  // namespace game
