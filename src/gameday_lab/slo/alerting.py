"""Part E — Multi-window, multi-burn-rate alerting (Google SRE Workbook, ch. 5).

Input: per-minute ``total`` and ``bad`` request counts for a 30-day window.

burn_rate(window) = error_ratio(window) / (1 - SLO)

A rule fires at minute i when BOTH its long and its short window (ending at i,
inclusive) burn at least ``burn_rate``. The long window says "this is
significant"; the short window says "it is still happening" (so the alert
resets quickly after recovery).

Tests: tests/test_alerting.py, then `make slo`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlertRule:
    name: str
    severity: str
    long_min: int
    short_min: int
    burn_rate: float


DEFAULT_RULES: tuple[AlertRule, ...] = (
    AlertRule("fast_burn_2pct_1h", "page", 60, 5, 14.4),
    AlertRule("slow_burn_5pct_6h", "page", 360, 30, 6.0),
    AlertRule("budget_leak_10pct_3d", "ticket", 4320, 360, 1.0),
)


@dataclass(frozen=True)
class AlertEvent:
    rule: str
    severity: str
    start_min: int
    end_min: int


class WindowSums:
    """O(1) sum of any window, via prefix sums."""

    def __init__(self, values: list[int]) -> None:
        # prefix[0] = 0; prefix[i+1] = prefix[i] + values[i]
        self.prefix: list[int] = [0] * (len(values) + 1)
        for i, v in enumerate(values):
            self.prefix[i + 1] = self.prefix[i] + v

    def sum(self, end_inclusive: int, length: int) -> int:
        # Window is [end_inclusive - length + 1, end_inclusive], clipped at 0.
        if length <= 0 or end_inclusive < 0:
            return 0
        end_inclusive = min(end_inclusive, len(self.prefix) - 2)
        start = max(0, end_inclusive - length + 1)
        # prefix[i] = sum of values[0..i-1]; so sum(l..r) = prefix[r+1] - prefix[l]
        return self.prefix[end_inclusive + 1] - self.prefix[start]


class BurnRateAlerter:
    def __init__(self, slo: float = 0.995, rules: tuple[AlertRule, ...] = DEFAULT_RULES) -> None:
        if not 0 < slo < 1:
            raise ValueError("slo must be in (0, 1)")
        self.slo = slo
        self.rules = rules

    def burn_rate(self, total: WindowSums, bad: WindowSums, end: int, length: int) -> float:
        t = total.sum(end, length)
        if t == 0:
            return 0.0
        b = bad.sum(end, length)
        error_ratio = b / t
        return error_ratio / (1.0 - self.slo)

    def evaluate(self, total: list[int], bad: list[int]) -> list[AlertEvent]:
        n = len(total)
        total_sums = WindowSums(total)
        bad_sums = WindowSums(bad)

        events: list[AlertEvent] = []
        for rule in self.rules:
            firing = False
            start = 0
            for i in range(n):
                long_br = self.burn_rate(total_sums, bad_sums, i, rule.long_min)
                short_br = self.burn_rate(total_sums, bad_sums, i, rule.short_min)
                is_firing = long_br >= rule.burn_rate and short_br >= rule.burn_rate

                if is_firing and not firing:
                    firing = True
                    start = i
                elif not is_firing and firing:
                    firing = False
                    events.append(AlertEvent(rule.name, rule.severity, start, i))

            if firing:
                events.append(AlertEvent(rule.name, rule.severity, start, n))

        events.sort(key=lambda e: e.start_min)
        return events


def error_budget_report(total: list[int], bad: list[int], slo: float = 0.995) -> dict[str, float | bool]:
    requests = sum(total)
    bad_sum = sum(bad)
    allowed_bad = (1.0 - slo) * requests
    availability = 1.0 - (bad_sum / requests) if requests > 0 else 1.0
    budget_consumed = bad_sum / allowed_bad if allowed_bad > 0 else 0.0
    budget_remaining = 1.0 - budget_consumed

    return {
        "requests": requests,
        "allowed_bad": round(allowed_bad, 1),
        "bad": bad_sum,
        "availability": round(availability, 6),
        "budget_consumed": round(budget_consumed, 4),
        "budget_remaining": round(budget_remaining, 4),
        "freeze_releases": budget_remaining <= 0.0,
    }