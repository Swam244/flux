cmake_minimum_required(VERSION 3.15)
project(flux)


set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(BUILD_SHARED_LIBS OFF CACHE BOOL "Build shared libraries" FORCE)



# -----------------------------------------------------------------------------
# DEPENDENCY MANAGEMENT 
# -----------------------------------------------------------------------------
include(FetchContent)

# 1. fmt (String formatting)
FetchContent_Declare(
    fmt
    GIT_REPOSITORY https://github.com/fmtlib/fmt.git
    GIT_TAG        10.1.1
)

# 2. toml++ (Configuration parsing for flux.toml)
FetchContent_Declare(
    tomlplusplus
    GIT_REPOSITORY https://github.com/marzer/tomlplusplus.git
    GIT_TAG        v3.4.0
)

# 3. hiredis (Redis C client for Distributed State)
# Force static linking to avoid runtime library path issues
FetchContent_Declare(
    hiredis
    GIT_REPOSITORY https://github.com/redis/hiredis.git
    GIT_TAG        v1.2.0
)

# Make dependencies available immediately
FetchContent_MakeAvailable(fmt tomlplusplus hiredis)



# -----------------------------------------------------------------------------
# CORE BUILD
# -----------------------------------------------------------------------------

# Find pybind11
find_package(pybind11 REQUIRED)

# Python module
pybind11_add_module(_flux_core
    src/cpp/main.cpp
)

# Link dependencies to the core module
target_link_libraries(_flux_core PRIVATE
    fmt::fmt
    tomlplusplus::tomlplusplus
    hiredis
)

# Set output directory
set(FLUX_OUTPUT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/src/flux")
set_target_properties(_flux_core PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${FLUX_OUTPUT_DIR}"
    RUNTIME_OUTPUT_DIRECTORY "${FLUX_OUTPUT_DIR}"
)

# Handle hiredis library - copy shared library to output if needed and set RPATH
FetchContent_GetProperties(hiredis)
if(hiredis_POPULATED)
    # Check if hiredis is built as shared library
    get_target_property(HIREDIS_TYPE hiredis TYPE)
    if(HIREDIS_TYPE STREQUAL "SHARED_LIBRARY")
        # Copy hiredis shared library to output directory using generator expression
        add_custom_command(TARGET _flux_core POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<TARGET_FILE:hiredis>"
            "${FLUX_OUTPUT_DIR}/"
            COMMENT "Copying hiredis library to output directory"
        )
        
        # Also copy symlinks if they exist (hiredis might have versioned symlinks)
        get_target_property(HIREDIS_BINARY_DIR hiredis BINARY_DIR)
        if(HIREDIS_BINARY_DIR)
            # Try to copy common symlink patterns
            add_custom_command(TARGET _flux_core POST_BUILD
                COMMAND ${CMAKE_COMMAND} -E copy_if_different
                "${HIREDIS_BINARY_DIR}/libhiredis.so"
                "${FLUX_OUTPUT_DIR}/"
                COMMENT "Copying hiredis symlink"
            )
        endif()
        
        # Set RPATH to the output directory so Python can find it
        file(TO_CMAKE_PATH "${FLUX_OUTPUT_DIR}" FLUX_OUTPUT_DIR_CMAKE)
        set_target_properties(_flux_core PROPERTIES
            INSTALL_RPATH "${FLUX_OUTPUT_DIR_CMAKE}"
            BUILD_WITH_INSTALL_RPATH TRUE
        )
    endif()
endif()




# Compiler-specific options
if(MSVC)
    target_compile_options(_flux_core PRIVATE /W4)
else()
    target_compile_options(_flux_core PRIVATE -Wall -Wextra -Wpedantic)
endif()