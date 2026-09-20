"""What the Wi-Fi scan lists hand to the UIs (api_server + webui_server).

Almost every home router broadcasts one SSID on 2.4 GHz and on 5 GHz. Both
scanners used to flatten that: webui_server kept the first row per SSID (so
the 5 GHz half of every network was thrown away) and api_server kept every
access point (so the same name appeared two, three, four times with nothing
to tell the rows apart). One row per SSID *and band* is what makes the
on-screen list choosable — and what the band pinned onto the profile in
test_wifi_connect.py is chosen from.
"""
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import api_server  # noqa: E402  (needs the path above)
import webui_server  # noqa: E402


#: IN-USE:SSID:SIGNAL:SECURITY:FREQ, as `nmcli -t` prints it. CasaWiFi is on
#: both bands, and twice on 2.4 (a repeater); Ospiti is on one only.
NMCLI_ROWS = '\n'.join([
    '*:CasaWiFi:78:WPA2:2462 MHz',
    ':CasaWiFi:64:WPA2:5180 MHz',
    ':CasaWiFi:41:WPA2:2437 MHz',
    ':Ospiti:40::2412 MHz',
    ':Futura:55:WPA3:6115 MHz',
    '::30:WPA2:2412 MHz',          # hidden network: no name, nothing to show
])


class ApiServerScanTests(unittest.TestCase):
    def _scan(self, rows=NMCLI_ROWS):
        def fake_run(cmd, timeout=20):
            out = rows if cmd[:4] == ['nmcli', '-t', '-f', 'IN-USE,SSID,SIGNAL,SECURITY,FREQ'] else ''
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr='')

        with patch.object(api_server, '_run', fake_run):
            return api_server.wifi_scan()['networks']

    def test_one_row_per_ssid_and_band(self):
        nets = self._scan()
        self.assertEqual([(n['ssid'], n['band']) for n in nets],
                         [('CasaWiFi', '2.4'), ('CasaWiFi', '5'),
                          ('Ospiti', '2.4'), ('Futura', '6')])

    def test_the_strongest_access_point_of_a_band_wins(self):
        casa24 = next(n for n in self._scan() if n['band'] == '2.4' and n['ssid'] == 'CasaWiFi')
        self.assertEqual(casa24['signal'], '78')
        self.assertTrue(casa24['in_use'])

    def test_security_and_in_use_survive(self):
        nets = {n['ssid']: n for n in self._scan()}
        self.assertEqual(nets['Ospiti']['security'], '')
        self.assertFalse(nets['Ospiti']['in_use'])
        self.assertEqual(nets['Futura']['security'], 'WPA3')

    def test_an_unreadable_frequency_is_not_a_band(self):
        nets = self._scan(':Vicino:20:WPA2:')
        self.assertEqual(nets[0]['band'], '')

    def test_a_network_with_a_profile_is_saved(self):
        with patch.object(api_server, '_connection_ids_for_device_type', lambda dtype: ['CasaWiFi', 'hifi-setup']):
            nets = {(n['ssid'], n['band']): n for n in self._scan()}
        self.assertTrue(nets[('CasaWiFi', '2.4')]['saved'])
        self.assertTrue(nets[('CasaWiFi', '5')]['saved'])
        self.assertFalse(nets[('Ospiti', '2.4')]['saved'])

    def test_no_profiles_means_nothing_saved(self):
        self.assertFalse(any(n['saved'] for n in self._scan()))


class WebuiScanTests(unittest.TestCase):
    def _scan(self, rows=NMCLI_ROWS):
        def fake_nmcli(args, timeout=60):
            out = rows if args[:3] == ['-t', '-f', 'IN-USE,SSID,SIGNAL,SECURITY,FREQ'] else ''
            return 0, out, ''

        with patch.object(webui_server, 'FAKE', False), \
             patch.object(webui_server, '_nmcli', fake_nmcli):
            return webui_server._scan_wifi()

    def test_both_bands_of_a_dual_band_router_come_back(self):
        """This is the regression: the 5 GHz row used to be dropped outright."""
        nets = self._scan()
        self.assertEqual([(n['ssid'], n['band']) for n in nets],
                         [('CasaWiFi', '2.4'), ('CasaWiFi', '5'),
                          ('Ospiti', '2.4'), ('Futura', '6')])

    def test_two_access_points_on_one_band_stay_one_row(self):
        casa24 = next(n for n in self._scan() if n['band'] == '2.4' and n['ssid'] == 'CasaWiFi')
        self.assertEqual(casa24['signal'], 78)
        self.assertTrue(casa24['in_use'])


class BandFromFrequencyTests(unittest.TestCase):
    def test_both_servers_read_frequencies_the_same_way(self):
        for band_of in (api_server._wifi_band, webui_server._wifi_band):
            self.assertEqual(band_of('2412 MHz'), '2.4')
            self.assertEqual(band_of('2484'), '2.4')
            self.assertEqual(band_of('5180 MHz'), '5')
            self.assertEqual(band_of('5885 MHz'), '5')
            self.assertEqual(band_of('6115 MHz'), '6')
            self.assertEqual(band_of(''), '')
            self.assertEqual(band_of(None), '')
            self.assertEqual(band_of('boh'), '')


if __name__ == '__main__':
    unittest.main()
