#include "game/Simulation.h"

#include <algorithm>
#include <cmath>

namespace game {

namespace {
// 입력값이 이보다 크면 제곱에서 float 오버플로가 날 수 있어서 먼저 이 범위로 제한한다.
constexpr float kMaxRawComponent = 1e6f;

float ClampToArena(float value) {
    return std::max(-kArenaHalfSize, std::min(kArenaHalfSize, value));
}
}  // namespace

bool SanitizeDirection(float dirX, float dirZ, Vec2& out) {
    if (!std::isfinite(dirX) || !std::isfinite(dirZ)) return false;

    dirX = std::max(-kMaxRawComponent, std::min(kMaxRawComponent, dirX));
    dirZ = std::max(-kMaxRawComponent, std::min(kMaxRawComponent, dirZ));

    const float length = std::hypot(dirX, dirZ);
    if (length > 1.0f) {
        dirX /= length;
        dirZ /= length;
    }
    out.x = dirX;
    out.z = dirZ;
    return true;
}

Vec2 Step(Vec2 position, Vec2 direction) {
    Vec2 next;
    next.x = ClampToArena(position.x + direction.x * kMoveSpeed * kTickSeconds);
    next.z = ClampToArena(position.z + direction.z * kMoveSpeed * kTickSeconds);
    return next;
}

Vec2 SpawnPosition(std::size_t slot) {
    static const Vec2 kSlots[kSpawnSlotCount] = {
        {-5.0f, -5.0f},
        {5.0f, -5.0f},
        {-5.0f, 5.0f},
        {5.0f, 5.0f},
    };
    return kSlots[slot < kSpawnSlotCount ? slot : 0];
}

}  // namespace game
