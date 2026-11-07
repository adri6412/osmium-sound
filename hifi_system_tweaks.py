"""System tweaks: a few OS-level knobs a listener can turn to push PCM→DSD and
upsampling harder, at the cost of power draw and — for the mitigations one —
security. They are off by default: Osmium's defaults stay low-power and
secure, the user opts in only when they want the extra headroom (e.g. to reach
DSD512 through a server-side converter, as Daphile/C-3PO does with its "Power"
section).

Three knobs, three ways to apply them:

  * cpu_governor   — written to every CPU's cpufreq/scaling_governor in /sys.
                     Runtime, immediate, reset by a reboot (so re-applied at
                     boot by hifi-system-tweaks.service). 'performance' pins the
                     cores at their top frequency.
  * hyperthreading — written to /sys/devices/system/cpu/smt/control (on/off).
                     Runtime, immediate, reset by a reboot (re-applied at boot).
                     Only where the hardware exposes SMT control.
  * cpu_mitigations— the CPU vulnerability mitigations, which can only be turned
                     off on the *kernel command line* (mitigations=off). Not a
                     runtime write: it needs a reboot, and the token is merged
                     into the ESP's hifi-cmdline.env by api_server (next to the
                     screen-rotation tokens).

api_server drives all of this over /system_tweaks; this module owns the config
model (same shape as hifi_squeezelite: DEFAULTS / TUNABLE / normalize /
set_fields / update, atomic write under a flock) and the /sys side of apply.
The boot service runs `hifi_system_tweaks.py apply`, exactly as
squeezelite.service runs `hifi_squeezelite.py apply`.

The sysfs root is read through SYSFS_ROOT (HIFI_SYSFS in the environment),
overridable so the tests can point it at a temp tree.
"""
import contextlib
import fcntl
import glob
import json
import os
import re
import sys
import tempfile
import time

CONF = '/etc/hifi-player/system-tweaks.json'
# Overridable for the tests (and the same HIFI_SYSFS the stream-tune script honours).
SYSFS_ROOT = os.environ.get('HIFI_SYSFS', '/sys')
PROC_CMDLINE = '/proc/cmdline'

# Paths under SYSFS_ROOT.
_GOVERNOR_GLOB = 'devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor'
_GOVERNOR_CPU0 = 'devices/system/cpu/cpu0/cpufreq/scaling_governor'
_GOVERNORS_AVAIL = 'devices/system/cpu/cpu0/cpufreq/scaling_available_governors'
_SMT_CONTROL = 'devices/system/cpu/smt/control'
# Values smt/control reports when the CPU has no usable SMT to toggle.
_SMT_UNAVAILABLE = ('notsupported', 'notimplemented', '')

DEFAULTS = {
    'cpu_governor': 'schedutil',   # Osmium's normal governor; the kernel's balanced choice
    'cpu_mitigations': 'on',       # 'on' = kernel defaults, 'off' = mitigations=off on the cmdline
    'hyperthreading': 'on',        # SMT on (every logical CPU usable)
}
TUNABLE = ('cpu_governor', 'cpu_mitigations', 'hyperthreading')

LOCK_TIMEOUT = 15.0
_GOVERNOR_RE = re.compile(r'^[a-z_]+$')


class InvalidField(ValueError):
    """A value /system_tweaks sent that the model refuses. `code` is the i18n
    key api_server answers with, `detail`/`field` what to put in the message."""

    def __init__(self, code, field, detail=''):
        super().__init__(f'{code}: {field} {detail}'.strip())
        self.code, self.field, self.detail = code, field, detail


# ── Reading the hardware ────────────────────────────────────────────
def _sys(rel):
    return os.path.join(SYSFS_ROOT, rel)


def _read(path):
    try:
        with open(path, encoding='ascii') as f:
            return f.read().strip()
    except (OSError, ValueError):
        return ''


def available_governors():
    """The governors this CPU offers, in the kernel's order; [] when the
    machine has no cpufreq (e.g. a fixed-frequency VM)."""
    raw = _read(_sys(_GOVERNORS_AVAIL))
    return raw.split() if raw else []


def governor_live():
    """The governor cpu0 runs now, '' when there is no cpufreq."""
    return _read(_sys(_GOVERNOR_CPU0))


def _smt_raw():
    return _read(_sys(_SMT_CONTROL))


def smt_available():
    """True when the hardware exposes a usable SMT toggle. A J4105 reports
    'notsupported' — the control must then be hidden, not offered."""
    return _smt_raw() not in _SMT_UNAVAILABLE


def smt_live():
    """'on' / 'off' / 'forceoff' ... as the kernel reports it, '' when absent."""
    return _smt_raw()


def _cmdline():
    return _read(PROC_CMDLINE)


# ── The config model ────────────────────────────────────────────────
def normalize(model):
    """A complete, clean model from whatever was read. Lenient (this is what
    loads a hand-edited JSON); set_fields() is the strict one. The governor is
    kept if it looks like a governor token — not checked against the live list
    here, so a config written on one box still loads on another."""
    m = dict(DEFAULTS)
    src = model if isinstance(model, dict) else {}
    gov = str(src.get('cpu_governor') or '').strip().lower()
    m['cpu_governor'] = gov if _GOVERNOR_RE.match(gov) else DEFAULTS['cpu_governor']
    mit = str(src.get('cpu_mitigations') or '').strip().lower()
    m['cpu_mitigations'] = 'off' if mit == 'off' else 'on'
    smt = str(src.get('hyperthreading') or '').strip().lower()
    m['hyperthreading'] = 'off' if smt == 'off' else 'on'
    return m


def set_fields(model, changes):
    """Strict partial update. Returns a new model or raises InvalidField.
    Unknown keys are refused, so a client typo cannot silently do nothing. The
    governor is checked against what the CPU actually offers (when it offers
    anything), so the UI can only pick a real one."""
    m = normalize(model)
    for key, value in (changes or {}).items():
        if key not in TUNABLE:
            raise InvalidField('systemTweaks.unknownField', key)
        if key == 'cpu_governor':
            value = str(value or '').strip().lower()
            avail = available_governors()
            if not _GOVERNOR_RE.match(value) or (avail and value not in avail):
                raise InvalidField('systemTweaks.invalidValue', key, str(value))
        elif key == 'cpu_mitigations':
            if value not in ('on', 'off'):
                raise InvalidField('systemTweaks.invalidValue', key, str(value))
        elif key == 'hyperthreading':
            if value not in ('on', 'off'):
                raise InvalidField('systemTweaks.invalidValue', key, str(value))
        m[key] = value
    return m


# ── Persistence (same shape as hifi_squeezelite) ────────────────────
def _write_atomic(path, text):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + os.path.basename(path) + '.', suffix='.tmp', dir=d)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def load(conf_path=None):
    """The model, from the JSON, or the defaults when there is none."""
    conf_path = CONF if conf_path is None else conf_path
    try:
        with open(conf_path, encoding='utf-8') as f:
            return normalize(json.load(f))
    except (OSError, ValueError):
        return normalize(DEFAULTS)


def save(model, conf_path=None):
    conf_path = CONF if conf_path is None else conf_path
    m = normalize(model)
    _write_atomic(conf_path, json.dumps(m, indent=2, sort_keys=True) + '\n')
    return m


class LockTimeout(TimeoutError):
    """Another writer held the model's lock for longer than the timeout."""


def _lock(conf_path, timeout):
    lock_path = conf_path + '.lock'
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockTimeout(f'{lock_path}: still held after {timeout:g} s') from None
                time.sleep(0.02)
    except BaseException:
        os.close(fd)
        raise


@contextlib.contextmanager
def locked(conf_path=None, timeout=LOCK_TIMEOUT):
    conf_path = CONF if conf_path is None else conf_path
    fd = _lock(conf_path, timeout)
    try:
        yield
    finally:
        os.close(fd)


def update(fn, conf_path=None, timeout=LOCK_TIMEOUT):
    """Load → `fn(model)` → save, as one step no other writer interleaves with.
    An exception from `fn` (InvalidField, say) leaves the file as it was.
    Returns the saved model."""
    conf_path = CONF if conf_path is None else conf_path
    with locked(conf_path, timeout):
        model = load(conf_path)
        new = fn(model)
        if new is not None:
            model = new
        return save(model, conf_path)


# ── Applying the /sys knobs (governor + SMT; not mitigations) ───────
def apply_governor(model):
    """Write the chosen governor to every CPU. Best-effort: a core that
    refuses it (offline, or the governor missing) is skipped. Returns the
    number of cores written."""
    gov = normalize(model)['cpu_governor']
    n = 0
    for path in glob.glob(_sys(_GOVERNOR_GLOB)):
        try:
            with open(path, 'w', encoding='ascii') as f:
                f.write(gov)
            n += 1
        except OSError:
            pass
    return n


def apply_smt(model):
    """Turn SMT on/off at runtime. No-op where the CPU has no SMT control, or
    where it is force-disabled on the command line (forceoff: writes refused).
    Returns True when it wrote the control."""
    if not smt_available():
        return False
    want = normalize(model)['hyperthreading']
    try:
        with open(_sys(_SMT_CONTROL), 'w', encoding='ascii') as f:
            f.write(want)
        return True
    except OSError:
        return False


def apply_runtime(model):
    """Both /sys knobs. mitigations is deliberately not here — it is a
    command-line change api_server writes to the ESP, taking effect on reboot."""
    return {'governor_cpus': apply_governor(model), 'smt': apply_smt(model)}


# ── The one command-line token this feature owns ────────────────────
def boot_tokens(model):
    """Kernel command-line tokens for the current config: ['mitigations=off']
    when the user turned mitigations off, else []. api_server merges these with
    the screen-rotation tokens into the single hifi_cmdline value."""
    return ['mitigations=off'] if normalize(model)['cpu_mitigations'] == 'off' else []


def needs_reboot(model, cmdline=None):
    """True when the running kernel does not yet match the chosen mitigations:
    off chosen but no mitigations=off in /proc/cmdline, or on chosen but it is
    still there. The UI shows a "reboot to apply" note while this holds."""
    line = _cmdline() if cmdline is None else cmdline
    has_off = 'mitigations=off' in line.split()
    want_off = normalize(model)['cpu_mitigations'] == 'off'
    return has_off != want_off


# ── Boot entry point (hifi-system-tweaks.service) ───────────────────
def apply(conf_path=None, out=None):
    """Load and apply the /sys knobs. Never raises for a refused /sys write;
    a stuck lock (read-only /etc) does not stop it either — the knobs must
    still be set."""
    model = load(conf_path)
    res = apply_runtime(model)
    if out is not None:
        print(f'hifi_system_tweaks: governor={model["cpu_governor"]} '
              f'({res["governor_cpus"]} cpus), smt={model["hyperthreading"]} '
              f'(written={res["smt"]}), mitigations={model["cpu_mitigations"]}', file=out)
    return model, res


def main(argv):
    if len(argv) >= 2 and argv[1] == 'apply':
        apply(out=sys.stdout)
        return 0
    print('usage: hifi_system_tweaks.py apply', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
