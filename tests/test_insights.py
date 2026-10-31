"""Insights (insights.py): pure functions over plain data, plus BabyTracker.get_insights."""
import csv
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from babytracker_client import insights
from babytracker_client.insights import Feed
from helpers import EVERLY, TWIN

CHICAGO = ZoneInfo("America/Chicago")
UTC = UTC


def at(day, hour=0, minute=0, tz=CHICAGO):
    return datetime(2026, 6, day, hour, minute, tzinfo=tz)


def feeds_at(*moments, amount=None, kind="Formula"):
    return [Feed(m, None, amount, kind) for m in moments]


# ----- units -----

def test_unit_conversions():
    assert insights.oz_to_ml(1) == pytest.approx(29.5735)
    assert insights.ml_to_oz(29.5735) == pytest.approx(1)
    assert insights.lb_to_kg(10) == pytest.approx(4.5359237)
    assert insights.kg_to_lb(insights.lb_to_kg(7.5)) == pytest.approx(7.5)
    assert insights.inches_to_cm(20) == pytest.approx(50.8)
    assert insights.cm_to_inches(50.8) == pytest.approx(20)


def test_parse_api_date():
    assert insights.parse_api_date("2026-06-01 12:00:00 +0000") == datetime(2026, 6, 1, 12, tzinfo=UTC)
    assert insights.parse_api_date("2026-06-01 12:00:00 UTC") == datetime(2026, 6, 1, 12, tzinfo=UTC)
    assert insights.parse_api_date(datetime(2026, 6, 1)) == datetime(2026, 6, 1, tzinfo=UTC)
    assert insights.parse_api_date("") is None
    assert insights.parse_api_date(None) is None
    assert insights.parse_api_date("garbage") is None


# ----- 1. age -----

def test_age_of_a_full_term_baby():
    info = insights.age_info("2026-03-01 00:00:00 +0000", "2026-03-01 00:00:00 +0000",
                             datetime(2026, 4, 10, 12, tzinfo=UTC))
    assert info.chronological_days == 40
    assert info.corrected_days == 40
    assert not info.premature and not info.correction_applied
    assert info.chronological_months == pytest.approx(40 / 30.4375)


def test_corrected_age_for_a_baby_born_six_weeks_early():
    dob = datetime(2026, 3, 1, tzinfo=UTC)
    due = dob + timedelta(days=42)
    info = insights.age_info(dob, due, dob + timedelta(days=92))
    assert info.chronological_days == 92
    assert info.corrected_days == 50
    assert info.gestation_days == 280 - 42
    assert info.premature and info.correction_applied
    assert info.correction_days == 42
    assert info.corrected_months == pytest.approx(50 / 30.4375)


def test_corrected_age_is_negative_before_the_due_date():
    dob = datetime(2026, 3, 1, tzinfo=UTC)
    info = insights.age_info(dob, dob + timedelta(days=42), dob + timedelta(days=10))
    assert info.corrected_days == -32


def test_correction_stops_at_24_months_corrected():
    dob = datetime(2024, 1, 1, tzinfo=UTC)
    due = dob + timedelta(days=42)
    before = insights.age_info(dob, due, dob + timedelta(days=42 + 700))
    assert before.correction_applied and before.corrected_days == 700
    after = insights.age_info(dob, due, dob + timedelta(days=42 + 731))
    assert not after.correction_applied
    assert after.corrected_days == after.chronological_days == 773


def test_a_slightly_early_baby_is_not_corrected():
    dob = datetime(2026, 3, 1, tzinfo=UTC)
    info = insights.age_info(dob, dob + timedelta(days=14), dob + timedelta(days=60))  # 38 weeks
    assert not info.premature
    assert info.corrected_days == info.chronological_days == 60
    assert info.gestation_days == 266


def test_age_without_a_due_date_or_dob():
    dob = datetime(2026, 3, 1, tzinfo=UTC)
    info = insights.age_info(dob, None, dob + timedelta(days=30))
    assert info.corrected_days == info.chronological_days == 30
    assert info.gestation_days is None
    assert insights.age_info("", None, dob) is None
    assert insights.age_info(None, dob, dob) is None


def test_an_absurd_due_date_is_ignored():
    dob = datetime(2026, 3, 1, tzinfo=UTC)
    info = insights.age_info(dob, dob + timedelta(days=200), dob + timedelta(days=30))
    assert not info.premature and info.corrected_days == 30


# ----- 2. next feed -----

def test_eight_feeds_every_three_hours_predict_three_hours_after_the_last():
    start = at(10, 6)
    moments = [start + timedelta(hours=3 * i) for i in range(8)]
    now = moments[-1] + timedelta(minutes=30)
    result = insights.predict_next_feed(feeds_at(*moments), now, age_days=60)
    assert result.predicted_at == moments[-1] + timedelta(hours=3)
    assert result.interval_hours == 3.0
    assert result.basis == "history"
    assert result.sample_count >= 3
    assert result.last_feed_at == moments[-1]
    assert not result.overdue


def test_an_overdue_prediction_is_flagged():
    moments = [at(10, 6) + timedelta(hours=3 * i) for i in range(6)]
    result = insights.predict_next_feed(feeds_at(*moments), moments[-1] + timedelta(hours=4), age_days=60)
    assert result.overdue


def test_age_defaults_when_fewer_than_three_intervals():
    last = at(10, 12)
    feeds = feeds_at(last - timedelta(hours=1), last)  # one interval
    for age_days, hours in [(10, 2.5), (45, 3.0), (100, 3.5), (200, 4.0)]:
        result = insights.predict_next_feed(feeds, last + timedelta(hours=1), age_days)
        assert result.basis == "age_default"
        assert result.interval_hours == hours
        assert result.predicted_at == last + timedelta(hours=hours)


def test_night_defaults_run_an_hour_longer():
    last = at(10, 22)
    result = insights.predict_next_feed(feeds_at(last), last + timedelta(minutes=10), age_days=10)
    assert result.bucket == "night"
    assert result.interval_hours == 3.5
    assert result.predicted_at == last + timedelta(hours=3.5)


def test_no_feeds_gives_no_prediction():
    result = insights.predict_next_feed([], at(10, 12), age_days=20)
    assert result.predicted_at is None
    assert result.basis == "age_default"
    assert result.sample_count == 0
    assert result.last_feed_at is None


def test_day_and_night_intervals_are_kept_apart():
    # Every 2 hours by day, every 4 hours overnight, two days running
    day_one = [at(10, h) for h in (7, 9, 11, 13, 15, 17)] + [at(10, 21), at(11, 1), at(11, 5)]
    day_two = [at(11, h) for h in (7, 9, 11, 13, 15, 17)]
    feeds = feeds_at(*day_one, *day_two)

    daytime = insights.predict_next_feed(feeds[:-1], at(11, 15, 30), age_days=90)
    assert daytime.bucket == "day"
    assert daytime.interval_hours == 2.0
    assert daytime.predicted_at == at(11, 17)

    # 2 hours after 17:00 would be 19:00, which is night, so the night interval applies
    evening = insights.predict_next_feed(feeds, at(11, 17, 30), age_days=90)
    assert evening.bucket == "night"
    assert evening.interval_hours == 4.0
    assert evening.predicted_at == at(11, 21)


def test_local_hours_follow_the_timezone_of_now():
    # An hour that is day in one zone and night in the other tells them apart
    moment = datetime(2026, 6, 10, 19, 0, tzinfo=UTC)  # 14:00 Chicago (day), 19:00 UTC (night)
    chicago = insights.predict_next_feed(feeds_at(moment), moment.astimezone(CHICAGO), age_days=100)
    utc = insights.predict_next_feed(feeds_at(moment), moment, age_days=100)
    assert chicago.bucket == "day" and chicago.interval_hours == 3.5
    assert utc.bucket == "night" and utc.interval_hours == 4.5


def test_interval_is_clamped_to_1_5_to_6_hours():
    slow = [at(10, 0) + timedelta(hours=7 * i) for i in range(6)]
    assert insights.predict_next_feed(feeds_at(*slow), slow[-1] + timedelta(hours=1), 100).interval_hours == 6.0
    fast = [at(10, 8) + timedelta(minutes=45 * i) for i in range(6)]
    assert insights.predict_next_feed(feeds_at(*fast), fast[-1] + timedelta(minutes=5), 100).interval_hours == 1.5


def test_feeds_close_together_count_as_one_feed():
    base = [at(10, 6) + timedelta(hours=3 * i) for i in range(6)]
    top_ups = [m + timedelta(minutes=15) for m in base]
    feeds = sorted(feeds_at(*base, *top_ups))
    result = insights.predict_next_feed(feeds, base[-1] + timedelta(hours=1), age_days=100)
    assert result.interval_hours == 3.0
    assert result.last_feed_at == base[-1]


def test_logging_gaps_are_not_intervals():
    moments = [at(10, 6), at(10, 9), at(10, 12), at(10, 15), at(10, 18), at(11, 18)]  # 24 h gap last
    result = insights.predict_next_feed(feeds_at(*moments[:-1]), at(10, 18, 30), age_days=100)
    with_gap = insights.predict_next_feed(feeds_at(*moments), at(11, 18, 30), age_days=100)
    assert result.interval_hours == with_gap.interval_hours == 3.0


def test_feeds_in_the_future_are_ignored():
    now = at(10, 12)
    result = insights.predict_next_feed(feeds_at(now - timedelta(hours=3), now + timedelta(hours=1)), now, 10)
    assert result.last_feed_at == now - timedelta(hours=3)


@pytest.mark.parametrize("age_days, weight, birth, expected", [
    (10, None, None, 4.5),      # under two weeks
    (13, 3.4, 3.4, 4.5),
    (30, 3.5, 3.6, 4.5),        # below birth weight
    (30, 4.0, 3.6, 5.0),        # regained, under 2 months, under 5.4 kg
    (40, None, None, 5.0),      # weight unknown counts as under
    (40, 5.6, 3.6, None),       # past 12 lb
    (70, 4.5, 3.6, None),       # past 2 months
    (200, 7.0, 3.5, None),
])
def test_feed_gap_guidance(age_days, weight, birth, expected):
    assert insights.feed_gap_guidance(age_days, weight, birth) == expected


def test_prediction_carries_the_wake_by_time():
    last = at(10, 22)
    result = insights.predict_next_feed(feeds_at(last), last + timedelta(hours=1), age_days=8)
    assert result.max_gap_hours == 4.5
    assert result.wake_by == last + timedelta(hours=4.5)
    older = insights.predict_next_feed(feeds_at(last), last, age_days=200)
    assert older.max_gap_hours is None and older.wake_by is None


# ----- 3. intake -----

def bottles(total_ml, count=6, kind="Formula"):
    start = at(10, 6)
    return [Feed(start + timedelta(hours=3 * i), None, total_ml / count, kind) for i in range(count)]


@pytest.mark.parametrize("ml, status", [(500, "low"), (599, "low"), (600, "ok"), (700, "ok"), (800, "ok"), (801, "high"), (950, "high")])
def test_intake_for_a_four_kilo_month_old(ml, status):
    result = insights.intake_assessment(bottles(ml), 4.0, 30, "formula")
    assert result.status == status
    assert (result.expected_min_ml, result.expected_max_ml) == (600, 800)
    assert result.actual_ml == pytest.approx(ml)
    assert result.ml_per_kg == pytest.approx(ml / 4)
    assert result.reason


def test_intake_counts_only_formula_and_pumped():
    feeds = bottles(300) + bottles(300, kind="Pumped") + bottles(500, kind="OtherFeed")
    result = insights.intake_assessment(feeds, 4.0, 30)
    assert result.actual_ml == pytest.approx(600)
    assert result.status == "ok"
    assert result.bottle_feeds == 12


def test_intake_is_capped_at_960_ml():
    result = insights.intake_assessment(bottles(1000), 6.0, 120)
    assert (result.expected_min_ml, result.expected_max_ml) == (900, 960)
    assert result.status == "high"
    heavy = insights.intake_assessment(bottles(1000), 8.0, 150)
    assert (heavy.expected_min_ml, heavy.expected_max_ml) == (960, 960)


def test_intake_is_unknown_when_mostly_nursing():
    feeds = [Feed(at(10, 6 + 2 * i), None, None, "Nursing") for i in range(5)] + bottles(120, count=2)
    result = insights.intake_assessment(feeds, 4.0, 30)
    assert result.status == "unknown"
    assert result.nursing_feeds == 5
    assert "nursing" in result.reason.lower()


def test_intake_with_a_minority_of_nursing_is_still_assessed():
    feeds = [Feed(at(10, 4), None, None, "Nursing")] + bottles(700)
    assert insights.intake_assessment(feeds, 4.0, 30).status == "ok"


@pytest.mark.parametrize("weight, age_days, feeding_type", [
    (None, 30, None),        # no weight
    (0, 30, None),
    (4.0, 3, None),          # first week
    (7.0, 200, None),        # solids
    (4.0, 30, "breast"),
])
def test_intake_unknown_cases(weight, age_days, feeding_type):
    result = insights.intake_assessment(bottles(600), weight, age_days, feeding_type)
    assert result.status == "unknown"
    assert result.reason


def test_intake_with_no_feeds_is_unknown():
    result = insights.intake_assessment([], 4.0, 30)
    assert result.status == "unknown"
    assert result.actual_ml == 0


# ----- 4. diapers -----

@pytest.mark.parametrize("age_days, wet, status, expected_min", [
    (0, 0, "low", 1), (0, 1, "ok", 1),       # day 1
    (1, 1, "low", 2), (1, 2, "ok", 2),
    (2, 2, "low", 3), (2, 3, "ok", 3),
    (3, 3, "low", 4), (3, 4, "ok", 4),
    (4, 4, "low", 6), (4, 5, "ok", 6),       # day 5: expect 6, flag below 5
    (30, 4, "low", 6), (30, 6, "ok", 6),
])
def test_wet_diaper_thresholds_by_day_of_life(age_days, wet, status, expected_min):
    result = insights.diaper_adequacy(wet, 3, age_days)
    assert result.wet_status == status
    assert result.expected_min_wet == expected_min
    assert result.day_of_life == int(age_days) + 1


def test_stool_guidance_by_age():
    assert insights.diaper_adequacy(8, 1, 15).stool_status == "low"
    assert insights.diaper_adequacy(8, 3, 15).stool_status == "ok"
    assert insights.diaper_adequacy(8, 3, 15).expected_min_dirty == 3
    assert insights.diaper_adequacy(8, 1, 0).stool_status == "ok"   # day 1 expects one
    assert insights.diaper_adequacy(8, 0, 1).stool_status == "low"  # day 2 expects two
    older = insights.diaper_adequacy(8, 0, 60)
    assert older.stool_status == "ok" and older.expected_min_dirty == 0
    assert "infrequent" in older.note.lower()


def test_overall_diaper_status_and_unknowns():
    assert insights.diaper_adequacy(8, 4, 15).status == "ok"
    assert insights.diaper_adequacy(2, 4, 15).status == "low"
    assert insights.diaper_adequacy(8, 0, 15).status == "low"
    unknown = insights.diaper_adequacy(None, None, 15)
    assert unknown.status == unknown.wet_status == unknown.stool_status == "unknown"


# ----- 5. growth percentiles -----

def table(sex, kind):
    path = insights.DATA_DIR / f"who-{'boys' if sex == 'male' else 'girls'}-{kind}.csv"
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


@pytest.mark.parametrize("sex", ["male", "female"])
@pytest.mark.parametrize("kind", ["weight", "length", "head"])
def test_tabulated_percentile_columns_round_trip(sex, kind):
    rows = table(sex, kind)
    assert len(rows) == 25
    for row in (rows[0], rows[1], rows[6], rows[12], rows[24]):
        month = float(row["Month"])
        for column, percentile in (("2nd (2.3rd)", 2.275), ("5th", 5), ("25th", 25), ("50th", 50),
                                   ("75th", 75), ("95th", 95), ("98th (97.7th)", 97.725)):
            result = insights.growth_percentile(sex, month, float(row[column]), kind)
            assert result.percentile == pytest.approx(percentile, abs=0.15), (sex, kind, month, column)
        assert insights.growth_percentile(sex, month, float(row["50th"]), kind).z == pytest.approx(0, abs=1e-3)


def test_median_birth_weight_of_a_boy():
    result = insights.growth_percentile("male", 0, 3.3464, "weight")
    assert result.percentile == pytest.approx(50)
    assert result.z == pytest.approx(0, abs=1e-9)
    assert result.p50 == pytest.approx(3.3464)
    assert result.p3 < result.p50 < result.p97
    assert result.p3 == pytest.approx(2.507, abs=0.01)
    assert result.p97 == pytest.approx(4.35, abs=0.01)


def test_interpolates_between_months():
    boys = table("male", "weight")
    mid = (float(boys[1]["50th"]) + float(boys[2]["50th"])) / 2
    result = insights.growth_percentile("male", 1.5, mid, "weight")
    assert result.p50 == pytest.approx(mid, abs=0.01)
    assert result.percentile == pytest.approx(50, abs=0.5)
    assert result.age_months == 1.5


def test_a_four_kilo_boy_at_one_month_is_below_the_median():
    result = insights.growth_percentile("male", 1.0, 4.0, "weight")
    assert 10 < result.percentile < 30


def test_sex_flag_and_names():
    boy = insights.growth_percentile(True, 3, 6.0, "weight")
    girl = insights.growth_percentile(False, 3, 6.0, "weight")
    assert boy.percentile < girl.percentile  # boys run heavier, so 6 kg is lower on the boys' chart
    assert insights.growth_percentile("boy", 3, 6.0, "weight") == boy
    assert insights.growth_percentile("Female", 3, 6.0, "weight") == girl
    with pytest.raises(ValueError):
        insights.growth_percentile("other", 3, 6.0, "weight")


def test_z_is_clamped_to_five():
    huge = insights.growth_percentile("female", 2, 40.0, "weight")
    assert huge.z == 5
    assert huge.percentile > 99.99
    tiny = insights.growth_percentile("female", 2, 0.5, "weight")
    assert tiny.z == -5


def test_out_of_range_inputs():
    assert insights.growth_percentile("male", 25, 12.0, "weight") is None
    assert insights.growth_percentile("male", 3, 0, "weight") is None
    assert insights.growth_percentile("male", 3, None, "length") is None
    assert insights.growth_percentile("male", -1, 3.3, "weight").age_months == 0  # before the due date
    with pytest.raises(ValueError):
        insights.growth_percentile("male", 3, 6.0, "height")


def test_length_and_head_reference_values():
    length = insights.growth_percentile("male", 0, 49.8842, "length")
    assert length.percentile == pytest.approx(50)
    head = insights.growth_percentile("female", 24, 47.1822, "head")
    assert head.percentile == pytest.approx(50)
    assert head.p3 < 47.1822 < head.p97


# ----- 6. weight velocity -----

def weights(*points):
    base = datetime(2026, 5, 1, tzinfo=UTC)
    return [(base + timedelta(days=d), kg) for d, kg in points]


@pytest.mark.parametrize("gain_kg, status", [(0.14, "low"), (0.42, "ok"), (0.60, "high")])
def test_velocity_in_the_first_four_months(gain_kg, status):
    result = insights.weight_velocity(weights((0, 4.0), (14, 4.0 + gain_kg)), age_days=60)
    assert result.status == status
    assert result.grams_per_day == pytest.approx(gain_kg * 1000 / 14)
    assert (result.expected_min, result.expected_max) == (20, 35)
    assert result.span_days == 14


def test_velocity_bands_by_age():
    gain = weights((0, 6.0), (10, 6.15))  # 15 g/day
    assert insights.weight_velocity(gain, 100).status == "low"
    assert insights.weight_velocity(gain, 150).status == "ok"     # 4-6 months: 12-20
    assert insights.weight_velocity(gain, 250).status == "high"   # 6-12 months: 8-12
    assert insights.weight_velocity(gain, 250).expected_max == 12


def test_velocity_uses_a_measurement_at_least_five_days_before():
    result = insights.weight_velocity(weights((0, 4.0), (10, 4.3), (12, 4.35)), age_days=60)
    assert result.span_days == 12  # the 10 day point is only 2 days before the latest
    assert result.grams_per_day == pytest.approx(350 / 12)
    result = insights.weight_velocity(weights((0, 4.0), (5, 4.15), (11, 4.5)), age_days=60)
    assert result.span_days == 6   # most recent earlier weight that is 5+ days back


def test_velocity_unknown_cases():
    assert insights.weight_velocity([], 60).status == "unknown"
    assert insights.weight_velocity(weights((0, 4.0)), 60).status == "unknown"
    assert insights.weight_velocity(weights((0, 4.0), (3, 4.1)), 60).status == "unknown"
    young = insights.weight_velocity(weights((0, 3.2), (7, 3.5)), age_days=10)
    assert young.status == "unknown" and young.grams_per_day == pytest.approx(300 / 7)
    assert insights.weight_velocity(weights((0, 9.0), (30, 9.3)), age_days=500).status == "unknown"


def test_velocity_sorts_its_input():
    result = insights.weight_velocity(list(reversed(weights((0, 4.0), (14, 4.42)))), 60)
    assert result.status == "ok"


# ----- results as dicts -----

def test_to_dict_makes_json_friendly_dicts():
    last = at(10, 22)
    result = insights.predict_next_feed(feeds_at(last), last, age_days=8)
    as_dict = insights.to_dict(result)
    assert as_dict["predicted_at"] == (last + timedelta(hours=3.5)).isoformat()
    json.dumps(as_dict)


# ----- BabyTracker.get_insights -----

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def seed(app_db):
    ts = lambda **delta: (NOW - timedelta(**delta)).timestamp()  # noqa: E731
    conn = sqlite3.connect(app_db)
    # Everly: a boy, 30 days old, born on her due date
    conn.execute("UPDATE Baby SET DOB=?, DueDay=?, Gender=1 WHERE ID=?", (ts(days=30), ts(days=30), EVERLY))
    conn.execute("UPDATE Baby SET DOB=?, DueDay=?, Gender=0 WHERE ID=?", (ts(days=200), ts(days=200), TWIN))
    growth = "INSERT INTO Growth (ID, Time, BabyID, Weight, Length, Head, IsEnglishWeightScale, IsEnglishLengthScale) VALUES (?,?,?,?,?,?,?,?)"
    conn.execute(growth, ("G1", ts(days=20), EVERLY, 3.6, 0, 0, 0, 0))
    conn.execute(growth, ("G2", ts(days=2), EVERLY, 4.0, 21.5, 0, 0, 1))   # 21.5 in = 54.6 cm
    conn.execute(growth, ("G3", ts(days=1), TWIN, 14.0, 0, 0, 0, 0))
    for i in range(6):  # 110 ml every 3 hours, the latest an hour ago
        conn.execute("INSERT INTO Formula (ID, Time, BabyID, Amount, IsEnglishScale) VALUES (?,?,?,?,0)",
                     (f"F{i}", ts(hours=1 + 3 * i), EVERLY, 110))
    conn.execute("INSERT INTO Formula (ID, Time, BabyID, Amount, IsEnglishScale) VALUES ('F-old',?,?,300,0)",
                 (ts(hours=30), EVERLY))
    conn.execute("INSERT INTO Formula (ID, Time, BabyID, Amount, IsEnglishScale) VALUES ('F-twin',?,?,4,1)",
                 (ts(hours=2), TWIN))
    conn.execute("INSERT INTO OtherFeedSelection (ID, Name, IsBottle) VALUES ('OS1','Water',0)")
    conn.execute("INSERT INTO OtherFeed (ID, Time, BabyID, TypeID, Amount, IsEnglishScale) VALUES ('O1',?,?,'OS1',500,0)",
                 (ts(minutes=10), EVERLY))
    diaper = "INSERT INTO Diaper (ID, Time, BabyID, Status, Amount) VALUES (?,?,?,?,?)"
    for i in range(7):
        conn.execute(diaper, (f"W{i}", ts(hours=1 + i), EVERLY, 0, 2))
    for i in range(3):
        conn.execute(diaper, (f"P{i}", ts(hours=2 + i), EVERLY, 1, 2))
    conn.execute(diaper, ("M", ts(hours=3), EVERLY, 2, 2))
    conn.execute(diaper, ("D", ts(hours=4), EVERLY, 0, 0))        # dry
    conn.execute(diaper, ("OLD", ts(hours=30), EVERLY, 0, 2))
    conn.execute(diaper, ("TW", ts(hours=1), TWIN, 0, 2))
    conn.commit()
    conn.close()


def test_get_insights_for_one_baby(tracker, app_db):
    seed(app_db)
    result = tracker.get_insights(EVERLY, now=NOW)
    json.dumps(result)

    assert result["baby_id"] == EVERLY and result["name"] == "Everly"
    assert result["age"]["chronological_days"] == 30
    assert result["age"]["correction_applied"] is False

    feed = result["next_feed"]
    assert feed["basis"] == "history" and feed["sample_count"] == 5
    assert feed["interval_hours"] == 3.0
    last = (NOW - timedelta(hours=1)).astimezone(ZoneInfo("America/Chicago"))
    assert datetime.fromisoformat(feed["last_feed_at"]) == last
    assert datetime.fromisoformat(feed["predicted_at"]) == last + timedelta(hours=3)
    assert feed["max_gap_hours"] == 5.0  # 30 days old, past the 3.6 kg first weight, under 5.4 kg

    intake = result["intake"]
    assert intake["actual_ml"] == pytest.approx(660)          # 6 x 110; not the 30 h old one, not the water, not the twin
    assert (intake["expected_min_ml"], intake["expected_max_ml"]) == (600, 800)
    assert intake["status"] == "ok"

    diapers = result["diapers"]
    assert diapers["wet_count"] == 7 + 1                       # 7 wet + 1 mixed; dry and 30 h old excluded
    assert diapers["dirty_count"] == 3 + 1
    assert diapers["status"] == "ok"
    assert diapers["day_of_life"] == 31

    growth = result["growth"]
    assert set(growth) == {"weight", "length"}                 # no head measurement
    assert growth["weight"]["value"] == 4.0
    assert 10 < growth["weight"]["percentile"] < 40            # boy, 28 days
    assert growth["length"]["value"] == pytest.approx(54.61)   # inches converted
    assert growth["weight"]["measured_at"].startswith("2026-10-28")

    velocity = result["weight_velocity"]
    assert velocity["grams_per_day"] == pytest.approx(400 / 18)
    assert velocity["status"] == "ok"


def test_get_insights_keeps_babies_apart(tracker, app_db):
    seed(app_db)
    twin = tracker.get_insights(TWIN, now=NOW)
    assert twin["name"] == "Ann Marie"
    assert twin["age"]["chronological_days"] == 200
    assert twin["intake"]["actual_ml"] == pytest.approx(4 * 29.5735, abs=0.05)   # 4 oz in ml, total kept to 0.1 ml
    assert twin["growth"]["weight"]["value"] == 14.0
    assert twin["diapers"]["wet_count"] == 1
    assert twin["weight_velocity"]["status"] == "unknown"
    assert twin["next_feed"]["max_gap_hours"] is None


def test_get_insights_without_data_or_babies(tracker, app_db):
    empty = tracker.get_insights(EVERLY, now=NOW)  # nothing logged yet
    assert empty["next_feed"]["predicted_at"] is None
    assert empty["intake"]["status"] == "unknown"
    assert empty["growth"] is None
    assert empty["weight_velocity"] is None
    assert tracker.get_insights("NO-SUCH-BABY", now=NOW) == {}


def test_get_insights_opens_the_database_in_the_trackers_zone(tracker):
    tracker.db = None  # not opened yet, as after a restart before the first sync
    tracker.get_insights(EVERLY, now=NOW)
    assert tracker.db.tz == tracker.tz == CHICAGO

def test_unknown_age_is_unknown_not_a_newborn():
    assert insights.feed_gap_guidance(None) is None
    assert insights.default_interval_hours(None) == 3.0
    no_age = insights.intake_assessment([Feed(NOW, None, 120, "Formula")], 4.0, None)
    assert no_age.status == "unknown" and "date of birth" in no_age.reason
    diapers = insights.diaper_adequacy(0, 0, None)
    assert (diapers.status, diapers.wet_status, diapers.stool_status) == ("unknown", "unknown", "unknown")
    assert (diapers.wet_count, diapers.dirty_count) == (0, 0)


def test_get_insights_for_a_baby_without_a_date_of_birth(tracker, app_db):
    conn = sqlite3.connect(app_db)
    conn.execute("UPDATE Baby SET DOB = 0 WHERE ID = ?", (EVERLY,))
    conn.commit()
    conn.close()

    result = tracker.get_insights(EVERLY, now=NOW)

    assert result["age"] is None
    assert result["diapers"] is None
    assert result["next_feed"]["max_gap_hours"] is None  # not "4.5 hours, as for a newborn"
    assert result["intake"]["status"] == "unknown"
