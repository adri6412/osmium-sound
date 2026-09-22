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

    def _node(self, name, keys, bus=5, uniq='', phys='', rel=None):
        d = os.path.join(self.tmp, 'input%d' % self.n)
        self.n += 1
        os.makedirs(os.path.join(d, 'capabilities'))
        os.makedirs(os.path.join(d, 'id'))
        w = lambda p, t: open(os.path.join(d, p), 'w').write(t + '\n')
        w('name', name)
        w('capabilities/key', bitmap(keys))
        w('capabilities/rel', bitmap(rel) if rel else '0')
        w('capabilities/abs', '0')
        w('uniq', uniq)
        w('phys', phys)
        w('id/bustype', '%x' % bus)
        w('id/vendor', '2717')
        w('id/product', '1234')

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


if __name__ == '__main__':
    unittest.main(verbosity=2)
