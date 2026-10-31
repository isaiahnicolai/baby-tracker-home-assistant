"""
Insights derived from a baby's logged data: age, feed timing, intake, diapers
and growth.

Everything here is a pure function over plain data. There is no sqlite, no
network and no Home Assistant; datetimes are timezone-aware and "local" hours
are taken from the timezone of the datetime that is passed in (``now``). The
:class:`~babytracker_client.core.BabyTracker` insight methods gather the rows
and call these functions.

These are rules of thumb taken from AAP / WHO guidance. They are meant to
prompt a look at the data, not to diagnose anything.
"""

from __future__ import annotations

import csv
import dataclasses
import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from itertools import pairwise
from pathlib import Path
from typing import Any, NamedTuple

# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------

ML_PER_OZ = 29.5735
KG_PER_LB = 0.45359237
CM_PER_INCH = 2.54
DAYS_PER_MONTH = 30.4375  # 365.25 / 12, the WHO definition of a month


def oz_to_ml(oz: float) -> float:
    return oz * ML_PER_OZ


def ml_to_oz(ml: float) -> float:
    return ml / ML_PER_OZ


def lb_to_kg(lb: float) -> float:
    return lb * KG_PER_LB


def kg_to_lb(kg: float) -> float:
    return kg / KG_PER_LB


def inches_to_cm(inches: float) -> float:
    return inches * CM_PER_INCH


def cm_to_inches(cm: float) -> float:
    return cm / CM_PER_INCH


def to_dict(result: Any) -> Any:
    """A result dataclass as a plain dict, with datetimes as ISO strings."""
    if dataclasses.is_dataclass(result) and not isinstance(result, type):
        return {f.name: to_dict(getattr(result, f.name)) for f in dataclasses.fields(result)}
    if isinstance(result, datetime):
        return result.isoformat()
    if isinstance(result, (list, tuple)):
        return [to_dict(item) for item in result]
    if isinstance(result, dict):
        return {key: to_dict(value) for key, value in result.items()}
    return result


def parse_api_date(value: Any) -> datetime | None:
    """A datetime from an API date string ("yyyy-MM-dd HH:mm:ss +0000"), or None.

    Datetimes pass through (naive ones are taken as UTC); an empty or
    unrecognised value gives None.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC)
    text = str(value).strip().replace(" UTC", " +0000").replace(" GMT", " +0000")
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# --------------------------------------------------------------------------
# 1. Age
# --------------------------------------------------------------------------

FULL_TERM_DAYS = 280                 # 40 weeks
PREMATURE_BELOW_GESTATION_DAYS = 259  # born before 37 weeks is premature
MIN_PLAUSIBLE_GESTATION_DAYS = 154   # 22 weeks; a due date implying less is bad data
CORRECTION_ENDS_MONTHS = 24          # AAP: correct for prematurity until 24 months corrected


@dataclass(frozen=True)
class AgeInfo:
    chronological_days: int
    corrected_days: int           # may be negative for a preemie still before their due date
    chronological_months: float
    corrected_months: float
    gestation_days: int | None  # None without a (plausible) due date
    premature: bool
    correction_days: int           # days subtracted; 0 when no correction applies
    correction_applied: bool


def age_info(dob: Any, due_date: Any, on: datetime) -> AgeInfo | None:
    """Chronological and corrected age on a date.

    ``dob`` and ``due_date`` are datetimes or API date strings; ``due_date``
    may be missing. Babies born before 37 weeks (259 days) get a corrected
    age of ``chronological - (280 - gestation_days)`` until they reach 24
    months corrected, after which corrected equals chronological (AAP). A due
    date less than 3 weeks after the birth, on or before it, or implying a
    gestation under 22 weeks (bad data) is not treated as prematurity.
    Returns None without a date of birth.
    """
    born = parse_api_date(dob)
    if born is None:
        return None
    if on.tzinfo is None:
        on = on.replace(tzinfo=UTC)
    chronological = max(0, math.floor((on - born).total_seconds() / 86400))

    due = parse_api_date(due_date)
    gestation: int | None = None
    correction = 0
    premature = False
    if due is not None:
        early_days = round((due - born).total_seconds() / 86400)
        implied = FULL_TERM_DAYS - early_days
        if early_days > 0 and implied >= MIN_PLAUSIBLE_GESTATION_DAYS:
            gestation = implied
            if implied < PREMATURE_BELOW_GESTATION_DAYS:
                premature = True
                correction = early_days
        elif early_days <= 0 and -early_days <= 7 * 6:
            gestation = FULL_TERM_DAYS - early_days  # born at or after the due date

    corrected = chronological - correction
    if correction and corrected >= CORRECTION_ENDS_MONTHS * DAYS_PER_MONTH:
        correction = 0
        corrected = chronological
    return AgeInfo(
        chronological_days=chronological,
        corrected_days=corrected,
        chronological_months=chronological / DAYS_PER_MONTH,
        corrected_months=corrected / DAYS_PER_MONTH,
        gestation_days=gestation,
        premature=premature,
        correction_days=correction,
        correction_applied=correction > 0,
    )


# --------------------------------------------------------------------------
# 2. Next feed
# --------------------------------------------------------------------------

class Feed(NamedTuple):
    """One feed. ``end`` is None when unknown; ``amount_ml`` is None for nursing.

    ``kind`` is "Nursing", "Formula", "Pumped" or "OtherFeed".
    """

    start: datetime
    end: datetime | None
    amount_ml: float | None
    kind: str


DAY_START_HOUR = 7
DAY_END_HOUR = 19
MIN_INTERVAL_HOURS = 1.5
MAX_INTERVAL_HOURS = 6.0
MAX_USABLE_INTERVAL_HOURS = 12.0  # a longer gap is a logging gap, not an interval
SESSION_MERGE_MINUTES = 30        # feeds this close are one feed (top-ups, second side)
INTERVALS_PER_BUCKET = 8
MIN_INTERVALS = 3


@dataclass(frozen=True)
class FeedPrediction:
    predicted_at: datetime | None  # None when there are no feeds to count from
    interval_hours: float
    basis: str                        # "history" or "age_default"
    sample_count: int                 # intervals the estimate came from
    bucket: str                       # "day" (07:00-19:00) or "night"
    last_feed_at: datetime | None
    overdue: bool
    max_gap_hours: float | None    # wake-to-feed guidance, see feed_gap_guidance
    wake_by: datetime | None       # last feed + max_gap_hours


def default_interval_hours(age_days: float | None, night: bool = False) -> float:
    """
    Typical start-to-start feeding interval for an age; nights run 1 hour longer.
    Without a date of birth (None) it is the 1-2 month figure, not the newborn one.
    """
    months = 1.5 if age_days is None else age_days / DAYS_PER_MONTH
    if months < 1:
        hours = 2.5
    elif months < 2:
        hours = 3.0
    elif months < 6:
        hours = 3.5
    else:
        hours = 4.0
    return hours + (1.0 if night else 0.0)


def feed_gap_guidance(age_days: float | None, weight_kg: float | None = None,
                      birth_weight_kg: float | None = None) -> float | None:
    """Longest sensible stretch between feeds, in hours, or None when there's no limit.
    Also None when the age is unknown (no date of birth): that is no basis for waking anyone.

    AAP: wake a newborn to feed if they sleep more than 4-5 hours, until they
    have regained their birth weight (and are gaining well); most formula-fed
    babies drop the night feed at 2-4 months or about 12 lb (5.4 kg).

    4.5 h while under 14 days old or below birth weight; 5 h while under 2
    months and under 5.4 kg (an unknown weight counts as under).
    """
    if age_days is None:
        return None
    if age_days < 14:
        return 4.5
    if weight_kg is not None and birth_weight_kg is not None and weight_kg < birth_weight_kg:
        return 4.5
    if age_days / DAYS_PER_MONTH < 2 and (weight_kg is None or weight_kg < 5.4):
        return 5.0
    return None


def _is_day(moment: datetime, tz) -> bool:
    return DAY_START_HOUR <= moment.astimezone(tz).hour < DAY_END_HOUR


def _feed_session_starts(feeds: Sequence[Feed], now: datetime) -> list[datetime]:
    """Start times of feeds, with ones a few minutes after another merged into it."""
    starts: list[datetime] = []
    for feed in sorted(feeds, key=lambda f: f[0]):
        if feed[0] > now:
            continue
        if starts and feed[0] - starts[-1] < timedelta(minutes=SESSION_MERGE_MINUTES):
            continue
        starts.append(feed[0])
    return starts


def predict_next_feed(feeds: Sequence[Feed], now: datetime, age_days: float | None, *,
                      weight_kg: float | None = None,
                      birth_weight_kg: float | None = None) -> FeedPrediction:
    """When the next feed is likely, from the pattern of recent feeds.

    ``feeds`` are ``(start, end, amount_ml, kind)`` sorted ascending. Feeds
    less than 30 minutes after another count as part of it. The estimate is
    the median of the last up to 8 start-to-start intervals ending in the same
    part of the day as the next feed (day is 07:00-19:00 in ``now``'s
    timezone), falling back to all recent intervals when that part of the day
    has fewer than 3, and to age defaults when there are fewer than 3 at all.
    Clamped to 1.5-6 hours.
    """
    tz = now.tzinfo or UTC
    starts = _feed_session_starts(feeds, now)
    last = starts[-1] if starts else None

    day: list[float] = []
    night: list[float] = []
    for earlier, later in pairwise(starts):
        hours = (later - earlier).total_seconds() / 3600
        if hours > MAX_USABLE_INTERVAL_HOURS:
            continue
        (day if _is_day(later, tz) else night).append(hours)
    pooled = [
        (b - a).total_seconds() / 3600 for a, b in pairwise(starts)
        if (b - a).total_seconds() / 3600 <= MAX_USABLE_INTERVAL_HOURS
    ][-INTERVALS_PER_BUCKET:]

    def estimate(is_day: bool) -> tuple[float, str, int]:
        own = (day if is_day else night)[-INTERVALS_PER_BUCKET:]
        if len(own) >= MIN_INTERVALS:
            return statistics.median(own), "history", len(own)
        if len(pooled) >= MIN_INTERVALS:
            return statistics.median(pooled), "history", len(pooled)
        return default_interval_hours(age_days, night=not is_day), "age_default", len(pooled)

    def clamp(hours: float) -> float:
        return min(MAX_INTERVAL_HOURS, max(MIN_INTERVAL_HOURS, hours))

    # The interval depends on where the next feed lands, which depends on the
    # interval: try the daytime one, and if that lands at night use the night one.
    interval, basis, count = estimate(True)
    interval = clamp(interval)
    next_is_day = True
    if last is not None and not _is_day(last + timedelta(hours=interval), tz):
        interval, basis, count = estimate(False)
        interval = clamp(interval)
        next_is_day = False

    max_gap = feed_gap_guidance(age_days, weight_kg, birth_weight_kg)
    if last is None:
        return FeedPrediction(None, interval, basis, count, "day" if next_is_day else "night",
                              None, False, max_gap, None)
    predicted = last + timedelta(hours=interval)
    return FeedPrediction(
        predicted_at=predicted,
        interval_hours=interval,
        basis=basis,
        sample_count=count,
        bucket="day" if next_is_day else "night",
        last_feed_at=last,
        overdue=predicted < now,
        max_gap_hours=max_gap,
        wake_by=last + timedelta(hours=max_gap) if max_gap else None,
    )


# --------------------------------------------------------------------------
# 3. Intake
# --------------------------------------------------------------------------

INTAKE_ML_PER_KG_MIN = 150
INTAKE_ML_PER_KG_MAX = 200
INTAKE_CAP_ML = 960            # 32 oz
INTAKE_MIN_AGE_DAYS = 7        # the first week's intake builds up from tiny volumes
INTAKE_MAX_AGE_DAYS = 183      # about 6 months: solids make milk intake meaningless
COUNTED_KINDS = ("Formula", "Pumped")


@dataclass(frozen=True)
class IntakeAssessment:
    actual_ml: float
    expected_min_ml: int | None
    expected_max_ml: int | None
    status: str          # "low", "ok", "high" or "unknown"
    reason: str
    bottle_feeds: int
    nursing_feeds: int
    ml_per_kg: float | None


def intake_assessment(feeds_last_24h: Sequence[Feed], weight_kg: float | None,
                      age_days: float | None, feeding_type: str | None = None) -> IntakeAssessment:
    """Compare the last 24 hours of bottle milk with 150-200 ml per kg per day.

    The AAP's 2.5 oz per lb (about 165 ml/kg) sits inside that range, and the
    day's total is capped at 960 ml (32 oz). Only Formula and Pumped amounts
    are summed. The result is "unknown" with no weight, under a week or over
    about 6 months old, with no feeds logged, when nursing makes up more than
    half of the feeds, or when ``feeding_type`` says the baby is breastfed
    ("breast"/"nursing") or on solids.
    """
    bottles = [f for f in feeds_last_24h if f.kind in COUNTED_KINDS and f.amount_ml]
    nursing = [f for f in feeds_last_24h if f.kind == "Nursing"]
    # Rounded so float summation noise (which differs between Python versions)
    # can't push a total that is exactly on a bound over it
    actual = round(float(sum(f.amount_ml for f in bottles)), 1)
    total_feeds = len(feeds_last_24h)

    def unknown(reason: str, lo=None, hi=None) -> IntakeAssessment:
        per_kg = actual / weight_kg if weight_kg else None
        return IntakeAssessment(actual, lo, hi, "unknown", reason, len(bottles), len(nursing), per_kg)

    if not weight_kg or weight_kg <= 0:
        return unknown("No weight recorded")
    lo = int(round(min(INTAKE_CAP_ML, weight_kg * INTAKE_ML_PER_KG_MIN)))
    hi = int(round(min(INTAKE_CAP_ML, weight_kg * INTAKE_ML_PER_KG_MAX)))
    if age_days is None:
        return unknown("No date of birth, so the age is unknown", lo, hi)
    if age_days < INTAKE_MIN_AGE_DAYS:
        return unknown("Intake builds up over the first week", lo, hi)
    if age_days >= INTAKE_MAX_AGE_DAYS:
        return unknown("Over about 6 months, solids make milk volume a poor guide", lo, hi)
    if (feeding_type or "").lower() in ("breast", "breastfed", "nursing", "solids"):
        return unknown(f"Feeding type is {feeding_type}", lo, hi)
    if total_feeds == 0:
        return unknown("No feeds logged in the last 24 hours", lo, hi)
    if len(nursing) * 2 > total_feeds:
        return unknown("Mostly nursing, which isn't measured in ml", lo, hi)

    per_kg = actual / weight_kg
    if actual < lo:
        status, reason = "low", f"{actual:.0f} ml is under {lo} ml ({INTAKE_ML_PER_KG_MIN} ml/kg)"
    elif actual > hi:
        status, reason = "high", f"{actual:.0f} ml is over {hi} ml ({INTAKE_ML_PER_KG_MAX} ml/kg)"
    else:
        status, reason = "ok", f"{actual:.0f} ml is within {lo}-{hi} ml for {weight_kg:g} kg"
    return IntakeAssessment(actual, lo, hi, status, reason, len(bottles), len(nursing), per_kg)


# --------------------------------------------------------------------------
# 4. Diapers
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DiaperAdequacy:
    status: str                # "ok", "low" or "unknown"
    wet_status: str
    stool_status: str
    wet_count: int | None
    dirty_count: int | None
    day_of_life: int           # the day of birth is day 1
    expected_min_wet: int
    low_below_wet: int         # fewer wet diapers than this is flagged
    expected_min_dirty: int    # 0 once infrequent stools are normal
    note: str


def diaper_adequacy(wet_count: int | None, dirty_count: int | None,
                    age_days: float | None) -> DiaperAdequacy:
    """Is the wet and dirty diaper count enough for the baby's age?

    Wet diapers, by day of life: day 1 at least 1, day 2 at least 2, day 3 at
    least 3, day 4 at least 4, from day 5 six or more are expected and fewer
    than 5 is flagged. Dirty diapers: in the first month at least 3 a day are
    expected (fewer in the first 3 days, which follow the day of life); after
    6 weeks infrequent stools are normal; in between there is no flag.
    """
    if age_days is None:
        # No date of birth: there is nothing to judge the counts against
        return DiaperAdequacy("unknown", "unknown", "unknown", wet_count, dirty_count, 0, 0, 0, 0,
                              "No date of birth, so the age is unknown")
    day = int(age_days) + 1
    if day < 5:
        expected_wet = low_below = day
    else:
        expected_wet, low_below = 6, 5
    if age_days < DAYS_PER_MONTH:
        expected_dirty = min(day, 3)
        note = "At least 3 stools a day are expected in the first month"
    elif age_days < 42:
        expected_dirty = 0
        note = "Stools are settling into their own pattern"
    else:
        expected_dirty = 0
        note = "Infrequent stools are normal after 6 weeks"

    wet_status = "unknown" if wet_count is None else ("low" if wet_count < low_below else "ok")
    stool_status = "unknown" if dirty_count is None else ("low" if dirty_count < expected_dirty else "ok")
    if "low" in (wet_status, stool_status):
        status = "low"
    elif "unknown" in (wet_status, stool_status):
        status = "unknown" if wet_status == "unknown" else wet_status
    else:
        status = "ok"
    return DiaperAdequacy(status, wet_status, stool_status, wet_count, dirty_count, day,
                          expected_wet, low_below, expected_dirty, note)


# --------------------------------------------------------------------------
# 5. Growth percentiles (WHO Child Growth Standards, 0-24 months)
# --------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent / "data"
MAX_GROWTH_MONTHS = 24
MAX_Z = 5.0
GROWTH_KINDS = ("weight", "length", "head")
_NORMAL = statistics.NormalDist()
_Z3 = _NORMAL.inv_cdf(0.03)
_Z97 = _NORMAL.inv_cdf(0.97)


@dataclass(frozen=True)
class GrowthPercentile:
    kind: str
    age_months: float
    value: float
    z: float                # clamped to +-5
    percentile: float       # 0-100
    p3: float
    p50: float
    p97: float


def normalize_sex(sex: Any) -> str:
    """"male" or "female" from a Baby's gender flag (truthy is male) or a name."""
    if isinstance(sex, str):
        text = sex.strip().lower()
        if text in ("male", "m", "boy", "b"):
            return "male"
        if text in ("female", "f", "girl", "g"):
            return "female"
        raise ValueError(f"Unknown sex {sex!r}")
    return "male" if sex else "female"


@cache
def _lms_table(sex: str, kind: str) -> tuple[tuple[float, float, float, float], ...]:
    """(month, L, M, S) rows of a WHO table, ascending by month."""
    path = DATA_DIR / f"who-{'boys' if sex == 'male' else 'girls'}-{kind}.csv"
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = [
            (float(r["Month"]), float(r["L"]), float(r["M"]), float(r["S"]))
            for r in csv.DictReader(handle)
        ]
    return tuple(sorted(rows))


def _lms_at(sex: str, kind: str, months: float) -> tuple[float, float, float]:
    """L, M and S at an age, linearly interpolated between the tabulated months."""
    table = _lms_table(sex, kind)
    months = min(max(months, table[0][0]), table[-1][0])
    for (m0, *lms0), (m1, *lms1) in pairwise(table):
        if m0 <= months <= m1:
            frac = (months - m0) / (m1 - m0) if m1 > m0 else 0.0
            return tuple(a + (b - a) * frac for a, b in zip(lms0, lms1, strict=True))
    return tuple(table[-1][1:])


def _value_at_z(lam: float, m: float, s: float, z: float) -> float:
    if lam == 0:
        return m * math.exp(s * z)
    return m * (1 + lam * s * z) ** (1 / lam)


def growth_percentile(sex: Any, age_months: float, measure: float,
                      kind: str) -> GrowthPercentile | None:
    """Where a measurement sits on the WHO growth standard for age and sex.

    ``measure`` is kg for ``kind="weight"`` and cm for "length" and "head".
    ``age_months`` is a float and should be the corrected age for a preemie.
    L, M and S are interpolated linearly between the tabulated months;
    ``z = ((X/M)**L - 1) / (L*S)`` (``ln(X/M)/S`` when L is 0), clamped to
    +-5. Also returns the 3rd, 50th and 97th percentile values at that age.
    Returns None for a non-positive measurement or an age over 24 months.
    Raises ValueError for an unknown ``kind`` or ``sex``.
    """
    if kind not in GROWTH_KINDS:
        raise ValueError(f"kind must be one of {GROWTH_KINDS}, not {kind!r}")
    sex = normalize_sex(sex)
    if measure is None or measure <= 0 or age_months > MAX_GROWTH_MONTHS:
        return None
    age = max(0.0, age_months)
    lam, m, s = _lms_at(sex, kind, age)
    z = math.log(measure / m) / s if lam == 0 else ((measure / m) ** lam - 1) / (lam * s)
    z = max(-MAX_Z, min(MAX_Z, z))
    return GrowthPercentile(
        kind=kind,
        age_months=age,
        value=measure,
        z=z,
        percentile=_NORMAL.cdf(z) * 100,
        p3=_value_at_z(lam, m, s, _Z3),
        p50=m,
        p97=_value_at_z(lam, m, s, _Z97),
    )


# --------------------------------------------------------------------------
# 6. Weight velocity
# --------------------------------------------------------------------------

MIN_VELOCITY_SPAN_DAYS = 5
# Approximate normal gain in g/day. These round the WHO weight velocity medians
# (about 30 g/day at 1 month falling to about 10 g/day by a year) into bands.
VELOCITY_BANDS = (
    (4 * DAYS_PER_MONTH, 20.0, 35.0),    # 0-4 months
    (6 * DAYS_PER_MONTH, 12.0, 20.0),    # 4-6 months
    (12 * DAYS_PER_MONTH, 8.0, 12.0),    # 6-12 months
)
VELOCITY_MIN_AGE_DAYS = 14  # newborns lose weight first; compare with birth weight instead


@dataclass(frozen=True)
class WeightVelocity:
    status: str                              # "low", "ok", "high" or "unknown"
    grams_per_day: float | None
    expected_min: float | None
    expected_max: float | None
    span_days: float | None
    from_at: datetime | None
    to_at: datetime | None
    reason: str


def weight_velocity(measurements: Sequence[tuple[datetime, float]],
                    age_days: float) -> WeightVelocity:
    """Weight gain in g/day between the latest weight and the latest earlier one at least 5 days before.

    ``measurements`` are ``(datetime, kg)``. Expected bands: 0-4 months 20-35
    g/day, 4-6 months 12-20, 6-12 months 8-12. Unknown under 14 days old (the
    early dip and regain) or over a year old.
    """
    def result(status, reason, **kw):
        return WeightVelocity(status, kw.get("g"), kw.get("lo"), kw.get("hi"), kw.get("span"),
                              kw.get("a"), kw.get("b"), reason)

    points = sorted((p for p in measurements if p[1]), key=lambda p: p[0])
    if len(points) < 2:
        return result("unknown", "Needs two weights")
    latest = points[-1]
    earlier = next((p for p in reversed(points[:-1])
                    if latest[0] - p[0] >= timedelta(days=MIN_VELOCITY_SPAN_DAYS)), None)
    if earlier is None:
        return result("unknown", f"Needs two weights at least {MIN_VELOCITY_SPAN_DAYS} days apart")
    span = (latest[0] - earlier[0]).total_seconds() / 86400
    grams = (latest[1] - earlier[1]) * 1000 / span

    band = next(((lo, hi) for limit, lo, hi in VELOCITY_BANDS if age_days < limit), None)
    if age_days < VELOCITY_MIN_AGE_DAYS or band is None:
        return result("unknown", "No expected range for this age",
                      g=grams, span=span, a=earlier[0], b=latest[0])
    lo, hi = band
    status = "low" if grams < lo else "high" if grams > hi else "ok"
    return result(status, f"{grams:.0f} g/day against {lo:.0f}-{hi:.0f} g/day expected",
                  g=grams, lo=lo, hi=hi, span=span, a=earlier[0], b=latest[0])
