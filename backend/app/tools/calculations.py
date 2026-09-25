from decimal import Decimal
from datetime import date

from app.schemas import Evidence


def calculate(operation: str, inputs: list[Evidence]) -> tuple[str, str]:
    if len(inputs) != 2 or any(x.value is None for x in inputs):
        raise ValueError("Exactly two numeric evidence records are required")
    a, b = inputs
    if a.ticker != b.ticker or a.unit != b.unit:
        raise ValueError("Inputs must have the same company and unit")
    if a.period_type or b.period_type:
        if a.period_type != "annual" or b.period_type != "annual":
            raise ValueError("V1 calculations accept annual periods only, never quarterly or YTD")
        if not all((a.period_start, a.period_end, b.period_start, b.period_end)):
            raise ValueError("Fiscal dates are required")
        durations = [(date.fromisoformat(e.period_end) - date.fromisoformat(e.period_start)).days + 1 for e in (a, b)]
        if any(not 350 <= d <= 380 for d in durations):
            raise ValueError("Inputs must cover whole annual periods")
        if operation == "operating_margin" and (a.period_start, a.period_end) != (b.period_start, b.period_end):
            raise ValueError("Margin inputs must have identical fiscal dates")
        if operation in ("growth", "margin_change") and not 350 <= (date.fromisoformat(a.period_end) - date.fromisoformat(b.period_end)).days <= 380:
            raise ValueError("Annual comparisons require adjacent fiscal years")
    x, y = Decimal(a.value), Decimal(b.value)
    if not x.is_finite() or not y.is_finite():
        raise ValueError("Inputs must be finite")
    if operation == "operating_margin":
        if (a.metric, b.metric) != ("operating_income", "revenue") or a.period != b.period:
            raise ValueError("Margin requires operating income and revenue for the same period")
        if y <= 0:
            raise ValueError("Revenue must be positive")
        value, unit = x / y * 100, "percent"
    elif operation == "growth":
        if a.metric != b.metric or not a.period or not b.period or a.period <= b.period:
            raise ValueError("Growth requires the same metric, newest annual period first")
        if y <= 0:
            raise ValueError("Growth is undefined here for a nonpositive base")
        value, unit = (x - y) / y * 100, "percent"
    elif operation == "margin_change":
        if a.metric != "operating_margin" or b.metric != "operating_margin" or a.unit != "percent":
            raise ValueError("Margin change requires two calculated operating margins")
        if not a.period or not b.period or a.period <= b.period:
            raise ValueError("Use the newest annual margin first")
        value, unit = x - y, "percentage_points"
    else:
        raise ValueError("Unsupported operation")
    return str(value.quantize(Decimal("0.0001"))), unit
