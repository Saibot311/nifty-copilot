"""Contract-selection invariants: the option chosen on a given day must be
one that (a) actually had recorded open interest above the liquidity
floor that day -- an untraded strike still carries a settlement price
that could not have been transacted at -- and (b) has an expiry that
outlasts the planned exit, so the position can't silently expire
mid-trade."""

import sqlite3

import pytest

from backtest.options_engine import select_contract
from storage.options_db import SCHEMA


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    rows = [
        # (trade_date, expiry_date, strike, option_type, open_interest)
        ("2024-01-02", "2024-01-25", 100.0, "CE", 5000),   # too soon: 23 days
        ("2024-01-02", "2024-02-15", 100.0, "CE", 5000),   # ok: 44 days, but illiquid strike below
        ("2024-01-02", "2024-02-15", 105.0, "CE", 50),     # below liquidity floor
        ("2024-01-02", "2024-02-15", 110.0, "CE", 8000),   # liquid, further from spot
        ("2024-01-02", "2024-03-15", 100.0, "CE", 9000),   # further expiry, liquid
    ]
    for trade_date, expiry, strike, opt_type, oi in rows:
        c.execute(
            """INSERT INTO option_bars (trade_date, expiry_date, strike, option_type,
               open, high, low, close, settle_price, contracts, open_interest, change_in_oi)
               VALUES (?,?,?,?,10,10,10,10,10,100,?,0)""",
            (trade_date, expiry, strike, opt_type, oi),
        )
    c.commit()
    return c


def test_rejects_expiry_that_does_not_outlast_the_exit(conn):
    # The Jan 25 expiry does not survive past a Jan 26 exit -- it must be
    # skipped in favor of the next real expiry on file (Feb 15).
    picked = select_contract(
        "2024-01-02", spot=100.0, option_type="CE", strike_offset_pts=0,
        min_days_to_expiry=1, must_survive_until="2024-01-26",
        min_open_interest=1000, conn=conn,
    )
    assert picked is not None
    strike, expiry = picked
    assert expiry != "2024-01-25"


def test_rejects_strikes_below_liquidity_floor(conn):
    # Nearest strike to 100 at the Feb expiry is the illiquid 105 (OI=50);
    # it must be skipped in favor of a real, liquid strike.
    picked = select_contract(
        "2024-01-02", spot=103.0, option_type="CE", strike_offset_pts=0,
        min_days_to_expiry=30, must_survive_until="2024-02-01",
        min_open_interest=1000, conn=conn,
    )
    assert picked is not None
    strike, expiry = picked
    assert strike != 105.0


def test_returns_none_when_no_contract_satisfies_constraints(conn):
    picked = select_contract(
        "2024-01-02", spot=100.0, option_type="CE", strike_offset_pts=0,
        min_days_to_expiry=200, must_survive_until="2024-06-01",  # nothing this far out
        min_open_interest=1000, conn=conn,
    )
    assert picked is None


def test_prefers_nearest_valid_expiry_over_further_one(conn):
    picked = select_contract(
        "2024-01-02", spot=100.0, option_type="CE", strike_offset_pts=0,
        min_days_to_expiry=30, must_survive_until="2024-02-01",
        min_open_interest=1000, conn=conn,
    )
    assert picked is not None
    strike, expiry = picked
    assert expiry == "2024-02-15"  # not the later March expiry
