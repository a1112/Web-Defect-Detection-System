cmake_minimum_required(VERSION 3.21)

project(DefectWebUi LANGUAGES CXX)

set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Qt6 6.5 COMPONENTS Quick Qml QuickControls2 REQUIRED)

qt_add_executable(defect_web_ui
    src/main.cpp
)

qt6_add_resources(QML_BUNDLE
    qml/qml.qrc
    resources/resources.qrc
)

target_sources(defect_web_ui PRIVATE ${QML_BUNDLE})

target_link_libraries(defect_web_ui
    PRIVATE
        Qt6::Quick
        Qt6::Qml
        Qt6::QuickControls2
)

target_compile_definitions(defect_web_ui
    PRIVATE $<$<CONFIG:Debug>:QT_QML_DEBUG>
)

set_target_properties(defect_web_ui PROPERTIES
    OUTPUT_NAME "DefectWebUi"
)

if(QT_FEATURE_qml_debug)
    message(STATUS "QML debugging is enabled. Disable in release builds if not needed.")
endif()

if(QT_FEATURE_wasm)
    message(STATUS "Building with Qt for WebAssembly target enabled.")
endif()
