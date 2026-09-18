#!/bin/bash
# Osmium Sound — downloading the image bundle before installing it
# (ab_url_size / ab_download / ab_dl_room / ab_sha256_ok in hifi-ab-lib.sh).
#
# The download replaces RAUC's streaming, so it has to survive what a home
# line does to a gigabyte: a redirect (GitHub answers with a 302 whose own
# Content-Length is 0), a connection dropped halfway (resume, don't start
# over), a server that ignores ranges (start over, don't glue two halves),
# and a partial file from an earlier attempt that is already complete.
#
# Hermetic: a local HTTP server on 127.0.0.1, nothing leaves the machine.
set -u
L="distro/config/includes.chroot/usr/local/sbin/hifi-ab-lib.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); }
bad() { fail=$((fail+1)); echo "FAIL: $1"; }
expect() { if [ "$2" = "$3" ]; then ok; else bad "$1: expected '$3', got '$2'"; fi; }

[ -f "$L" ] || { echo "missing $L"; exit 1; }
T=$(mktemp -d)
srv_pid=""
trap '[ -n "$srv_pid" ] && kill "$srv_pid" 2>/dev/null; rm -rf "$T"' EXIT

# 3 MiB of non-repeating bytes: a resume glued at the wrong offset changes
# the checksum.
python3 -c 'import os,sys; sys.stdout.buffer.write(os.urandom(3*1024*1024))' > "$T/bundle"
SIZE=$(wc -c < "$T/bundle" | tr -d ' ')
SHA=$(sha256sum "$T/bundle" | cut -c1-64)

cat > "$T/server.py" <<'PY'
import http.server, os, re, socket, sys
DATA = open(sys.argv[1], 'rb').read()
STATE = sys.argv[2]           # counts requests per path, one file each
class H(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *a): pass
    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass
    def hit(self):
        f = os.path.join(STATE, self.path.strip('/').replace('/', '_') or 'root')
        n = int(open(f).read()) + 1 if os.path.exists(f) else 1
        open(f, 'w').write(str(n))
        return n
    def do_HEAD(self): self.serve(False)
    def do_GET(self): self.serve(True)
    def serve(self, body):
        n = self.hit()
        if self.path == '/redir':
            self.send_response(302)
            self.send_header('Location', '/file')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        rng = self.headers.get('Range')
        start = 0
        m = re.match(r'bytes=(\d+)-', rng or '')
        if m and self.path != '/norange':
            start = int(m.group(1))
            if start >= len(DATA):
                self.send_response(416)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            self.send_response(206)
            self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, len(DATA) - 1, len(DATA)))
        else:
            self.send_response(200)
        chunk = DATA[start:]
        self.send_header('Content-Length', str(len(chunk)))
        self.send_header('Accept-Ranges', 'none' if self.path == '/norange' else 'bytes')
        self.end_headers()
        if not body:
            return
        # /flaky drops the connection after 1 MiB on its first two GETs.
        if self.path == '/flaky' and n <= 2:
            self.wfile.write(chunk[:1024 * 1024])
            self.wfile.flush()
            # shutdown, not close: the handler's file objects keep the socket
            # alive, and curl would sit waiting for the rest of the body.
            self.connection.shutdown(socket.SHUT_RDWR)
            self.close_connection = True
            return
        self.wfile.write(chunk)
http.server.ThreadingHTTPServer(('127.0.0.1', int(sys.argv[3])), H).serve_forever()
PY

PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
mkdir -p "$T/state"
python3 "$T/server.py" "$T/bundle" "$T/state" "$PORT" &
srv_pid=$!
for _ in $(seq 50); do
    curl -s -o /dev/null "http://127.0.0.1:$PORT/file" -I && break
    sleep 0.1
done
U="http://127.0.0.1:$PORT"

# shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-ab-lib.sh
. "$L"
AB_DL_RETRY_DELAY=0

# ── size ───────────────────────────────────────────────────────────────
expect "size of a plain file" "$(ab_url_size "$U/file")" "$SIZE"
expect "size behind a 302 is the file's, not the redirect's" "$(ab_url_size "$U/redir")" "$SIZE"
expect "size of a missing server is 0" "$(ab_url_size "http://127.0.0.1:1/x")" "0"

# ── download ───────────────────────────────────────────────────────────
ab_download "$U/redir" "$T/a.part" "$SIZE" 2>/dev/null; expect "download through a redirect" "$?" 0
ab_sha256_ok "$T/a.part" "$SHA"; expect "... and the bytes are right" "$?" 0

# A partial file from an earlier attempt: only the rest is fetched.
head -c 1000000 "$T/bundle" > "$T/b.part"
ab_download "$U/file" "$T/b.part" "$SIZE" 2>/dev/null; expect "resume a partial file" "$?" 0
ab_sha256_ok "$T/b.part" "$SHA"; expect "... glued at the right offset" "$?" 0

# The line drops at 1 MiB: the next attempt resumes instead of starting over.
ab_download "$U/flaky" "$T/c.part" "$SIZE" 2>/dev/null; expect "survive a dropped connection" "$?" 0
ab_sha256_ok "$T/c.part" "$SHA"; expect "... and the bytes are right" "$?" 0

# A server that ignores ranges: the half file is thrown away, never glued.
head -c 1000000 "$T/bundle" > "$T/d.part"
ab_download "$U/norange" "$T/d.part" "$SIZE" 2>/dev/null; expect "server without ranges" "$?" 0
ab_sha256_ok "$T/d.part" "$SHA"; expect "... starts over, no glued halves" "$?" 0

# Already complete from a run cut right after the transfer: no request at all.
cp "$T/bundle" "$T/e.part"
rm -f "$T/state/file"
ab_download "$U/file" "$T/e.part" "$SIZE" 2>/dev/null; expect "complete part file" "$?" 0
expect "... asks the server nothing" "$(cat "$T/state/file" 2>/dev/null || echo 0)" 0

# Larger than the bundle (another version's leftovers): started over.
cat "$T/bundle" "$T/bundle" > "$T/f.part"
ab_download "$U/file" "$T/f.part" "$SIZE" 2>/dev/null; expect "oversized part file" "$?" 0
ab_sha256_ok "$T/f.part" "$SHA"; expect "... replaced by the right bytes" "$?" 0

# A server that is gone: fails, does not loop forever.
ab_download "http://127.0.0.1:1/x" "$T/g.part" "$SIZE" 2>/dev/null; expect "unreachable server fails" "$?" 1

# ── checksum ───────────────────────────────────────────────────────────
ab_sha256_ok "$T/a.part" "0000000000000000000000000000000000000000000000000000000000000000"
expect "wrong checksum is refused" "$?" 1
ab_sha256_ok "$T/a.part" ""; expect "no checksum checks nothing" "$?" 0

# ── room ───────────────────────────────────────────────────────────────
ab_dl_room "$T" 1048576; expect "1 MiB fits" "$?" 0
ab_dl_room "$T" $(( 1 << 60 )); expect "an exabyte does not" "$?" 1
free_mib=$(( $(df -Pk "$T" | awk 'NR == 2 { print $4 }') / 1024 ))
ab_dl_room "$T" $(( (free_mib - AB_DL_MARGIN_MIB + 1) * 1048576 ))
expect "the margin is kept free" "$?" 1
ab_dl_room "/nonexistent/dir" 1; expect "unknown filesystem means no room" "$?" 1

echo "bundle fetch: $pass ok, $fail failed"
[ "$fail" = 0 ]
