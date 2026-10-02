"""Which input devices are remotes, and which of them are the SAME remote.

api_server reads /sys/class/input with the same rules as the on-screen
interface (native-ui-qt/src/remote.cpp) so the web admin can answer even while
the interface is restarting. Two things are easy to get wrong and both were:

  * what counts as a remote at all — a media-key keyboard is not one, a
    numeric pad is not one, and a full keyboard must not be grabbed;
  * how many remotes are in front of you. A Xiaomi remote is TWO input
    devices (a keyboard node and a consumer-control node), an air mouse adds
    a pointer. Offered as separate entries, someone setting up a player is
    asked which of the three is "theirs", which is not a question. They share
    the Bluetooth address, so that is what ties them together.

Run with:  python tests/test_remote_devices.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('HIFI_NO_SERVICES', '1')
import api_server  # noqa: E402

# the evdev codes the rules look at (linux/input-event-codes.h)
NAV = [103, 108, 105, 106, 28]          # up down left right enter
MEDIA = [164, 163, 165]                 # playpause next prev
LETTERS = list(range(1, 32))            # ESC..D — udev's "full keyboard" test


def bitmap(bits):
    words = [0] * (max(bits) // 64 + 1)
    for b in bits:
        words[b // 64] |= 1 << (b % 64)
    return ' '.join('%x' % w for w in reversed(words))


class RemoteDevices(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ['HIFI_SYSFS_INPUT'] = self.tmp
        self.n = 0
        self._chosen = ''
        self._patch_chosen()

    def tearDown(self):
        os.environ.pop('HIFI_SYSFS_INPUT', None)
        api_server._remote_chosen = self._real_chosen

    def _patch_chosen(self):
        self._real_chosen = api_server._remote_chosen
        api_server._remote_chosen = lambda: self._chosen

    def _usb(self, port, classes):
        """a USB device with one interface per class ('01' audio, '03' HID);
        returns the HID interface, where an input node hangs"""
        dev = os.path.join(self.tmp, 'devices', port)
        hid = ''
        for i, c in enumerate(classes):
            iface = os.path.join(dev, '%s:1.%d' % (port, i))
            os.makedirs(iface)
            open(os.path.join(iface, 'bInterfaceClass'), 'w').write(c + '\n')
            if c == '03':
                hid = iface
        for k in ('authorized', 'idVendor'):
            open(os.path.join(dev, k), 'w').write('1\n')
        return hid

    def _node(self, name, keys, bus=5, uniq='', phys='', rel=None, vendor='2717', product='1234', abs_=None, props=None, usb=None):
        d = os.path.join(self.tmp, 'input%d' % self.n)
        self.n += 1
        os.makedirs(os.path.join(d, 'capabilities'))
        os.makedirs(os.path.join(d, 'id'))
        w = lambda p, t: open(os.path.join(d, p), 'w').write(t + '\n')
        w('name', name)
        w('capabilities/key', bitmap(keys))
        w('capabilities/rel', bitmap(rel) if rel else '0')
        w('capabilities/abs', bitmap(abs_) if abs_ else '0')
        w('properties', bitmap(props) if props else '0')
        w('uniq', uniq)
        w('phys', phys)
        w('id/bustype', '%x' % bus)
        w('id/vendor', vendor)
        w('id/product', product)
        if usb:
            os.symlink(usb, os.path.join(d, 'device'))

    def test_a_known_remote_that_declares_a_keyboard_is_a_remote(self):
        # The Fire TV remote declares a whole keyboard. As a "keyboard" it was
        # not taken exclusively, and its power key reached logind and switched
        # the box off. A model the appliance knows is a remote whatever it says.
        self._node('Amazon Remote Keyboard', LETTERS + NAV + MEDIA, vendor='0171', product='0421')
        self._node('Some Keyboard', LETTERS + NAV + MEDIA, vendor='046d', product='c31c')
        kinds = {d['name']: (d['kind'], d['model']) for d in api_server._remote_devices()}
        self.assertEqual(kinds['Amazon Remote Keyboard'], ('remote', 'firetv'))
        self.assertEqual(kinds['Some Keyboard'], ('keyboard', ''))

    def test_the_two_halves_of_one_bluetooth_remote_are_one_remote(self):
        # a Xiaomi remote, exactly as it shows up: two nodes, one address.
        # The keyboard node carries the media keys too — which is why it is
        # listed at all: a full keyboard with nothing else is not a remote.
        self._node('Xiaomi RC Keyboard', LETTERS + NAV + MEDIA, uniq='dc:2c:26:1f:00:11')
        self._node('Xiaomi RC Consumer Control', MEDIA, uniq='dc:2c:26:1f:00:11')
        devs = api_server._remote_devices()
        self.assertEqual(len(devs), 2)
        self.assertEqual(len({d['group'] for d in devs}), 1, 'two entries, one remote')
        self.assertEqual({d['groupName'] for d in devs}, {'Xiaomi RC'},
                         'the name to show is what its pieces agree on')

    def test_choosing_the_remote_chooses_every_node_of_it(self):
        self._node('Xiaomi RC Keyboard', LETTERS + NAV + MEDIA, uniq='dc:2c:26:1f:00:11')
        self._node('Xiaomi RC Consumer Control', MEDIA, uniq='dc:2c:26:1f:00:11')
        self._chosen = 'DC:2C:26:1F:00:11'          # the group, as the picker sends it
        self.assertTrue(all(d['chosen'] for d in api_server._remote_devices()))
        # and the old way — one node by name — still means that node
        self._chosen = 'Xiaomi RC Keyboard'
        chosen = {d['name'] for d in api_server._remote_devices() if d['chosen']}
        self.assertEqual(chosen, {'Xiaomi RC Keyboard'})

    def test_usb_nodes_of_one_receiver_group_on_the_port_not_the_endpoint(self):
        # USB rarely fills in uniq; the endpoint after the slash is which node
        self._node('MCE Remote', NAV + MEDIA, bus=3, phys='usb-0000:00:14.0-3/input0')
        self._node('MCE Remote Consumer Control', MEDIA, bus=3, phys='usb-0000:00:14.0-3/input1')
        groups = {d['group'] for d in api_server._remote_devices()}
        self.assertEqual(groups, {'usb-0000:00:14.0-3'})

    def test_two_different_remotes_stay_two(self):
        self._node('Osmium Remote', NAV + MEDIA, uniq='aa:aa:aa:aa:aa:aa')
        self._node('Some Other Remote', NAV + MEDIA, uniq='bb:bb:bb:bb:bb:bb')
        devs = api_server._remote_devices()
        self.assertEqual(len({d['group'] for d in devs}), 2)
        self.assertEqual({d['groupName'] for d in devs}, {'Osmium Remote', 'Some Other Remote'})

    def test_what_is_not_a_remote_is_left_out(self):
        self._node('Tastierino', [2, 3, 4, 5, 6, 7, 8, 9, 10, 11], bus=3, phys='usb-1/input0')
        self._node('Perfectly Ordinary Keyboard', LETTERS, bus=3, phys='usb-2/input0')
        self.assertEqual(api_server._remote_devices(), [])

    def test_a_full_keyboard_with_media_keys_is_a_keyboard_not_a_remote(self):
        self._node('flirc.tv flirc Keyboard', LETTERS + NAV + MEDIA, bus=3, phys='usb-3/input0')
        devs = api_server._remote_devices()
        self.assertEqual([d['kind'] for d in devs], ['keyboard'])

    def test_the_keyboard_node_of_a_touchscreen_is_the_screen_not_a_remote(self):
        # The TSTP MTouch panel, as a user's appliance shows it: a touch node
        # (INPUT_PROP_DIRECT, multitouch axes) and a full keyboard with media
        # keys, same serial, same port. The keyboard node was listed under
        # "Your remotes" with "This is my remote" next to it.
        self._node('TSTP MTouch', [330], bus=3, uniq='CMTP_1.0', phys='usb-0000:00:15.0-2/input0',
                   vendor='eeef', product='2828', abs_=[0, 1, 47, 53, 54, 57], props=[1])
        self._node('TSTP MTouch', LETTERS + NAV + MEDIA, bus=3, uniq='CMTP_1.0', phys='usb-0000:00:15.0-2/input1',
                   vendor='eeef', product='2828')
        self._node('Amazon Remote Keyboard', LETTERS + NAV + MEDIA, vendor='0171', product='0421')
        self.assertEqual([d['name'] for d in api_server._remote_devices()], ['Amazon Remote Keyboard'])

    def test_a_touchpad_on_a_remote_does_not_hide_the_remote(self):
        # absolute axes WITHOUT INPUT_PROP_DIRECT: a touchpad (keyboard remotes
        # with a pad), not a screen — the remote stays
        self._node('Mini Keyboard', LETTERS + NAV + MEDIA, bus=3, phys='usb-4/input0')
        self._node('Mini Keyboard Touchpad', [330], bus=3, phys='usb-4/input1', abs_=[0, 1])
        self.assertEqual([d['name'] for d in api_server._remote_devices()], ['Mini Keyboard'])


    def test_the_playback_keys_of_a_dac_are_not_a_remote(self):
        # The Topping DX1 II: audio interfaces plus a HID one with play, next
        # and previous. It showed up under "Your remotes"; a USB remote
        # receiver without audio must stay.
        dac = self._usb('1-1.1', ['01', '01', '01', '01', '03'])
        self._node('TOPPING DX1 II', MEDIA, bus=3, phys='usb-0000:00:15.0-1.1/input4', vendor='152a', product='8750', usb=dac)
        rx = self._usb('1-3', ['03', '03'])
        self._node('MCE Remote', NAV + MEDIA, bus=3, phys='usb-0000:00:14.0-3/input0', usb=rx)
        self.assertEqual([d['name'] for d in api_server._remote_devices()], ['MCE Remote'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
