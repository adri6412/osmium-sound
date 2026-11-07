# osmium-cdread — ESP-style audio-CD reader (libcdio_cdda).
# Built at image time by distro/config/hooks/normal/0435-osmium-cdread.hook.chroot.

CC      ?= cc
PKG     ?= pkg-config
CFLAGS  ?= -O2 -Wall -Wextra
CFLAGS  += -pthread $(shell $(PKG) --cflags libcdio_cdda)
LDLIBS  += $(shell $(PKG) --libs libcdio_cdda) -pthread

osmium-cdread: osmium-cdread.c
	$(CC) $(CFLAGS) -o $@ $< $(LDLIBS)

clean:
	rm -f osmium-cdread

.PHONY: clean
