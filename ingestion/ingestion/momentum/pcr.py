"""Put-Call Ratio and max-pain computation for one underlying's option chain
on a single expiry. Pure functions over already-fetched fno_bhavcopy_daily
rows — the calling job (jobs/fno_signals.py) owns querying the DB and
persisting the output (same separation as brokerage/consensus.py)."""


def compute_pcr(option_rows: list[dict]) -> tuple[float | None, float | None]:
    """option_rows: contract_type='OPT' rows for one (underlying, expiry).
    Returns (pcr_oi, pcr_volume) = put/call ratios of total OI and total
    volume. None for either side whose denominator (call OI/volume) is zero
    or absent — a PCR is undefined, not infinite, when there's no call-side
    activity to divide by."""
    call_oi = sum(r["open_interest"] or 0 for r in option_rows if r["option_type"] == "CE")
    put_oi = sum(r["open_interest"] or 0 for r in option_rows if r["option_type"] == "PE")
    call_vol = sum(r["volume"] or 0 for r in option_rows if r["option_type"] == "CE")
    put_vol = sum(r["volume"] or 0 for r in option_rows if r["option_type"] == "PE")

    pcr_oi = put_oi / call_oi if call_oi else None
    pcr_volume = put_vol / call_vol if call_vol else None
    return pcr_oi, pcr_volume


def compute_max_pain(option_rows: list[dict]) -> float | None:
    """The strike at which option writers' aggregate payout to buyers (across
    every strike in this chain, at settlement) is smallest — the classic
    "max pain" strike. None if the chain has no strikes with any OI at all
    (nothing to compute pain over)."""
    strikes = sorted({r["strike_price"] for r in option_rows if r["strike_price"] is not None})
    if not strikes:
        return None

    calls = [(r["strike_price"], r["open_interest"] or 0) for r in option_rows if r["option_type"] == "CE"]
    puts = [(r["strike_price"], r["open_interest"] or 0) for r in option_rows if r["option_type"] == "PE"]

    if not any(oi for _, oi in calls) and not any(oi for _, oi in puts):
        return None

    best_strike, best_pain = None, None
    for settle in strikes:
        pain = sum(max(settle - k, 0) * oi for k, oi in calls) + sum(max(k - settle, 0) * oi for k, oi in puts)
        if best_pain is None or pain < best_pain:
            best_strike, best_pain = settle, pain
    return best_strike
