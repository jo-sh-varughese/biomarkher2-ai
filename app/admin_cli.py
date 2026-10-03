"""The `biomark-admin` command: account recovery from a terminal.

The admin console in the portal is where accounts are normally managed. This
is for the moments it can't be: creating the first administrator on a
server nobody can open a browser on, or getting back in after the last
administrator forgot their password. Whoever can run this can read the
database file anyway, so it asks for nothing but the database path.

    biomark-admin create-admin --email you@hospital.org --name "Dr. A. Menon"
    biomark-admin reset-password --email you@hospital.org
    biomark-admin unlock --email you@hospital.org
    biomark-admin list-users

Passwords are read with a hidden prompt, or from standard input with
--password-stdin (for scripts), never from the command line, where they
would land in shell history.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import AuthError, AuthStore


def _read_password(args) -> str:
    if args.password_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("New password: ")
    if first != getpass.getpass("Repeat it: "):
        raise SystemExit("The two passwords did not match. Nothing was changed.")
    return first


def _user(store: AuthStore, email: str) -> dict:
    user = store.find_user(email)
    if user is None:
        raise SystemExit(f"No account with the email {email}.")
    return user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="biomark-admin", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=os.environ.get("BIOMARK_DB", "artifacts/biomark.db"),
                        help="Account database (the server's --db; env BIOMARK_DB).")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-admin", help="Create an administrator account.")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--password-stdin", action="store_true")

    reset = commands.add_parser(
        "reset-password", help="Set a temporary password; it must be changed at the next sign-in."
    )
    reset.add_argument("--email", required=True)
    reset.add_argument("--password-stdin", action="store_true")

    unlock = commands.add_parser("unlock", help="Clear a lockout after failed sign-ins.")
    unlock.add_argument("--email", required=True)

    commands.add_parser("list-users", help="Print every account.")

    args = parser.parse_args(argv)
    store = AuthStore(args.db)
    try:
        if args.command == "create-admin":
            user = store.create_user(
                email=args.email, name=args.name, role="admin", password=_read_password(args),
            )
            print(f"Created administrator {user['name']} <{user['email']}>.")
        elif args.command == "reset-password":
            user = _user(store, args.email)
            store.admin_set_password(user["id"], _read_password(args), must_change=True, actor=None)
            print(f"Password reset for {user['email']}. They must choose a new one at their next sign-in.")
        elif args.command == "unlock":
            user = _user(store, args.email)
            store.unlock_user(user["id"], actor=None)
            print(f"Unlocked {user['email']}.")
        elif args.command == "list-users":
            users = store.list_users()
            if not users:
                print("No accounts yet.")
            for u in users:
                flags = [u["status"]] + (["locked"] if u["locked"] else []) + (
                    ["must change password"] if u["must_change_password"] else [])
                print(f"{u['email']:<36} {u['role']:<12} {', '.join(flags):<28} {u['name']}")
    except AuthError as exc:
        raise SystemExit(f"Refused: {exc}") from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
