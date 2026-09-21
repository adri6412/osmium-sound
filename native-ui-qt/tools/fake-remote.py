#!/usr/bin/env python3
"""Un telecomando finto, per provare la lettura di evdev senza telecomando.

Costruisce un albero sysfs e un nodo /dev fasulli (una fifo) dove hifi-qt va a
cercare i dispositivi di input, e ci scrive dentro eventi evdev veri.

    fake-remote.py tree  DIR                 prepara DIR/sys e DIR/dev
    fake-remote.py send  DIR TASTO [TASTO…]  preme i tasti (play, next, up…)

Poi si avvia hifi-qt con:
    HIFI_SYSFS_INPUT=DIR/sys HIFI_INPUT_DEV=DIR/dev

🚨 Il nodo e' una fifo: EVIOCGRAB non funziona (non e' un evdev vero) e la
lettura finisce quando chi scrive chiude. Basta per la strada dei tasti, non
per la presa esclusiva.
"""
import os
import struct
import sys
import time

# i codici evdev che ci interessano (linux/input-event-codes.h)
KEYS = {
    "esc": 1, "enter": 28, "space": 57, "a": 30,
    "up": 103, "down": 108, "left": 105, "right": 106,
    "mute": 113, "voldown": 114, "volup": 115,
    "pause": 119, "stop": 128, "menu": 139,
    "prev": 165, "play": 164, "next": 163,
    "back": 158, "home": 172, "info": 358, "list": 395,
    "search": 217, "favorites": 364, "shuffle": 444,
    "power": 116, "red": 398, "ok": 352,
}
EV_KEY, EV_SYN = 0x01, 0x00


def bitmap(bits):
    """I bitmap di sysfs: parole esadecimali da 64 bit, la piu' alta per prima."""
    top = max(bits)
    words = [0] * (top // 64 + 1)
    for b in bits:
        words[b // 64] |= 1 << (b % 64)
    return " ".join("%x" % w for w in reversed(words))


def tree(root):
    sysdir = os.path.join(root, "sys", "input0")
    for sub in ("capabilities", "id", "event0"):
        os.makedirs(os.path.join(sysdir, sub), exist_ok=True)
    os.makedirs(os.path.join(root, "dev"), exist_ok=True)
    write = lambda p, t: open(os.path.join(sysdir, p), "w").write(t + "\n")
    write("name", "Telecomando finto")
    # tasti da telecomando: multimediali, frecce, ok/indietro. NON le lettere,
    # o passerebbe per una tastiera e non verrebbe preso in esclusiva.
    write("capabilities/key", bitmap(sorted(set(KEYS.values()) - {30})))
    write("capabilities/rel", "0")
    write("capabilities/abs", "0")
    write("properties", "0")
    write("id/bustype", "3")          # BUS_USB
    node = os.path.join(root, "dev", "event0")
    if not os.path.exists(node):
        os.mkfifo(node)
    print("pronto:", root)


def send(root, names):
    node = os.path.join(root, "dev", "event0")
    fd = os.open(node, os.O_WRONLY)
    try:
        for name in names:
            code = KEYS.get(name)
            if code is None:
                print("tasto sconosciuto:", name, file=sys.stderr)
                continue
            for value in (1, 0):
                t = time.time()
                os.write(fd, struct.pack("llHHi", int(t), int(t % 1 * 1e6), EV_KEY, code, value))
                os.write(fd, struct.pack("llHHi", int(t), int(t % 1 * 1e6), EV_SYN, 0, 0))
                time.sleep(0.05)
            time.sleep(0.2)
    finally:
        os.close(fd)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    if sys.argv[1] == "tree":
        tree(sys.argv[2])
    elif sys.argv[1] == "send":
        send(sys.argv[2], sys.argv[3:])
    else:
        print(__doc__)
        sys.exit(2)
