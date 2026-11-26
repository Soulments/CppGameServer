#pragma once

#include <chrono>
#include <cstdarg>
#include <cstdio>

namespace net {

// 서버 시작 후 경과 시간(ms)을 붙여 출력하는 간단한 로그.
// io_context 스레드 1개로 동작하는 동안은 잠금이 필요 없다. 멀티스레드로 바꿀 때 보강한다.
inline void Log(const char* format, ...) {
    static const auto start = std::chrono::steady_clock::now();
    const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
                             std::chrono::steady_clock::now() - start)
                             .count();

    std::printf("[%7lldms] ", static_cast<long long>(elapsed));
    std::va_list args;
    va_start(args, format);
    std::vprintf(format, args);
    va_end(args);
    std::printf("\n");
    std::fflush(stdout);
}

}  // namespace net
