"""Futures rollover % — how much of an underlying's total near+next-month
open interest already sits in the next-month contract. Pure function, no
I/O."""


def compute_rollover_pct(near_oi: int, next_oi: int | None) -> float | None:
    """None when there's no next-month contract open yet (next_oi is None)
    or both contracts are somehow empty — not assumed zero, since a missing
    next-month contract isn't "0% rolled", it's "not yet meaningful"."""
    if next_oi is None:
        return None
    total = near_oi + next_oi
    if total == 0:
        return None
    return next_oi / total * 100
