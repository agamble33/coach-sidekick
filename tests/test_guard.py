"""Gate 13a: rate limits, daily token budget, kill switch."""
import pytest

from coach.guard import Guard, GuardError, Limits


class Clock:
    def __init__(self, t=1_700_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def guard(tmp_path, **lim):
    clk = Clock()
    g = Guard(tmp_path / "budget.json", Limits(**lim), clock=clk)
    return g, clk


def test_turns_per_minute_bucket(tmp_path):
    g, clk = guard(tmp_path, turns_per_min=3)
    for _ in range(3):
        g.check("turns", "a")
    with pytest.raises(GuardError) as e:
        g.check("turns", "a")
    assert e.value.status == 429 and "breather" in e.value.message
    g.check("turns", "b")                      # another subject is unaffected
    clk.t += 61
    g.check("turns", "a")                      # window rolled


def test_daily_budget_global_and_per_subject(tmp_path):
    g, clk = guard(tmp_path, daily_tokens=1000, daily_tokens_per_subject=400)
    g.record_usage("a", 400)
    with pytest.raises(GuardError, match="this session"):
        g.check("turns", "a")
    g.check("turns", "b")
    g.record_usage("b", 600)
    with pytest.raises(GuardError, match="today's model budget"):
        g.check("turns", "c")
    assert g.status()["tokens_used"] == 1000 and g.status()["refused_today"] == 2
    clk.t += 86_400                            # next UTC day
    g.check("turns", "a")
    assert g.status()["tokens_used"] == 0


def test_budget_survives_restart(tmp_path):
    g, clk = guard(tmp_path, daily_tokens=1000)
    g.record_usage("a", 999)
    g2 = Guard(tmp_path / "budget.json", Limits(daily_tokens=1000), clock=clk)
    assert g2.status()["tokens_used"] == 999


def test_kill_switch(tmp_path):
    g, _ = guard(tmp_path)
    g.disabled = True
    with pytest.raises(GuardError) as e:
        g.check("frames", "a")
    assert e.value.status == 503


def test_limits_from_env():
    lim = Limits.from_env({"COACH_TURNS_PER_MIN": "5", "COACH_DAILY_TOKENS": "oops"})
    assert lim.turns_per_min == 5 and lim.daily_tokens == 1_000_000
