cmake_minimum_required(VERSION 3.20)
project(cppgameserver LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(FetchContent)

# --- standalone Asio (header-only) -------------------------------------------
# 설정 단계에서 GitHub 에서 고정 태그를 내려받는다. 오프라인이면
# -DFETCHCONTENT_SOURCE_DIR_ASIO=<로컬 asio 경로> 로 대체할 수 있다.
FetchContent_Declare(
    asio
    GIT_REPOSITORY https://github.com/chriskohlhoff/asio.git
    GIT_TAG        asio-1-30-2
    GIT_SHALLOW    TRUE
)
FetchContent_MakeAvailable(asio)

find_package(Threads REQUIRED)

add_library(asio_headers INTERFACE)
target_include_directories(asio_headers SYSTEM INTERFACE ${asio_SOURCE_DIR}/asio/include)
target_compile_definitions(asio_headers INTERFACE ASIO_STANDALONE ASIO_NO_DEPRECATED)
target_link_libraries(asio_headers INTERFACE Threads::Threads)
if(WIN32)
    target_compile_definitions(asio_headers INTERFACE _WIN32_WINNT=0x0A00)
    target_link_libraries(asio_headers INTERFACE ws2_32 mswsock)
endif()

# --- protobuf (소스에서 빌드: protoc + libprotobuf-lite) -----------------------
# 3.21.x 는 abseil 에 의존하지 않는 마지막 계열이라 빌드가 가볍다. Unity 쪽 Google.Protobuf
# 런타임(3.21.12)과 같은 버전을 쓴다. 오프라인이면 -DFETCHCONTENT_SOURCE_DIR_PROTOBUF=<경로>.
set(protobuf_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(protobuf_BUILD_CONFORMANCE OFF CACHE BOOL "" FORCE)
set(protobuf_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(protobuf_BUILD_PROTOC_BINARIES ON CACHE BOOL "" FORCE)
set(protobuf_BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(protobuf_WITH_ZLIB OFF CACHE BOOL "" FORCE)
set(protobuf_INSTALL OFF CACHE BOOL "" FORCE)
set(protobuf_MSVC_STATIC_RUNTIME OFF CACHE BOOL "" FORCE)  # 우리 코드와 같은 /MD 런타임
FetchContent_Declare(
    protobuf
    GIT_REPOSITORY https://github.com/protocolbuffers/protobuf.git
    GIT_TAG        v3.21.12
    GIT_SHALLOW    TRUE
    GIT_SUBMODULES ""
    SOURCE_SUBDIR  cmake
)
FetchContent_MakeAvailable(protobuf)

# --- proto 코드 생성 ----------------------------------------------------------
set(PROTO_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../proto)
set(PROTO_FILE ${PROTO_DIR}/game.proto)
set(PROTO_GEN_DIR ${CMAKE_CURRENT_BINARY_DIR}/generated)
file(MAKE_DIRECTORY ${PROTO_GEN_DIR})

add_custom_command(
    OUTPUT  ${PROTO_GEN_DIR}/game.pb.cc ${PROTO_GEN_DIR}/game.pb.h
    COMMAND protoc --cpp_out=${PROTO_GEN_DIR} -I ${PROTO_DIR} ${PROTO_FILE}
    DEPENDS protoc ${PROTO_FILE}
    COMMENT "protoc: game.proto -> C++"
    VERBATIM
)
add_library(game_proto STATIC ${PROTO_GEN_DIR}/game.pb.cc)
target_include_directories(game_proto SYSTEM PUBLIC ${PROTO_GEN_DIR})
target_link_libraries(game_proto PUBLIC libprotobuf-lite)

# Unity 용 C# 코드 생성 (결과는 커밋한다): cmake --build build --target gen_proto_csharp
set(PROTO_CSHARP_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../client-unity/Assets/Scripts/Generated)
add_custom_target(
    gen_proto_csharp
    COMMAND ${CMAKE_COMMAND} -E make_directory ${PROTO_CSHARP_DIR}
    COMMAND protoc --csharp_out=${PROTO_CSHARP_DIR} -I ${PROTO_DIR} ${PROTO_FILE}
    DEPENDS protoc ${PROTO_FILE}
    COMMENT "protoc: game.proto -> C# (client-unity/Assets/Scripts/Generated)"
    VERBATIM
)

# --- 이동 시뮬레이션 (외부 의존성 없는 순수 계산, 단위 테스트 대상) --------------
add_library(simulation STATIC src/game/Simulation.cpp)
target_include_directories(simulation PUBLIC src)

# --- server --------------------------------------------------------------------
add_executable(cppgameserver
    src/main.cpp
    src/net/Server.cpp
    src/net/Session.cpp
    src/game/GameHandler.cpp
    src/game/GameLoop.cpp
)
target_include_directories(cppgameserver PRIVATE src)
target_link_libraries(cppgameserver PRIVATE asio_headers game_proto simulation)

# --- 단위 테스트: ctest --test-dir build -C Release --output-on-failure ----------
enable_testing()
add_executable(simulation_test tests/simulation_test.cpp)
target_link_libraries(simulation_test PRIVATE simulation)
add_test(NAME simulation_test COMMAND simulation_test)

foreach(target cppgameserver simulation simulation_test)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /permissive- /utf-8)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -pedantic)
    endif()
endforeach()
