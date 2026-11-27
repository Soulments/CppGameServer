#pragma once

#include <chrono>
#include <cstdint>
#include <system_error>

#include <asio.hpp>

#include "game/GameHandler.h"

namespace game {

// 고정 간격(20Hz)으로 GameHandler::Tick 을 부르는 루프.
// 만료 시각을 이전 만료 시각에 간격을 더해서 정하므로 처리 시간이 누적 오차가 되지 않는다.
// 처리가 밀려 여러 틱이 늦어지면 최대 kMaxCatchUpTicks 개까지만 따라잡고, 그래도 밀리면 시계를 다시 맞춘다.
class GameLoop {
public:
    GameLoop(asio::io_context& io, GameHandler& handler);

    void Start();
    void Stop();  // 타이머를 취소한다. 이후 io_context::run 이 일이 없어서 끝날 수 있다.

    std::uint32_t tick() const { return tick_; }

private:
    void Schedule();
    void OnTimer(const std::error_code& ec);

    asio::steady_timer timer_;
    GameHandler& handler_;
    std::chrono::steady_clock::time_point next_;
    std::uint32_t tick_ = 0;
    bool running_ = false;
};

}  // namespace game
