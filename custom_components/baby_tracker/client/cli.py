"""
Command line interface for the Baby Tracker sync client.

    babytracker babies
    babytracker last diaper --baby Everly
    babytracker add-diaper --baby Everly wet
    babytracker add-bottle --baby Everly --amount 4 --unit oz
    babytracker add-nursing --baby Everly --left 10 --right 8
    babytracker recent --baby Everly
    babytracker delete Diaper <object-id> --yes
    babytracker undo --baby Everly --yes
    babytracker insights --baby Everly
    babytracker next
    babytracker calendar --baby Everly --days 2
    babytracker inventory
    babytracker create-medicine Tylenol --amount 2.5 --unit ml --interval 6
    babytracker create-food Banana
    babytracker raw <device-uuid> --since 120
    babytracker                         # an interactive shell with the same commands

Every command prints JSON. Credentials come from BABYTRACKER_EMAIL / BABYTRACKER_PASSWORD or are asked
for; the password is never stored. The CLI keeps its own device ID and local
database in --state-dir (default ~/.babytracker), so it appears as its own
device in the app, separate from Home Assistant.

Run with no command (or `babytracker shell`) for an interactive shell built on
cmd2: it signs in and syncs once, then runs the same commands with tab
completion for commands, options and baby names, `help <command>`, a command
history kept between sessions and `set baby <name>` so --baby can be left out.
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


# Where _print writes: print, or the shell's own output while it runs a command
_OUTPUT = [print]


def _print(value):
    _OUTPUT[0](json.dumps(value, indent=2, default=_json_default))


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


def cmd_add_joy(tracker, args):
    _print(tracker.add_joy(_baby_id(tracker, args.baby), note=args.note, photo_path=args.photo,
                           picture_dir=_picture_dir(args)))


def cmd_attach_photo(tracker, args):
    _print(tracker.attach_photo(args.object_type, args.object_id, args.path, picture_dir=_picture_dir(args)))


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


def cmd_create_medicine(tracker, args):
    """Add a medicine to the account's list (it shows up in the app and Home Assistant)."""
    _print(tracker.create_medicine(args.name, amount_per_time=args.amount, unit=args.unit,
                                   interval_hours=args.interval, prescription=args.prescription))


def cmd_create_food(tracker, args):
    """Add a food to the account's solids list."""
    _print(tracker.create_food(args.name, is_bottle=args.bottle))


def cmd_recent(tracker, args):
    """A baby's newest records, with the type and ID that `delete` takes."""
    _print(tracker.get_recent_records(_baby_id(tracker, args.baby), limit=args.limit))


def cmd_delete(tracker, args):
    if not args.yes:
        raise SystemExit(f"This deletes {args.object_type} {args.object_id} on every device. Add --yes to confirm.")
    result = tracker.delete_record(args.object_type, args.object_id)
    _print(result)
    if result.get("status") != "success":
        raise SystemExit(1)


def cmd_undo(tracker, args):
    """Delete a baby's newest record (from the last day unless --hours says otherwise)."""
    baby_id = _baby_id(tracker, args.baby)
    if not args.yes:
        latest = tracker.get_recent_records(baby_id, limit=1, within_hours=args.hours)
        _print({"would_delete": latest[0] if latest else None})
        raise SystemExit("Add --yes to delete it." if latest else "Nothing to undo.")
    result = tracker.undo_last(baby_id, within_hours=args.hours)
    _print(result)
    if result.get("status") != "success":
        raise SystemExit(1)


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
        insight = tracker.get_insights(baby.object_id) or {}
        feed = insight.get("next_feed") or {}
        sleep = insight.get("next_sleep") or {}
        babies.append({"baby": baby.name, "predicted_at": feed.get("predicted_at"),
                       "overdue": feed.get("overdue"), "last_feed_at": feed.get("last_feed_at"),
                       "interval_hours": feed.get("interval_hours"),
                       # a nap is due, or a sleep in progress is due to end
                       "next_sleep_at": sleep.get("next_sleep_at"), "asleep": sleep.get("is_asleep"),
                       "expected_wake_at": sleep.get("expected_wake_at")})
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
    sub = parser.add_subparsers(dest="command")
    for command in COMMANDS:
        command.add_to(sub)
    sub.add_parser("shell", help="an interactive shell with these commands (the default with no command)")

    args = parser.parse_args(argv)
    if args.command == "logout":
        args.offline = True  # no point syncing just to log out
    try:
        tracker = _connect(args)
    except AuthenticationError as err:
        raise SystemExit(f"Login rejected: {err}") from None
    except AccountResetError as err:
        raise SystemExit(f"{err}\nDelete the state directory ({args.state_dir}) to start over.") from None
    if args.command in (None, "shell"):
        make_shell(tracker, args).cmdloop()
    else:
        args.func(tracker, args)


# ===== The command table, shared by the command line and the shell =====

class Command:
    """One subcommand: its name, help, how to add its arguments to a parser, and what runs."""

    def __init__(self, name, help, func, configure=None):
        self.name = name
        self.help = help
        self.func = func
        self.configure = configure or (lambda parser: None)

    def add_to(self, subparsers):
        parser = subparsers.add_parser(self.name, help=self.help)
        self.configure(parser)
        parser.set_defaults(func=self.func)
        return parser


def _last_args(p):
    p.add_argument("kind", choices=sorted(LAST))
    p.add_argument("--baby")


def _diaper_args(p):
    p.add_argument("kind", choices=list(DIAPER_KINDS))
    p.add_argument("--baby")
    p.add_argument("--note", default="")


def _joy_args(p):
    p.add_argument("--baby")
    p.add_argument("--note", default="")
    p.add_argument("--photo", help="an image file to attach (needs Pillow)")


def _attach_args(p):
    p.add_argument("object_type", help="the entry's type as `recent` shows it, e.g. Diaper")
    p.add_argument("object_id")
    p.add_argument("path", help="an image file (needs Pillow)")


def _bottle_args(p):
    p.add_argument("--baby")
    p.add_argument("--amount", type=_positive_number, required=True)
    p.add_argument("--unit", choices=["oz", "ml"], default="oz", help="unit of --amount (default: oz)")
    p.add_argument("--type", choices=["formula", "pumped"], default="formula",
                   help="what was in the bottle (default: formula)")
    p.add_argument("--note", default="")


def _nursing_args(p):
    p.add_argument("--baby")
    p.add_argument("--left", type=int, default=0, metavar="MIN", help="minutes on the left side")
    p.add_argument("--right", type=int, default=0, metavar="MIN", help="minutes on the right side")
    p.add_argument("--finish-side", choices=list(NURSING_SIDES),
                   help="side the session ended on (default: right if --right is given, else left)")
    p.add_argument("--note", default="")


def _create_medicine_args(p):
    p.add_argument("name", help="the medicine's name, e.g. Tylenol")
    p.add_argument("--amount", type=float, default=0, help="usual dose per time (default: none)")
    p.add_argument("--unit", default="", help="the dose's unit, e.g. ml, mg or drops")
    p.add_argument("--interval", type=int, default=0, metavar="HOURS", help="hours between doses (default: none)")
    p.add_argument("--prescription", action="store_true", help="it is a prescription medicine")


def _create_food_args(p):
    p.add_argument("name", help="the food's name, e.g. Banana")
    p.add_argument("--bottle", action="store_true", help="it is given from a bottle")


def _recent_args(p):
    p.add_argument("--baby")
    p.add_argument("--limit", type=int, default=10, help="how many to show (default: 10)")


def _delete_args(p):
    p.add_argument("object_type", help="the record's type as `recent` shows it, e.g. Diaper")
    p.add_argument("object_id")
    p.add_argument("--yes", action="store_true", help="confirm the delete")


def _undo_args(p):
    p.add_argument("--baby")
    p.add_argument("--hours", type=float, default=24, help="ignore records older than this (default: 24)")
    p.add_argument("--yes", action="store_true", help="delete it (without, only shows what would go)")


def _insights_args(p):
    p.add_argument("--baby", help="one baby (default: every baby)")


def _calendar_args(p):
    p.add_argument("--baby")
    p.add_argument("--days", type=int, default=1, help="how many days back to show (default: 1)")


def _raw_args(p):
    p.add_argument("device", help="device UUID (see `devices`)")
    p.add_argument("--since", type=int, default=0, help="only transactions after this SyncID")
    p.add_argument("--limit", type=int, default=20)


COMMANDS = [
    Command("babies", "list babies", cmd_babies),
    Command("sync", "download new records and upload queued ones", cmd_sync),
    Command("devices", "list devices registered on the account", cmd_devices),
    Command("logout", "end the session on the server", cmd_logout),
    Command("last", "show the most recent record of a kind", cmd_last, _last_args),
    Command("add-diaper", "log a diaper", cmd_add_diaper, _diaper_args),
    Command("add-joy", "log a joy, optionally with a photo", cmd_add_joy, _joy_args),
    Command("attach-photo", "add a photo to an existing entry", cmd_attach_photo, _attach_args),
    Command("add-bottle", "log a bottle feed", cmd_add_bottle, _bottle_args),
    Command("add-nursing", "log a nursing session", cmd_add_nursing, _nursing_args),
    Command("create-medicine", "add a medicine to the account's list", cmd_create_medicine, _create_medicine_args),
    Command("create-food", "add a food to the account's solids list", cmd_create_food, _create_food_args),
    Command("recent", "a baby's newest records, with the IDs `delete` takes", cmd_recent, _recent_args),
    Command("delete", "delete a record on every device", cmd_delete, _delete_args),
    Command("undo", "delete a baby's newest record", cmd_undo, _undo_args),
    Command("insights", "age, next feed and sleep, intake, diapers and growth percentiles", cmd_insights,
            _insights_args),
    Command("next", "each baby's predicted next feed and who is due first", cmd_next),
    Command("calendar", "a baby's feeds, sleeps, baths, visits and medicines", cmd_calendar, _calendar_args),
    Command("inventory", "pumped milk in store", cmd_inventory),
    Command("raw", "print a device's raw transactions from the server", cmd_raw, _raw_args),
]


# ===== The interactive shell =====

def make_shell(tracker, args):
    """A cmd2 shell over a connected tracker: the same commands, with completion and history."""
    import cmd2
    import cmd2.plugin  # noqa: F401 - the hook type hint below needs it

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    class Shell(cmd2.Cmd):
        """Baby Tracker shell."""

        def __init__(self):
            super().__init__(allow_cli_args=False,
                             persistent_history_file=os.path.join(args.state_dir, "history"))
            self.tracker = tracker
            self.prompt = "babytracker> "
            self.default_category = "Shell"
            self.register_postparsing_hook(self._help_through_aliases)
            self.baby = ""
            self.add_settable(cmd2.Settable("baby", str, "baby that commands act on when --baby is not given",
                                            self, choices_provider=Shell.baby_names))
            # cmd2's own commands that don't suit a sync client
            self.hidden_commands.extend(["alias", "macro", "edit", "run_pyscript", "run_script", "shell",
                                         "shortcuts"])
            # The hyphenated command names from the command line work here too
            for command in COMMANDS:
                if "-" in command.name:
                    self.aliases[command.name] = command.name.replace("-", "_")
            names = ", ".join(b.name for b in tracker.get_all_babies())
            self.intro = (f"Baby Tracker shell. Babies: {names}.\n"
                          "Type help for the commands, help <command> for its options, "
                          "set baby <name> to pick a baby, quit to leave.")

        def baby_names(self):
            return [b.name for b in self.tracker.get_all_babies()]

        def _help_through_aliases(self, data: cmd2.plugin.PostparsingData) -> cmd2.plugin.PostparsingData:
            """`help add-diaper` finds add_diaper (help doesn't look through aliases itself)."""
            statement = data.statement
            if statement.command == "help" and "-" in statement.args:
                data.statement = self.statement_parser.parse("help " + statement.args.replace("-", "_"))
            return data

        def run(self, func, ns):
            """Run a command function, keeping errors inside the shell."""
            if getattr(ns, "baby", None) is None and self.baby and hasattr(ns, "baby"):
                ns.baby = self.baby
            ns.state_dir = args.state_dir
            ns.time_zone = args.time_zone
            ns.offline = True
            _OUTPUT[0] = self.poutput
            try:
                func(self.tracker, ns)
            except SystemExit as err:  # the command functions report problems with SystemExit
                if err.code not in (None, 0):
                    self.perror(str(err.code))
            except (AuthenticationError, AccountResetError) as err:
                self.perror(f"{err}")
            except Exception as err:  # noqa: BLE001 - a shell must survive any command failure
                self.perror(f"{type(err).__name__}: {err}")
            finally:
                _OUTPUT[0] = print

    for command in COMMANDS:
        setattr(Shell, f"do_{command.name.replace('-', '_')}", _shell_command(command, Shell))
    return Shell()


def _shell_command(command, shell_class):
    """A do_<name> method for the shell from a Command, with baby-name completion."""
    import cmd2

    parser = cmd2.Cmd2ArgumentParser(prog=command.name, description=command.help)
    command.configure(parser)
    for action in parser._actions:
        if action.dest == "baby":
            action.set_choices_provider(shell_class.baby_names)

    def do(self, ns):
        self.run(command.func, ns)
        if command.name == "logout":
            return True  # the session is over; leave the shell

    # cmd2 files the parser under the command name it takes from the function's name
    do.__name__ = do.__qualname__ = f"do_{command.name.replace('-', '_')}"
    do.__doc__ = command.help
    cmd2.categorize(do, "Baby Tracker")
    return cmd2.with_argparser(parser)(do)


if __name__ == "__main__":
    main()
