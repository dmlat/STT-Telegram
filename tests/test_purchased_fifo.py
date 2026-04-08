"""FIFO allocation for purchased seconds."""
import pytest

from src.services.purchased_fifo import fifo_allocate


def test_empty_amount():
    assert fifo_allocate([(1, 100.0), (2, 50.0)], 0) == []


def test_single_bucket():
    assert fifo_allocate([(1, 100.0)], 30) == [(1, 30.0)]


def test_spans_two_buckets():
    assert fifo_allocate([(1, 100.0), (2, 50.0)], 120) == [(1, 100.0), (2, 20.0)]


def test_skips_zero_remaining():
    assert fifo_allocate([(1, 0.0), (2, 50.0)], 10) == [(2, 10.0)]


def test_exhaust_first_only():
    assert fifo_allocate([(1, 40.0), (2, 60.0)], 40) == [(1, 40.0)]
