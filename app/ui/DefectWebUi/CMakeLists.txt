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

qt_add_qml_module(defect_web_ui
    URI DefectWebUi
    VERSION 1.0
    QML_FILES
        qml/main.qml
        qml/components/ImagePreview.qml
        qml/components/PanelHeader.qml
        qml/components/SideRail.qml
)

qt_add_resources(defect_web_ui "assets"
    PREFIX "/"
    FILES
        qtquickcontrols2.conf
        resources/images/placeholder.png
)

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
