cmake_minimum_required(VERSION 3.20)
project(cppgameserver LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# --- standalone Asio (header-only) -------------------------------------------
# 설정 단계에서 GitHub 에서 고정 태그를 내려받는다. 오프라인이면
# -DFETCHCONTENT_SOURCE_DIR_ASIO=<로컬 asio 경로> 로 대체할 수 있다.
include(FetchContent)
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

# --- server --------------------------------------------------------------------
add_executable(cppgameserver
    src/main.cpp
    src/net/Server.cpp
    src/net/Session.cpp
)
target_include_directories(cppgameserver PRIVATE src)
target_link_libraries(cppgameserver PRIVATE asio_headers)

if(MSVC)
    target_compile_options(cppgameserver PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(cppgameserver PRIVATE -Wall -Wextra -pedantic)
endif()
