"""
Command line interface for the Baby Tracker sync client.

    babytracker babies
    babytracker last diaper --baby Everly
    babytracker add-diaper --baby Everly wet
    babytracker raw <device-uuid> --since 120

Credentials come from BABYTRACKER_EMAIL / BABYTRACKER_PASSWORD or are asked
for; the password is never stored. The CLI keeps its own device ID and local
database in --state-dir (default ~/.babytracker), so it appears as its own
device in the app, separate from Home Assistant.
"""
import argparse
import base64
import getpass
import json
import os
import sys
import uuid

from .api import AccountResetError, AuthenticationError
from .core import BabyTracker

LAST = {
    "diaper": "get_last_diaper",
    "feeding": "get_last_feeding",
    "nursing": "get_last_nursing",
    "sleep": "get_last_sleep",
    "temperature": "get_last_temperature",
    "bath": "get_last_bath",
    "pump": "get_last_pump",
    "medicine": "get_last_medicine",
    "growth": "get_last_growth",
    "milestone": "get_last_milestone",
    "vaccine": "get_last_vaccine",
}

DIAPER_KINDS = {"wet": (True, False), "dirty": (False, True), "mixed": (True, True), "dry": (False, False)}


def _state(state_dir):
    """Load (or create) this CLI's own device ID."""
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, "state.json")
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        state = {}
    if not state.get("device_uuid"):
        state["device_uuid"] = str(uuid.uuid4())
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    return state


def _picture_dir(args):
    """Where activity pictures are kept (~/.babytracker/pictures by default)."""
    return os.path.join(args.state_dir, "pictures")


def _connect(args):
    state = _state(args.state_dir)
    email = args.email or os.environ.get("BABYTRACKER_EMAIL") or input("Baby Tracker email: ")
    password = os.environ.get("BABYTRACKER_PASSWORD") or getpass.getpass("Baby Tracker password: ")

    tracker = BabyTracker(db_path=os.path.join(args.state_dir, "babytracker.db"), time_zone=args.time_zone)
    result = tracker.authenticate(email, password, state["device_uuid"])
    if result.get("status") != "success":
        raise SystemExit(f"Could not connect: {result.get('message')}")
    if not args.offline:
        sync = tracker.sync(picture_dir=_picture_dir(args))
        if sync.get("status") != "success":
            print(f"warning: sync failed: {sync.get('message')}", file=sys.stderr)
    return tracker


def _baby_id(tracker, name):
    babies = tracker.get_all_babies()
    if name:
        for baby in babies:
            if baby.name.lower() == name.lower():
                return baby.object_id
        raise SystemExit(f"No baby named {name!r}. Babies: {', '.join(b.name for b in babies)}")
    if len(babies) == 1:
        return babies[0].object_id
    raise SystemExit(f"--baby is required: {', '.join(b.name for b in babies)}")


def _print(value):
    print(json.dumps(value, indent=2, default=str))


def cmd_babies(tracker, args):
    _print([{"id": b.object_id, "name": b.name, "dob": b.dob, "gender": "male" if b.gender else "female"}
            for b in tracker.get_all_babies()])


def cmd_sync(tracker, args):
    _print(tracker.sync(picture_dir=_picture_dir(args)))


def cmd_logout(tracker, args):
    """End the server session. Nothing is stored between runs (each command logs in
    again), so there is no local session to clear beyond the connection's cookies."""
    tracker.api.logout()
    _print({"status": "success", "message": "Logged out"})


def cmd_last(tracker, args):
    _print(getattr(tracker, LAST[args.kind])(_baby_id(tracker, args.baby)))


def cmd_add_diaper(tracker, args):
    pee, poo = DIAPER_KINDS[args.kind]
    _print(tracker.add_diaper(_baby_id(tracker, args.baby), None, pee=pee, poo=poo, note=args.note))


def cmd_devices(tracker, args):
    _print(tracker.api.get_devices())


def cmd_raw(tracker, args):
    """Decoded transactions straight from the server, for inspecting the wire format."""
    response = tracker.api._request("GET", f"/account/transaction/{args.device}/{args.since}")
    response.raise_for_status()
    items = response.json() or []
    for item in items[: args.limit]:
        decoded = json.loads(base64.b64decode(item["Transaction"]).decode("utf-8"))
        _print({"SyncID": item.get("SyncID"), "OPCode": item.get("OPCode"), "record": decoded})


def main(argv=None):
    parser = argparse.ArgumentParser(prog="babytracker", description="Baby Tracker sync client")
    parser.add_argument("--state-dir", default=os.path.join(os.path.expanduser("~"), ".babytracker"),
                        help="where this client's device ID and local database live")
    parser.add_argument("--email", help="account email (or BABYTRACKER_EMAIL)")
    parser.add_argument("--time-zone", default=os.environ.get("TZ"),
                        help="IANA zone for records you add, e.g. America/Chicago (default: host zone)")
    parser.add_argument("--offline", action="store_true", help="don't sync before running the command")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("babies", help="list babies").set_defaults(func=cmd_babies)
    sub.add_parser("sync", help="download new records and upload queued ones").set_defaults(func=cmd_sync)
    sub.add_parser("devices", help="list devices registered on the account").set_defaults(func=cmd_devices)
    sub.add_parser("logout", help="end the session on the server").set_defaults(func=cmd_logout)

    last = sub.add_parser("last", help="show the most recent record of a kind")
    last.add_argument("kind", choices=sorted(LAST))
    last.add_argument("--baby")
    last.set_defaults(func=cmd_last)

    diaper = sub.add_parser("add-diaper", help="log a diaper")
    diaper.add_argument("kind", choices=list(DIAPER_KINDS))
    diaper.add_argument("--baby")
    diaper.add_argument("--note", default="")
    diaper.set_defaults(func=cmd_add_diaper)

    raw = sub.add_parser("raw", help="print a device's raw transactions from the server")
    raw.add_argument("device", help="device UUID (see `devices`)")
    raw.add_argument("--since", type=int, default=0, help="only transactions after this SyncID")
    raw.add_argument("--limit", type=int, default=20)
    raw.set_defaults(func=cmd_raw)

    args = parser.parse_args(argv)
    if args.command == "logout":
        args.offline = True  # no point syncing just to log out
    try:
        tracker = _connect(args)
    except AuthenticationError as err:
        raise SystemExit(f"Login rejected: {err}")
    except AccountResetError as err:
        raise SystemExit(f"{err}\nDelete the state directory ({args.state_dir}) to start over.")
    args.func(tracker, args)


if __name__ == "__main__":
    main()
