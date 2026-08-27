# UI Qt Quick Osmium Sound — build sul dispositivo (Debian 13, Qt 6.8) o nel
# chroot trixie di sviluppo. Nessun qmake/cmake: moc e un Makefile bastano.
CXX      ?= g++
CXXFLAGS ?= -O2 -Wall -std=c++17 -fPIC
PKGS      = Qt6Quick Qt6Qml Qt6Gui Qt6Network Qt6Core libdrm
CXXFLAGS += $(shell pkg-config --cflags $(PKGS))
LDLIBS    = $(shell pkg-config --libs $(PKGS))
MOC      ?= $(shell pkg-config --variable=libexecdir Qt6Core)/moc

CC       ?= gcc
CFLAGS   ?= -O2 -Wall -std=c11
SRC   = $(wildcard src/*.cpp)
CSRC  = $(wildcard src/*.c)
HDRS  = $(filter-out src/qr.h,$(wildcard src/*.h))
MOCS  = $(patsubst src/%.h,build/moc_%.cpp,$(HDRS))
OBJ   = $(patsubst src/%.cpp,build/%.o,$(SRC)) $(patsubst src/%.c,build/c_%.o,$(CSRC)) $(patsubst build/moc_%.cpp,build/moc_%.o,$(MOCS))
BIN   = hifi-qt

all: $(BIN)

$(BIN): $(OBJ)
	$(CXX) -o $@ $(OBJ) $(LDLIBS)

build/%.o: src/%.cpp $(HDRS) | build
	$(CXX) $(CXXFLAGS) -Isrc -c -o $@ $<

build/c_%.o: src/%.c | build
	$(CC) $(CFLAGS) -c -o $@ $<

build/moc_%.cpp: src/%.h | build
	$(MOC) $< -o $@

build/moc_%.o: build/moc_%.cpp
	$(CXX) $(CXXFLAGS) -Isrc -c -o $@ $<

build:
	mkdir -p build

clean:
	rm -rf build $(BIN)

.PHONY: all clean
