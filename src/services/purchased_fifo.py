"""FIFO allocation of usage against purchased-second buckets (transaction rows)."""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


def fifo_allocate(
    ordered_buckets: list[tuple[T, float]],
    amount: float,
) -> list[tuple[T, float]]:
    """
    Given buckets (id, seconds_remaining) oldest-first, return how much to take from each.

    ``amount`` is total seconds to consume from purchased balance. Each tuple in the result
    is (bucket_id, delta_to_subtract_from_remaining).
    """
    if amount <= 0:
        return []
    left = amount
    out: list[tuple[T, float]] = []
    for bid, rem in ordered_buckets:
        if left <= 0:
            break
        if rem <= 0:
            continue
        take = min(rem, left)
        out.append((bid, take))
        left -= take
    return out
