// 이동 계산(Simulation)의 단위 테스트. 외부 라이브러리 없이 CHECK 매크로만 쓴다.
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <limits>

#include "game/Simulation.h"

namespace {

int g_failures = 0;

#define CHECK(condition)                                                          \
    do {                                                                          \
        if (!(condition)) {                                                       \
            std::fprintf(stderr, "FAIL %s:%d  %s\n", __FILE__, __LINE__, #condition); \
            ++g_failures;                                                         \
        }                                                                         \
    } while (0)

bool Near(float a, float b, float eps = 1e-4f) { return std::fabs(a - b) <= eps; }

void TestSanitizeDirection() {
    game::Vec2 d;

    CHECK(game::SanitizeDirection(0, 0, d) && Near(d.x, 0) && Near(d.z, 0));
    CHECK(game::SanitizeDirection(1, 0, d) && Near(d.x, 1) && Near(d.z, 0));
    CHECK(game::SanitizeDirection(0.5f, 0, d) && Near(d.x, 0.5f));  // 1 이하는 그대로 (천천히 이동)
    CHECK(game::SanitizeDirection(100, 0, d) && Near(d.x, 1) && Near(d.z, 0));
    CHECK(game::SanitizeDirection(3, 4, d) && Near(d.x, 0.6f) && Near(d.z, 0.8f));
    CHECK(game::SanitizeDirection(-3, -4, d) && Near(d.x, -0.6f) && Near(d.z, -0.8f));

    // 매우 큰 값도 오버플로 없이 정규화되어야 한다
    CHECK(game::SanitizeDirection(1e30f, 0, d) && Near(d.x, 1) && Near(d.z, 0));
    CHECK(game::SanitizeDirection(1e30f, 1e30f, d) && Near(d.x, 0.7071f, 1e-3f) && Near(d.z, 0.7071f, 1e-3f));
    CHECK(game::SanitizeDirection(3.0e38f, -3.0e38f, d) && Near(d.x, 0.7071f, 1e-3f) && Near(d.z, -0.7071f, 1e-3f));

    // 비정상 값은 거부
    const float nan = std::numeric_limits<float>::quiet_NaN();
    const float inf = std::numeric_limits<float>::infinity();
    CHECK(!game::SanitizeDirection(nan, 0, d));
    CHECK(!game::SanitizeDirection(0, nan, d));
    CHECK(!game::SanitizeDirection(inf, 0, d));
    CHECK(!game::SanitizeDirection(0, -inf, d));
}

void TestStep() {
    game::Vec2 p{0, 0};

    game::Vec2 next = game::Step(p, {1, 0});
    CHECK(Near(next.x, game::kMoveSpeed * game::kTickSeconds) && Near(next.z, 0));  // 0.25

    // 대각선도 같은 속도: 이동 거리가 한 틱 이동 거리(0.25)와 같아야 한다
    game::Vec2 dir;
    CHECK(game::SanitizeDirection(1, 1, dir));
    next = game::Step(p, dir);
    CHECK(Near(std::hypot(next.x, next.z), game::kMoveSpeed * game::kTickSeconds, 1e-4f));

    // 20틱(1초) 이동하면 5 유닛
    p = {0, 0};
    for (int i = 0; i < game::kTickRate; ++i) p = game::Step(p, {1, 0});
    CHECK(Near(p.x, game::kMoveSpeed, 1e-3f));

    // 정지
    next = game::Step({3, 4}, {0, 0});
    CHECK(Near(next.x, 3) && Near(next.z, 4));
}

void TestArenaBounds() {
    const float edge = game::kArenaHalfSize;
    game::Vec2 p = game::Step({edge - 0.1f, 0}, {1, 0});
    CHECK(Near(p.x, edge));  // 경계에서 멈춘다
    p = game::Step({edge, 0}, {1, 0});
    CHECK(Near(p.x, edge));
    p = game::Step({-edge + 0.1f, 0}, {-1, 0});
    CHECK(Near(p.x, -edge));
    p = game::Step({0, edge}, {0, 1});
    CHECK(Near(p.z, edge));
    p = game::Step({0, -edge}, {0, -1});
    CHECK(Near(p.z, -edge));

    // 한 축이 막혀도 다른 축은 계속 움직인다
    p = game::Step({edge, 0}, {1, 1});
    CHECK(Near(p.x, edge) && p.z > 0.0f);
}

void TestSpawnPositions() {
    for (std::size_t a = 0; a < game::kSpawnSlotCount; ++a) {
        const game::Vec2 pa = game::SpawnPosition(a);
        CHECK(std::fabs(pa.x) < game::kArenaHalfSize && std::fabs(pa.z) < game::kArenaHalfSize);
        for (std::size_t b = a + 1; b < game::kSpawnSlotCount; ++b) {
            const game::Vec2 pb = game::SpawnPosition(b);
            CHECK(!(Near(pa.x, pb.x) && Near(pa.z, pb.z)));  // 서로 겹치지 않는다
        }
    }
    const game::Vec2 fallback = game::SpawnPosition(99);
    const game::Vec2 first = game::SpawnPosition(0);
    CHECK(Near(fallback.x, first.x) && Near(fallback.z, first.z));
}

}  // namespace

int main() {
    TestSanitizeDirection();
    TestStep();
    TestArenaBounds();
    TestSpawnPositions();

    if (g_failures != 0) {
        std::fprintf(stderr, "%d check(s) failed\n", g_failures);
        return 1;
    }
    std::printf("all simulation tests passed\n");
    return 0;
}
