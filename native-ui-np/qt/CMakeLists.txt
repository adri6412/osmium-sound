# The kiosk interface for the browser (Qt for WebAssembly, single thread).
# Sources: OSMIUM_SRC, prepared by prepare.py from the Osmium Sound
# repository; QML and assets are not compiled in, the page unpacks them.
cmake_minimum_required(VERSION 3.21)
project(osmium_kiosk_demo LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_AUTOMOC ON)

find_package(Qt6 REQUIRED COMPONENTS Core Gui Network Qml Quick)

if(NOT OSMIUM_SRC)
  message(FATAL_ERROR "OSMIUM_SRC (the output of prepare.py) is required")
endif()
if(NOT OSMIUM_QML)
  message(FATAL_ERROR "OSMIUM_QML (native-ui-qt/qml of the checkout) is required")
endif()
file(GLOB SRC_CPP ${OSMIUM_SRC}/*.cpp)
file(GLOB SRC_H ${OSMIUM_SRC}/*.h)
file(GLOB SRC_C ${OSMIUM_SRC}/*.c)

qt_add_executable(hifi-qt ${CMAKE_CURRENT_SOURCE_DIR}/wasm/main.cpp ${SRC_CPP} ${SRC_H} ${SRC_C})
# linux/input.h for the remote-control code, which in the browser only maps
# keyboard keys (no /dev/input there)
target_include_directories(hifi-qt PRIVATE ${OSMIUM_SRC} ${CMAKE_CURRENT_SOURCE_DIR}/wasm/include)
target_link_libraries(hifi-qt PRIVATE Qt6::Core Qt6::Gui Qt6::Network Qt6::Qml Qt6::Quick)
# a static build links only the QML modules it finds imported in these files
set_target_properties(hifi-qt PROPERTIES QT_QML_ROOT_PATH ${OSMIUM_QML})
# (Qt 6.8.2 needs scripts/fix-qt-static.py once, see there)
# the page unpacks the interface's files into Module.FS (Qt exports FS)
target_link_options(hifi-qt PRIVATE -sFORCE_FILESYSTEM=1)
