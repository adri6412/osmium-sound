#!/bin/sh
# Wraps the Linux tar.gz into a single self-extracting executable.
#
# Why not an AppImage: an AppImage is mounted over FUSE by the unprivileged
# user, and FUSE denies access to every other user -- root included -- unless
# user_allow_other is set in /etc/fuse.conf. pkexec could therefore never reach
# the elevated helper inside the mount. Extracting to real files on disk avoids
# the problem entirely while still shipping one file.
#
# Usage: make-selfextract.sh <tarball> <version> <output>
set -eu

TARBALL="$1"
VERSION="$2"
OUTPUT="$3"

[ -f "$TARBALL" ] || { echo "no such tarball: $TARBALL" >&2; exit 1; }

cat > "$OUTPUT" <<EOF
#!/bin/sh
# Osmium Flasher ${VERSION} — self-extracting launcher.
# Extracts once into the user's cache directory, then runs from there.
set -eu

VERSION="${VERSION}"
DIR="\${XDG_CACHE_HOME:-\$HOME/.cache}/osmium-flasher/\${VERSION}"

if [ ! -f "\$DIR/.complete" ]; then
    rm -rf "\$DIR"
    mkdir -p "\$DIR"
    # The payload begins on the line after the __PAYLOAD_BELOW__ marker.
    OFFSET=\$(awk '/^__PAYLOAD_BELOW__\$/ { print NR + 1; exit 0 }' "\$0")
    if ! tail -n +"\$OFFSET" "\$0" | tar xz -C "\$DIR" --strip-components=1; then
        echo "Osmium Flasher: extraction failed" >&2
        rm -rf "\$DIR"
        exit 1
    fi
    touch "\$DIR/.complete"
fi

exec "\$DIR/osmium-flasher" "\$@"
__PAYLOAD_BELOW__
EOF

cat "$TARBALL" >> "$OUTPUT"
chmod +x "$OUTPUT"
echo "wrote $OUTPUT ($(du -h "$OUTPUT" | cut -f1))"
