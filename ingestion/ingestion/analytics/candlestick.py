"""Candlestick pattern detection via TA-Lib's CDL* functions. Each returns an
array of -200..200 signals (0 = pattern not present, sign = bearish/bullish,
magnitude = TA-Lib's own confidence weighting) — we keep the raw signed value
for the most recent bar."""

import numpy as np
import pandas as pd
import talib

_PATTERN_FUNCS = {
    "cdl_doji": talib.CDLDOJI,
    "cdl_engulfing": talib.CDLENGULFING,
    "cdl_hammer": talib.CDLHAMMER,
    "cdl_shooting_star": talib.CDLSHOOTINGSTAR,
    "cdl_morning_star": talib.CDLMORNINGSTAR,
    "cdl_evening_star": talib.CDLEVENINGSTAR,
    "cdl_harami": talib.CDLHARAMI,
    "cdl_three_white_soldiers": talib.CDL3WHITESOLDIERS,
    "cdl_three_black_crows": talib.CDL3BLACKCROWS,
}


def compute_candlestick_patterns(df: pd.DataFrame) -> dict:
    """df: chronological OHLC, indexed by trade_date. Returns the signed
    pattern value for each of the 9 patterns on the last bar."""
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)

    out = {}
    for column, func in _PATTERN_FUNCS.items():
        values = func(o, h, l, c)
        last = values[-1] if len(values) else np.nan
        out[column] = None if pd.isna(last) else int(last)
    return out
