"""
Command line interface for the Baby Tracker sync client.

    babytracker babies
    babytracker last diaper --baby Everly
    babytracker add-diaper --baby Everly wet
    babytracker add-bottle --baby Everly --amount 4 --unit oz
    babytracker add-nursing --baby Everly --left 10 --right 8
    babytracker insights --baby Everly
    babytracker next
    babytracker calendar --baby Everly --days 2
    babytracker inventory
    babytracker raw <device-uuid> --since 120

Every command prints JSON. Credentials come from BABYTRACKER_EMAIL / BABYTRACKER_PASSWORD or are asked
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
from datetime import datetime, timedelta

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

NURSING_SIDES = {"left": 1, "right": 2}  # the app's NursingFinishSide

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


def _json_default(value):
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _print(value):
    print(json.dumps(value, indent=2, default=_json_default))


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


def cmd_add_bottle(tracker, args):
    add = tracker.add_pumped if args.type == "pumped" else tracker.add_formula
    _print(add(_baby_id(tracker, args.baby), None, amount=args.amount, is_english_measure=args.unit == "oz",
               note=args.note))


def cmd_add_nursing(tracker, args):
    if args.left <= 0 and args.right <= 0:
        raise SystemExit("Give --left and/or --right minutes")
    # The side the session ended on: as given, else the right side if it was used
    finish = args.finish_side or ("right" if args.right > 0 else "left")
    _print(tracker.add_nursing(_baby_id(tracker, args.baby), None, left_duration=args.left,
                               right_duration=args.right, finish_side=NURSING_SIDES[finish], note=args.note))


def cmd_insights(tracker, args):
    """One baby's insights with --baby, else every baby's (a list)."""
    if args.baby or len(tracker.get_all_babies()) == 1:
        _print(tracker.get_insights(_baby_id(tracker, args.baby)))
    else:
        _print([tracker.get_insights(baby.object_id) for baby in tracker.get_all_babies()])


def cmd_next(tracker, args):
    """Each baby's predicted next feed, soonest first, and who is due first."""
    babies = []
    for baby in tracker.get_all_babies():
        feed = (tracker.get_insights(baby.object_id) or {}).get("next_feed") or {}
        babies.append({"baby": baby.name, "predicted_at": feed.get("predicted_at"),
                       "overdue": feed.get("overdue"), "last_feed_at": feed.get("last_feed_at"),
                       "interval_hours": feed.get("interval_hours")})
    # Babies with no prediction (nothing logged yet) go last
    babies.sort(key=lambda b: (b["predicted_at"] is None, datetime.fromisoformat(b["predicted_at"])
                               if b["predicted_at"] else datetime.max))
    first = babies[0] if babies and babies[0]["predicted_at"] else None
    _print({"due_first": {"baby": first["baby"], "predicted_at": first["predicted_at"]} if first else None,
            "babies": babies})


def cmd_calendar(tracker, args):
    """Feeds, sleeps, baths, doctor visits and medicines from N days ago until tomorrow."""
    baby_id = _baby_id(tracker, args.baby)
    now = datetime.now(tracker._local_tz())
    _print(tracker.get_events_between(baby_id, now - timedelta(days=args.days), now + timedelta(days=1)))


def cmd_inventory(tracker, args):
    _print(tracker.get_pumped_milk_inventory())


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


def _positive_number(text):
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if value <= 0:
        raise argparse.ArgumentTypeError("must be more than zero")
    return value


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

    bottle = sub.add_parser("add-bottle", help="log a bottle feed")
    bottle.add_argument("--baby")
    bottle.add_argument("--amount", type=_positive_number, required=True)
    bottle.add_argument("--unit", choices=["oz", "ml"], default="oz", help="unit of --amount (default: oz)")
    bottle.add_argument("--type", choices=["formula", "pumped"], default="formula",
                        help="what was in the bottle (default: formula)")
    bottle.add_argument("--note", default="")
    bottle.set_defaults(func=cmd_add_bottle)

    nursing = sub.add_parser("add-nursing", help="log a nursing session")
    nursing.add_argument("--baby")
    nursing.add_argument("--left", type=int, default=0, metavar="MIN", help="minutes on the left side")
    nursing.add_argument("--right", type=int, default=0, metavar="MIN", help="minutes on the right side")
    nursing.add_argument("--finish-side", choices=list(NURSING_SIDES),
                         help="side the session ended on (default: right if --right is given, else left)")
    nursing.add_argument("--note", default="")
    nursing.set_defaults(func=cmd_add_nursing)

    insights = sub.add_parser("insights", help="age, next feed, intake, diapers and growth percentiles")
    insights.add_argument("--baby", help="one baby (default: every baby)")
    insights.set_defaults(func=cmd_insights)

    sub.add_parser("next", help="each baby's predicted next feed and who is due first").set_defaults(func=cmd_next)

    calendar = sub.add_parser("calendar", help="a baby's feeds, sleeps, baths, visits and medicines")
    calendar.add_argument("--baby")
    calendar.add_argument("--days", type=int, default=1, help="how many days back to show (default: 1)")
    calendar.set_defaults(func=cmd_calendar)

    sub.add_parser("inventory", help="pumped milk in store").set_defaults(func=cmd_inventory)

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
