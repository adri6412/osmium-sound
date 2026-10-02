"""Every call either page makes must have a way through webui_server.py.

There are TWO pages, and they are easy to confuse — the remote control was
added to the wrong one first. The Vue admin (admin-webui/) is what you see
once the box is set up; the first-boot wizard is a plain HTML page written
inside webui_server.py itself (SETUP_CAPTIVE_HTML), with its own steps and
its own /api/provision endpoints. A step added to one does not appear in the
other.

The admin page never talks to api_server: it goes through webui_server, which
forwards only the paths written in `_AUTH_ROUTES` / `_PROVISION_ROUTES` (plus
the handful with a handler of their own). That list is the security boundary,
so it is right that it is a list — but it is edited by hand in a second file,
and forgetting a line there fails in the ugliest way: the endpoint exists in
api_server, the page's code is correct, and the feature is simply dead, with a
404 nobody reads. It happened with the remote controls: the whole Telecomando
section and the setup wizard's last card were inert on the device while every
test passed.

So: read every `api.sys(...)` / `api.sysPost(...)` in admin-webui/src, read the
tables and the explicit routes out of webui_server.py, and insist the two
agree. Paths built at runtime (`updates/${kind}/check`) are checked by
expanding them from the same file's literals — if one cannot be read, the test
says so instead of quietly covering nothing.

Run with:  python tests/test_webui_routes.py
"""
import ast
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBUI = os.path.join(ROOT, 'webui_server.py')
SRC = os.path.join(ROOT, 'admin-webui', 'src')
# `.sys('x')` -> GET /api/system/x, `.sysPost('x')` -> POST /api/system/x
CALL = re.compile(r"\.(sys|sysPost)\(\s*[`'\"]([^`'\"]*)[`'\"]")


def _reachable():
    """(path, method) pairs webui_server.py answers: tables + own handlers."""
    with open(WEBUI, encoding='utf-8') as f:
        src = f.read()
    tables = set()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not any(n in ('_AUTH_ROUTES', '_PROVISION_ROUTES') for n in names):
            continue
        for key in node.value.keys:
            if isinstance(key, ast.Tuple) and len(key.elts) == 2:
                path, method = (getattr(e, 'value', None) for e in key.elts)
                tables.add((path, method))
    own = set()
    for m in re.finditer(r"@app\.route\('(/api/[^']+)'(?:,\s*methods=\[([^\]]*)\])?", src):
        for method in re.findall(r"'(\w+)'", m.group(2) or "'GET'"):
            own.add((m.group(1), method))
    return tables | own


def _calls():
    """(path, method, where) for every call the page makes, plus the unreadable ones."""
    found, opaque = [], []
    for base, _, files in os.walk(SRC):
        for name in sorted(files):
            if not name.endswith(('.vue', '.js')):
                continue
            full = os.path.join(base, name)
            with open(full, encoding='utf-8') as f:
                text = f.read()
            where = os.path.relpath(full, ROOT)
            for m in CALL.finditer(text):
                method = 'GET' if m.group(1) == 'sys' else 'POST'
                path = m.group(2)
                if '${' not in path:
                    found.append(('/api/system/' + path, method, where))
                    continue
                # one hole to fill, one list of values: expand it from the file
                var = re.search(r'\$\{(\w+)(?:\[[^\]]*\])?\}', path)
                values = re.findall(r"%s\s*=\s*\{([^}]*)\}" % var.group(1), text) if var else []
                names = re.findall(r"[:,]\s*`?([a-z_]+)`?", values[0]) if values else []
                if not names:
                    opaque.append((path, where))
                    continue
                for value in names:
                    found.append(('/api/system/' + re.sub(r'\$\{[^}]*\}', value, path),
                                  method, where))
    return found, opaque


# the wizard's own calls, read out of the HTML that webui_server.py serves
CAPTIVE_CALL = re.compile(r"""(?:j(get|post)|fetch)\('(/api/[^']*)'""")
PAGES = ('SETUP_CAPTIVE_HTML', 'NET_RECOVERY_HTML', 'INSTALL_CAPTIVE_HTML', 'FALLBACK_HTML')


def _wizard_calls(mod):
    calls = set()
    for name in PAGES:
        for m in CAPTIVE_CALL.finditer(getattr(mod, name, '')):
            method = 'POST' if m.group(1) == 'post' else 'GET'
            calls.add((m.group(2).split('?')[0], method, name))
    return calls


def _url_map(mod):
    """What Flask will actually answer: exact rules, and the ones with a hole."""
    exact, patterns = set(), []
    for rule in mod.app.url_map.iter_rules():
        for method in rule.methods & {'GET', 'POST'}:
            if '<' in rule.rule:
                # <path:rest> swallows slashes, every other converter does not
                body = re.sub(r'<path:[^>]+>', '.+', rule.rule)
                body = re.sub(r'<[^>]+>', '[^/]+', body)
                patterns.append((re.compile('^' + body + '$'), method))
            else:
                exact.add((rule.rule, method))
    return exact, patterns


class WebAdminRoutes(unittest.TestCase):
    def test_every_call_has_a_way_through(self):
        reachable = _reachable()
        calls, _ = _calls()
        self.assertGreater(len(calls), 50, 'no calls found — the reader is broken, not the routes')
        dead = sorted({(p, m, w) for p, m, w in calls if (p, m) not in reachable})
        self.assertEqual(dead, [], 'the page calls these and webui_server.py does not forward them:\n' +
                         '\n'.join('  %-5s %-44s (%s)' % (m, p, w) for p, m, w in dead))

    def test_the_reader_can_read_every_call(self):
        _, opaque = _calls()
        self.assertEqual(opaque, [], 'cannot tell what these ask for, so nothing is guarded:\n' +
                         '\n'.join('  %s (%s)' % (p, w) for p, w in opaque))

    def test_the_remote_control_is_reachable(self):
        # the case that made this test exist; pinned by name so a rewrite of
        # the tables cannot drop it again
        reachable = _reachable()
        for path, method in (('/api/system/remote', 'GET'),
                             ('/api/system/remote/device', 'POST'),
                             ('/api/system/remote/keys', 'POST'),
                             ('/api/system/remote/learn', 'POST'),
                             ('/api/system/bt_remotes', 'GET'),
                             ('/api/system/bt_remotes/scan', 'POST'),
                             ('/api/system/bt_remotes/add', 'POST')):
            self.assertIn((path, method), reachable)


class FirstBootWizardFlow(unittest.TestCase):
    """Where the setup ends, and what the steps after it can still ask for."""

    @classmethod
    def setUpClass(cls):
        import webui_server
        cls.html = webui_server.SETUP_CAPTIVE_HTML

    def test_setup_ends_at_complete_setup_and_not_three_steps_early(self):
        """The timezone step used to finalize: from there on the box was out
        of provisioning while the wizard was still running, so every
        /api/provision call was refused (the remote step read the refusal as
        "no Bluetooth") and a reload dropped into the admin app, wizard gone.
        Finalizing belongs to the last screen — and to the restore path, which
        reboots into an already-configured device."""
        callers = [line.strip() for line in self.html.splitlines()
                   if 'provision/finalize' in line]
        self.assertEqual(len(callers), 2, callers)
        self.assertTrue(any('reboot:true' in c for c in callers), callers)   # restore
        self.assertTrue(any('reboot' not in c for c in callers), callers)    # finish()
        # the step before the sources one must just move on
        self.assertIn('jpost(`/api/provision/set_timezone`'.replace('`', "'") +
                      ",{timezone:tz}).then(showSourcesStep)", self.html)


class FirstBootWizardRoutes(unittest.TestCase):
    """The captive page, checked against the routes Flask really registers."""

    @classmethod
    def setUpClass(cls):
        import webui_server
        cls.mod = webui_server
        cls.exact, cls.patterns = _url_map(webui_server)

    def _reachable(self, path, method):
        return ((path, method) in self.exact
                or any(p.match(path) and m == method for p, m in self.patterns))

    def test_every_call_has_a_way_through(self):
        calls = _wizard_calls(self.mod)
        self.assertGreater(len(calls), 30, 'no calls found — the reader is broken, not the routes')
        dead = sorted(c for c in calls if not self._reachable(c[0], c[1]))
        self.assertEqual(dead, [], 'the wizard calls these and webui_server.py does not answer them:\n' +
                         '\n'.join('  %-5s %-44s (%s)' % (m, p, w) for p, m, w in dead))

    def test_the_remote_step_is_in_the_page_and_in_the_flow(self):
        # the step the user asked for, in the wizard they actually walk
        html = self.mod.SETUP_CAPTIVE_HTML
        # assert on the pieces, not on the page: a failure here should name
        # what is missing, not print 100 kB of HTML
        steps = (re.search(r'var STEPS=\[[^\]]*\]', html) or re.match('', '')).group(0)
        self.assertTrue('id="step-remote"' in html, 'the card is not in the page')
        self.assertIn("'step-remote'", steps,
                      'the card exists but is not in STEPS, so show() would never reach it: ' + steps)
        self.assertTrue('showRemoteStep()' in html, 'nothing leads into the step')
        for path, method in (('/api/system/remote', 'GET'),
                             # the step's two buttons: scan+pair, and "use this one"
                             ('/api/system/remote/device', 'POST'),
                             ('/api/system/bt_remotes', 'GET'),
                             ('/api/system/bt_remotes/scan', 'POST'),
                             ('/api/system/bt_remotes/add', 'POST')):
            self.assertTrue(self._reachable(path, method), path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
