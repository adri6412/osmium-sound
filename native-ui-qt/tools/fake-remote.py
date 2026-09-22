#!/usr/bin/env python3
"""Telecomandi finti, per provare il riconoscimento senza comprare la ferramenta.

Costruisce un albero sysfs e dei nodi /dev fasulli (fifo) dove hifi-qt va a
cercare i dispositivi di input, e ci scrive dentro eventi evdev veri. Serve a
mettere alla prova la parte che decide CHI e' un telecomando, chi e' una
tastiera e chi non va toccato (native-ui-qt/src/remote.cpp), che e' dove si
sbaglia con i modelli che non si hanno in mano.

    fake-remote.py tree  DIR [PROFILO…]     prepara DIR/sys e DIR/dev
    fake-remote.py list                     i profili disponibili
    fake-remote.py send  DIR [-d NOME] TASTO…   preme i tasti

Poi si avvia l'interfaccia con:
    HIFI_SYSFS_INPUT=DIR/sys HIFI_INPUT_DEV=DIR/dev
(oppure `FAKE_REMOTE=DIR tools/dev-run.sh`, che lo fa da solo).

🚨 I nodi sono fifo: EVIOCGRAB non funziona (non sono evdev veri) e la lettura
finisce quando chi scrive chiude — vale UNA `send` per avvio dell'interfaccia.
Basta per la strada dei tasti e per la classificazione, non per la presa
esclusiva.
"""
import os
import struct
import sys
import time

# i codici evdev che ci interessano (linux/input-event-codes.h)
KEYS = {
    "esc": 1, "enter": 28, "space": 57, "backspace": 14, "tab": 15,
    "up": 103, "down": 108, "left": 105, "right": 106,
    "mute": 113, "voldown": 114, "volup": 115,
    "pause": 119, "stop": 128, "menu": 139,
    "prev": 165, "play": 164, "next": 163,
    "back": 158, "home": 172, "info": 358, "list": 395,
    "search": 217, "favorites": 364, "shuffle": 444,
    "power": 116, "ok": 352, "select": 353,
    "red": 398, "green": 399, "yellow": 400, "blue": 401,
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
}
LETTERS = list(range(16, 26)) + list(range(30, 39)) + list(range(44, 51))   # q..p, a..l, z..m
ALPHABET_ROW = list(range(1, 32))      # ESC..D: la prova "tastiera completa" di udev
NAV = [KEYS[k] for k in ("up", "down", "left", "right", "enter", "ok")]
MEDIA = [KEYS[k] for k in ("play", "next", "prev", "stop", "pause", "mute", "volup", "voldown")]
DIGITS = [KEYS[str(n)] for n in range(10)]
COLOURS = [KEYS[k] for k in ("red", "green", "yellow", "blue")]
EXTRA = [KEYS[k] for k in ("back", "home", "menu", "info", "power", "search", "favorites")]
REL_X, REL_Y = 0, 1
EV_KEY, EV_SYN = 0x01, 0x00
BUS_USB, BUS_BLUETOOTH = 3, 5

# Un profilo e' una lista di dispositivi, perche' un telecomando vero spesso ne
# espone piu' d'uno: il gruppo dei tasti normali, quello dei multimediali, e a
# volte un puntatore. Accanto a ogni profilo, cosa deve dirne remote.cpp.
PROFILES = {
    # il telecomando "da manuale": niente lettere, niente puntatore
    "remote": ([("Telecomando finto", BUS_USB, NAV + MEDIA + EXTRA + DIGITS, False)],
               "telecomando, tutti i tasti (presa esclusiva)"),
    # ricevitore stile MCE: tasti di navigazione, multimediali, cifre e colori
    "mce": ([("Media Center Ed. eHome Infrared Remote", BUS_USB,
              NAV + MEDIA + EXTRA + DIGITS + COLOURS, False)],
            "telecomando, tutti i tasti"),
    # Flirc e i cloni: si presentano come TASTIERA completa
    "flirc": ([("flirc.tv flirc Keyboard", BUS_USB,
                ALPHABET_ROW + LETTERS + NAV + MEDIA, False)],
              "tastiera: solo i tasti multimediali finche' non lo dichiari tuo"),
    # telecomando Android TV alla Xiaomi: due gruppi, come quello vero
    "androidtv": ([("Xiaomi RC Keyboard", BUS_BLUETOOTH, NAV + EXTRA, False),
                   ("Xiaomi RC Consumer Control", BUS_BLUETOOTH, MEDIA + EXTRA, False)],
                  "due righe, un telecomando solo: tutti i tasti"),
    # air mouse: tastiera completa + multimediali + un puntatore a parte
    "airmouse": ([("G20S PRO Keyboard", BUS_BLUETOOTH,
                   ALPHABET_ROW + LETTERS + NAV + MEDIA + EXTRA, False),
                  ("G20S PRO Mouse", BUS_BLUETOOTH, [272, 273], True)],
                 "tastiera (solo multimediali) + puntatore, che NON va preso in esclusiva"),
    # solo cifre e accensione: non e' un telecomando per noi, e non si tocca
    "digits": ([("Tastierino numerico finto", BUS_USB, DIGITS + [KEYS["power"]], False)],
               "ignorato di proposito: niente frecce, niente multimediali"),
}


def bitmap(bits):
    """I bitmap di sysfs: parole esadecimali da 64 bit, la piu' alta per prima."""
    if not bits:
        return "0"
    words = [0] * (max(bits) // 64 + 1)
    for b in bits:
        words[b // 64] |= 1 << (b % 64)
    return " ".join("%x" % w for w in reversed(words))


def tree(root, names):
    names = names or ["remote"]
    devs = []
    for name in names:
        if name not in PROFILES:
            print("profilo sconosciuto:", name, "- prova `list`", file=sys.stderr)
            return 2
        devs += PROFILES[name][0]

    os.makedirs(os.path.join(root, "dev"), exist_ok=True)
    for i, (label, bus, keys, pointer) in enumerate(devs):
        sysdir = os.path.join(root, "sys", "input%d" % i)
        for sub in ("capabilities", "id", "event%d" % i):
            os.makedirs(os.path.join(sysdir, sub), exist_ok=True)
        w = lambda p, t: open(os.path.join(sysdir, p), "w").write(t + "\n")
        w("name", label)
        w("capabilities/key", bitmap(keys))
        w("capabilities/rel", bitmap([REL_X, REL_Y]) if pointer else "0")
        w("capabilities/abs", "0")
        w("properties", "0")
        w("id/bustype", "%x" % bus)
        node = os.path.join(root, "dev", "event%d" % i)
        if not os.path.exists(node):
            os.mkfifo(node)
        print("  %-38s -> %s" % (label, node))
    print("pronto:", root, "(%d dispositivi)" % len(devs))
    for name in names:
        print("  %-10s atteso: %s" % (name, PROFILES[name][1]))
    return 0


def send(root, device, names):
    """Preme i tasti su un dispositivo (il primo, o quello col nome dato)."""
    node = os.path.join(root, "dev", "event0")
    if device:
        for i in range(32):
            f = os.path.join(root, "sys", "input%d" % i, "name")
            if os.path.exists(f) and device.lower() in open(f).read().lower():
                node = os.path.join(root, "dev", "event%d" % i)
                break
        else:
            print("nessun dispositivo con", device, "nel nome", file=sys.stderr)
            return 2
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
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(2)
    if args[0] == "list":
        for name, (devs, expect) in PROFILES.items():
            print("%-10s %d dispositiv%s — %s" % (name, len(devs), "o" if len(devs) == 1 else "i", expect))
        sys.exit(0)
    if args[0] == "tree" and len(args) >= 2:
        sys.exit(tree(args[1], args[2:]))
    if args[0] == "send" and len(args) >= 3:
        dev = None
        rest = args[2:]
        if rest[0] in ("-d", "--device"):
            dev, rest = rest[1], rest[2:]
        sys.exit(send(args[1], dev, rest))
    print(__doc__)
    sys.exit(2)
