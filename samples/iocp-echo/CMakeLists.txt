cmake_minimum_required(VERSION 3.20)
project(iocp_echo LANGUAGES CXX)

# IOCP는 Windows 전용이다. 다른 OS에서는 설정만 건너뛴다.
if(NOT WIN32)
    message(STATUS "iocp-echo is Windows only (IOCP); skipping.")
    return()
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(iocp_echo src/main.cpp)
target_link_libraries(iocp_echo PRIVATE ws2_32)

if(MSVC)
    target_compile_options(iocp_echo PRIVATE /W4 /permissive-)
else()
    target_compile_options(iocp_echo PRIVATE -Wall -Wextra)
endif()
