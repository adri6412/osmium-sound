"""The touchscreen "unplugged and plugged back in" in software.

A TSTP MTouch panel stops answering now and then until its USB cable is
pulled (2026-09-28). api_server.reset_touchscreen does what the cable does:
it de-authorises the USB device the touch node belongs to and authorises it
again. Easy to get wrong: picking a touchpad or a keyboard node instead of
the screen, stopping at the USB *interface* instead of the device, and above
all leaving the panel de-authorised — worse than frozen.

Run with:  python tests/test_touchscreen.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('HIFI_NO_SERVICES', '1')
import api_server  # noqa: E402


def bitmap(bits):
    words = [0] * (max(bits) // 64 + 1)
    for b in bits:
        words[b // 64] |= 1 << (b % 64)
    return ' '.join('%x' % w for w in reversed(words))


class Touchscreen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inputs = os.path.join(self.tmp, 'class-input')
        os.makedirs(self.inputs)
        os.environ['HIFI_SYSFS_INPUT'] = self.inputs
        self.n = 0
        self.writes = []
        self._sleep = api_server.time.sleep
        api_server.time.sleep = lambda s: None

    def tearDown(self):
        os.environ.pop('HIFI_SYSFS_INPUT', None)
        api_server.time.sleep = self._sleep

    def _usb(self, port):
        """a USB device (…/usb1/1-2) with one interface (…/1-2:1.0)"""
        dev = os.path.join(self.tmp, 'devices', 'usb1', port)
        iface = os.path.join(dev, port + ':1.0', '0003:EEEF:2828.0001')
        os.makedirs(iface)
        for k, v in (('authorized', '1'), ('idVendor', 'eeef')):
            with open(os.path.join(dev, k), 'w') as f:
                f.write(v + '\n')
        return dev, iface

    def _node(self, name, parent, abs_=None, props=None):
        d = os.path.join(self.inputs, 'input%d' % self.n)
        self.n += 1
        os.makedirs(os.path.join(d, 'capabilities'))
        w = lambda p, t: open(os.path.join(d, p), 'w').write(t + '\n')
        w('name', name)
        w('capabilities/key', bitmap([330]))
        w('capabilities/abs', bitmap(abs_) if abs_ else '0')
        w('properties', bitmap(props) if props else '0')
        if parent:
            os.symlink(parent, os.path.join(d, 'device'))

    def test_the_screen_is_unplugged_and_plugged_back_in(self):
        dev, iface = self._usb('1-2')
        self._node('TSTP MTouch', iface, abs_=[0, 1, 47, 53, 54, 57], props=[1])
        seen = []
        real_open = open

        def spy(path, mode='r', *a, **k):
            f = real_open(path, mode, *a, **k)
            if 'w' in mode and path.endswith('authorized'):
                orig = f.write
                f.write = lambda s: (seen.append(s), orig(s))[1]
            return f
        api_server.open = spy
        try:
            r = api_server.reset_touchscreen()
        finally:
            del api_server.open
        self.assertTrue(r['success'], r)
        self.assertEqual(r['devices'], ['1-2'], 'the USB device, not its interface')
        self.assertEqual(seen, ['0', '1'], 'off, then on again')
        self.assertEqual(open(os.path.join(dev, 'authorized')).read().strip(), '1')

    def test_a_touchpad_is_not_a_touchscreen(self):
        # absolute axes without INPUT_PROP_DIRECT: a touchpad, left alone
        _dev, iface = self._usb('1-3')
        self._node('Mini Keyboard Touchpad', iface, abs_=[0, 1])
        r = api_server.reset_touchscreen()
        self.assertFalse(r['success'])

    def test_nothing_to_restart_says_so(self):
        self.assertFalse(api_server.reset_touchscreen()['success'])

    def test_the_support_bundle_reads_the_usb_power_state(self):
        _dev, iface = self._usb('1-2')
        self._node('TSTP MTouch', iface, abs_=[0, 1, 53, 54], props=[1])
        snap = api_server._support_touch_snapshot()
        self.assertEqual([s['usb'] for s in snap['screens']], ['1-2'])
        self.assertEqual(snap['screens'][0]['authorized'], '1')


if __name__ == '__main__':
    unittest.main(verbosity=2)
