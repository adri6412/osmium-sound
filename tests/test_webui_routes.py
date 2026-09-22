"""Every call the web admin makes must have a way through webui_server.py.

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
import unittest

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


if __name__ == '__main__':
    unittest.main(verbosity=2)
