#!/usr/bin/env python3
"""HiFi Player beta server — reset the dashboard admin password from the
container CLI, for when the web UI's own /account change-password form is
out of reach (forgotten password, no active session).

Usage (from the host, against the running container):
    docker compose exec beta-server python3 reset_password.py "NewPassword123"
    docker compose exec beta-server python3 reset_password.py --clear

--clear removes the DB override entirely, reverting the active password to
whatever BETA_ADMIN_PASSWORD_HASH is currently set to in .env -- the
original "factory" password, always reachable even if the one set later
from /account is lost.
"""
import sys

from werkzeug.security import generate_password_hash

from models import get_db, init_db, now_iso


def main():
    if len(sys.argv) != 2 or sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0 if len(sys.argv) == 2 and sys.argv[1] in ('-h', '--help') else 1)

    init_db()
    db = get_db()
    try:
        if sys.argv[1] == '--clear':
            db.execute('DELETE FROM admin_config WHERE id = 1')
            db.commit()
            print('DB password override cleared -- the active password is now BETA_ADMIN_PASSWORD_HASH from .env.')
            return

        new_password = sys.argv[1]
        if len(new_password) < 8:
            print('error: password must be at least 8 characters', file=sys.stderr)
            sys.exit(1)

        password_hash = generate_password_hash(new_password)
        db.execute(
            'INSERT INTO admin_config (id, password_hash, updated_at) VALUES (1, ?, ?) '
            'ON CONFLICT(id) DO UPDATE SET password_hash = excluded.password_hash, '
            'updated_at = excluded.updated_at',
            (password_hash, now_iso()))
        db.commit()
        print('Password reset. Log in with the new password at /login.')
    finally:
        db.close()


if __name__ == '__main__':
    main()
