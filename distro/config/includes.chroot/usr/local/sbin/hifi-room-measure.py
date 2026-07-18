#!/usr/bin/env python3
"""HiFi Player — guided room-correction measurement.

Called by api_server.py via systemd-run:
    hifi-room-measure.py /run/hifi-roomcorr-config.json

Plays a logarithmic sine sweep through the current DAC while recording it
with a USB measurement microphone, deconvolves the room's impulse response
(Farina method), derives a smoothed magnitude response, inverts it against a
gently tilted target curve and writes a linear-phase correction FIR to
/etc/camilladsp/filters/room.wav — the exact file the existing DSP
room-correction toggle (api_server.py set_dsp) already consumes.

Progress: /run/hifi-roomcorr-status.json  {state, progress, message}
          states: preparing | sweep | analyzing | done | error
Curves:   /var/lib/hifi-player/roomcorr-result.json (for the Settings chart)

The playback chain is restored afterwards: CamillaDSP is stopped during the
measurement (the room must be measured uncorrected, and the DAC freed) and
restarted if it was running; the local player is paused and resumed.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

import numpy as np

STATUS = "/run/hifi-roomcorr-status.json"
RESULT = "/var/lib/hifi-player/roomcorr-result.json"
FIR_OUT = "/etc/camilladsp/filters/room.wav"
SWEEP_WAV = "/run/hifi-roomcorr-sweep.wav"
REC_WAV = "/run/hifi-roomcorr-rec.wav"
DSP_UNIT = "camilladsp.service"
LMS_RPC = "http://127.0.0.1:9000/jsonrpc.js"

RATE = 48000
SWEEP_SECONDS = 8.0
TAIL_SECONDS = 2.0       # room decay captured after the sweep ends
F_LO, F_HI = 20.0, 20000.0
FIR_TAPS = 65536
MAX_CUT_DB = -12.0       # deepest correction dip
CORR_LO, CORR_HI = 25.0, 16000.0  # correct only inside this band


def write_status(state, progress, message):
    tmp = STATUS + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"state": state, "progress": progress, "message": message}, f)
    os.replace(tmp, STATUS)


def fail(message):
    write_status("error", 0, message)
    print(f"E: [hifi-roomcorr] {message}", file=sys.stderr)
    sys.exit(1)


def _run(cmd, timeout=30):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def lms_request(playerid, command):
    payload = json.dumps({"id": 1, "method": "slim.request",
                          "params": [playerid, command]}).encode()
    req = urllib.request.Request(LMS_RPC, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read()).get("result")


def pause_local_player():
    """Pause this device's own squeezelite if it's playing. Best effort."""
    try:
        result = lms_request("-", ["serverstatus", 0, 999]) or {}
        for p in result.get("players_loop", []):
            if str(p.get("ip", "")).startswith("127.0.0.1:"):
                pid = p.get("playerid")
                st = lms_request(pid, ["status", "-", 1]) or {}
                if st.get("mode") == "play":
                    lms_request(pid, ["pause", "1"])
                    return pid
    except Exception:
        pass
    return None


def resume_local_player(pid):
    if not pid:
        return
    try:
        lms_request(pid, ["play"])
    except Exception:
        pass


def write_wav_s16(path, data, channels):
    """Minimal 16-bit PCM WAV writer (no scipy dependency for output)."""
    import struct
    pcm = np.clip(data, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2").tobytes()
    hdr = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + \
        struct.pack("<IHHIIHH", 16, 1, channels, RATE,
                    RATE * channels * 2, channels * 2, 16) + \
        b"data" + struct.pack("<I", len(pcm))
    with open(path, "wb") as f:
        f.write(hdr + pcm)


def write_wav_f32(path, data):
    """Mono float32 WAV (IEEE float) — the format CamillaDSP's Conv reads."""
    import struct
    pcm = data.astype("<f4").tobytes()
    hdr = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + \
        struct.pack("<IHHIIHH", 16, 3, 1, RATE, RATE * 4, 4, 32) + \
        b"data" + struct.pack("<I", len(pcm))
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(hdr + pcm)
    os.replace(tmp, path)


def read_wav_mono(path):
    """Read the capture WAV (mono S16_LE, as arecord was told to write)."""
    with open(path, "rb") as f:
        raw = f.read()
    idx = raw.find(b"data")
    if idx < 0:
        return np.zeros(0)
    data = np.frombuffer(raw[idx + 8:], dtype="<i2").astype(np.float64) / 32768.0
    return data


def make_sweep():
    """Log sine sweep + its Farina inverse filter."""
    n = int(RATE * SWEEP_SECONDS)
    t = np.arange(n) / RATE
    ratio = F_HI / F_LO
    k = SWEEP_SECONDS / np.log(ratio)
    phase = 2 * np.pi * F_LO * k * (np.exp(t / k) - 1.0)
    sweep = np.sin(phase)
    fade = int(0.05 * RATE)
    env = np.ones(n)
    env[:fade] = np.sin(np.linspace(0, np.pi / 2, fade)) ** 2
    env[-fade:] = env[:fade][::-1]
    sweep *= env
    # Inverse filter: time-reversed sweep with the Farina amplitude tilt.
    # Absolute scale is irrelevant — the measured response is normalised to
    # its own mid-band average later.
    inv = sweep[::-1] * np.exp(-t / k)
    return sweep, inv


def octave_smooth(freqs, mag_db, fraction=6.0):
    """Fractional-octave smoothing on a log grid."""
    out = np.empty_like(mag_db)
    factor = 2 ** (1.0 / (2 * fraction))
    for i, f in enumerate(freqs):
        lo, hi = f / factor, f * factor
        sel = (freqs >= lo) & (freqs <= hi)
        out[i] = mag_db[sel].mean() if sel.any() else mag_db[i]
    return out


def main():
    if len(sys.argv) != 2:
        fail("usage: hifi-room-measure.py <config.json>")
    try:
        with open(sys.argv[1]) as f:
            cfg = json.load(f)
    except Exception as e:
        fail(f"configurazione illeggibile: {e}")

    mic = cfg.get("mic_device") or ""
    out_dev = cfg.get("out_device") or "default"
    level_db = float(cfg.get("level_db") or -12.0)
    level_db = max(-30.0, min(-6.0, level_db))
    import re
    if not re.fullmatch(r"[A-Za-z0-9_:,=.-]+", mic):
        fail("microfono non valido")

    write_status("preparing", 5, "Preparazione…")

    # Free the DAC: stop CamillaDSP if running (and remember), pause playback.
    dsp_was_active = _run(["systemctl", "is-active", DSP_UNIT]).stdout.strip() == "active"
    paused_pid = pause_local_player()
    if dsp_was_active:
        _run(["systemctl", "stop", DSP_UNIT])
        time.sleep(1.0)

    try:
        sweep, inv = make_sweep()
        gain = 10 ** (level_db / 20.0)
        tail = np.zeros(int(RATE * TAIL_SECONDS))
        out = np.concatenate([sweep * gain, tail])
        write_wav_s16(SWEEP_WAV, np.column_stack([out, out]).ravel(), 2)

        # aplay/arecord want a plug device so ALSA converts rate/format when
        # the hardware doesn't do S16/48k natively.
        play_dev = "plug" + out_dev if out_dev.startswith("hw:") else out_dev
        rec_seconds = SWEEP_SECONDS + TAIL_SECONDS + 1.0

        write_status("sweep", 20, "Misura in corso: sweep in riproduzione…")
        rec = subprocess.Popen(
            ["arecord", "-q", "-D", mic, "-f", "S16_LE", "-r", str(RATE),
             "-c", "1", "-d", str(int(rec_seconds)), REC_WAV],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        time.sleep(0.5)  # let the capture start before the sweep begins
        play = subprocess.run(["aplay", "-q", "-D", play_dev, SWEEP_WAV],
                              capture_output=True, text=True,
                              timeout=rec_seconds + 15)
        rec_err = rec.communicate(timeout=rec_seconds + 15)[1]
        if play.returncode != 0:
            fail(f"riproduzione sweep fallita ({(play.stderr or '').strip()[:120]})")
        if rec.returncode != 0 or not os.path.isfile(REC_WAV):
            fail(f"registrazione fallita ({(rec_err or b'').decode()[:120].strip()})")

        write_status("analyzing", 60, "Analisi della risposta…")
        recorded = read_wav_mono(REC_WAV)
        if recorded.size < RATE:
            fail("registrazione troppo corta")
        peak = np.abs(recorded).max()
        if peak < 1e-3:
            fail("nessun segnale dal microfono: controlla collegamento e volume")
        if peak > 0.99:
            fail("segnale in clipping: abbassa il volume dello sweep e ripeti")

        # Impulse response by convolution with the inverse sweep (FFT-based).
        n_fft = 1 << int(np.ceil(np.log2(recorded.size + inv.size)))
        ir = np.fft.irfft(np.fft.rfft(recorded, n_fft) * np.fft.rfft(inv, n_fft))
        peak_idx = int(np.argmax(np.abs(ir)))
        # 500 ms window from just before the direct sound, half-Hann tail.
        pre, win_len = int(0.005 * RATE), int(0.5 * RATE)
        start = max(0, peak_idx - pre)
        seg = ir[start:start + win_len]
        if seg.size < win_len:
            seg = np.pad(seg, (0, win_len - seg.size))
        taper = np.ones(win_len)
        half = win_len // 4
        taper[-half:] = 0.5 * (1 + np.cos(np.linspace(0, np.pi, half)))
        seg = seg * taper

        freqs = np.fft.rfftfreq(win_len, 1.0 / RATE)
        mag = np.abs(np.fft.rfft(seg))
        mag_db = 20 * np.log10(np.maximum(mag, 1e-12))
        band = (freqs >= F_LO) & (freqs <= F_HI)
        smooth_db = octave_smooth(freqs[band], mag_db[band])
        # Normalise: 0 dB = the mid-band (200–2000 Hz) average level.
        mid = (freqs[band] >= 200) & (freqs[band] <= 2000)
        ref = smooth_db[mid].mean() if mid.any() else smooth_db.mean()
        smooth_db -= ref

        write_status("analyzing", 80, "Calcolo del filtro di correzione…")
        # Target: flat, then a gentle -1 dB/octave tilt above 1 kHz.
        fb = freqs[band]
        target_db = np.where(fb > 1000.0, -1.0 * np.log2(fb / 1000.0), 0.0)
        corr_db = target_db - smooth_db
        # Only correct inside the trusted band, no boosts (cut-only + global
        # normalisation below ⇒ the FIR can never clip).
        corr_db = np.clip(corr_db, MAX_CUT_DB, 6.0)
        edge = (fb < CORR_LO) | (fb > CORR_HI)
        corr_db[edge] = 0.0
        corr_db -= corr_db.max()  # all-attenuation

        # Linear-phase FIR by frequency sampling on the full rfft grid.
        grid = np.fft.rfftfreq(FIR_TAPS, 1.0 / RATE)
        grid_db = np.interp(grid, fb, corr_db, left=corr_db[0], right=corr_db[-1])
        mag_lin = 10 ** (grid_db / 20.0)
        fir = np.fft.irfft(mag_lin)
        fir = np.roll(fir, FIR_TAPS // 2)
        fir *= np.hanning(FIR_TAPS)

        os.makedirs(os.path.dirname(FIR_OUT), exist_ok=True)
        # Remove a stale REW-uploaded text filter so the .wav takes precedence
        # deterministically (_fir_current checks .wav first anyway).
        write_wav_f32(FIR_OUT, fir)

        # Downsampled curves for the Settings chart (~200 log-spaced points).
        plot_f = np.geomspace(F_LO, F_HI, 200)
        measured = np.interp(plot_f, fb, smooth_db)
        correction = np.interp(plot_f, fb, corr_db)
        os.makedirs(os.path.dirname(RESULT), exist_ok=True)
        with open(RESULT + ".tmp", "w") as f:
            json.dump({
                "created": int(time.time()),
                "freqs": [round(float(x), 1) for x in plot_f],
                "measured_db": [round(float(x), 2) for x in measured],
                "corrected_db": [round(float(x + y), 2) for x, y in zip(measured, correction)],
            }, f)
        os.replace(RESULT + ".tmp", RESULT)

        write_status("done", 100, "Misura completata: filtro pronto")
    finally:
        for p in (SWEEP_WAV, REC_WAV):
            try:
                os.remove(p)
            except OSError:
                pass
        if dsp_was_active:
            _run(["systemctl", "start", DSP_UNIT])
        resume_local_player(paused_pid)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        fail(f"errore inatteso: {e}")
