#pragma once

#include <cstddef>

namespace game {

// 서버 시뮬레이션 상수. 클라이언트 예측이 같은 값을 써야 한다 (docs/protocol.md 참고).
constexpr int kTickRate = 20;                           // 초당 틱 수
constexpr float kTickSeconds = 1.0f / kTickRate;        // 한 틱의 시간 (50ms)
constexpr float kMoveSpeed = 5.0f;                      // 초당 이동 거리
constexpr float kArenaHalfSize = 20.0f;                 // 아레나는 [-20, 20] x [-20, 20] (XZ 평면)
constexpr std::size_t kSpawnSlotCount = 4;              // 방 정원과 같다

struct Vec2 {
    float x = 0.0f;
    float z = 0.0f;
};

// 클라이언트가 보낸 방향을 유효한 이동 방향으로 바꾼다.
//  - NaN/무한대가 있으면 false (호출한 쪽이 입력을 무시한다)
//  - 크기가 1보다 크면 1로 줄인다. 그래서 값을 부풀려도 속도가 올라가지 않는다.
//  - 매우 큰 값(오버플로 위험)은 먼저 ±1e6 으로 제한한다.
bool SanitizeDirection(float dirX, float dirZ, Vec2& out);

// 한 틱만큼 이동하고 아레나 경계 안으로 제한한 새 위치를 돌려준다. direction 은 SanitizeDirection 을 거친 값이어야 한다.
Vec2 Step(Vec2 position, Vec2 direction);

// 방 입장 시 배치되는 위치. slot 은 0 ~ kSpawnSlotCount-1 (범위 밖이면 0번 슬롯).
Vec2 SpawnPosition(std::size_t slot);

}  // namespace game
