"""Trend / momentum / volume / volatility indicators for the most recent bar
of a per-instrument OHLCV history. TA-Lib covers most of these directly;
Supertrend, Ichimoku, rolling VWAP and Keltner Channels aren't TA-Lib
primitives so they're composed here from TA-Lib's EMA/ATR building blocks.
"""

import numpy as np
import pandas as pd
import talib

# Ichimoku's standard periods (Tenkan/Kijun/Senkou B). Classic charting plots
# senkou_a/senkou_b 26 periods *ahead* of trade_date and chikou 26 periods
# *behind* — we store the values as computed as-of trade_date (chikou is
# simply that day's close) and leave any forward/back shifting to query time.
_ICHIMOKU_TENKAN = 9
_ICHIMOKU_KIJUN = 26
_ICHIMOKU_SENKOU_B = 52

_SUPERTREND_PERIOD = 7
_SUPERTREND_MULTIPLIER = 3

_KELTNER_EMA_PERIOD = 20
_KELTNER_ATR_PERIOD = 14
_KELTNER_MULTIPLIER = 2

_ROC_PERIOD = 12
_VWAP_PERIOD = 20


def _last(arr) -> float | None:
    val = arr[-1] if len(arr) else np.nan
    return None if pd.isna(val) else float(val)


def _last_int(arr) -> int | None:
    val = _last(arr)
    return None if val is None else int(round(val))


def _donchian_mid(high: np.ndarray, low: np.ndarray, period: int) -> np.ndarray:
    highs = pd.Series(high).rolling(period).max()
    lows = pd.Series(low).rolling(period).min()
    return ((highs + lows) / 2).to_numpy()


def _supertrend(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int, multiplier: float):
    atr = talib.ATR(high, low, close, timeperiod=period)
    hl2 = (high + low) / 2
    upperband = hl2 + multiplier * atr
    lowerband = hl2 - multiplier * atr

    n = len(close)
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    trend = np.full(n, np.nan)
    direction = np.full(n, np.nan)  # 1 = up, -1 = down

    for i in range(n):
        if np.isnan(atr[i]):
            continue
        if np.isnan(final_upper[i - 1]) if i > 0 else True:
            final_upper[i] = upperband[i]
            final_lower[i] = lowerband[i]
            direction[i] = 1
            trend[i] = final_lower[i]
            continue

        final_upper[i] = (
            upperband[i] if upperband[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1] else final_upper[i - 1]
        )
        final_lower[i] = (
            lowerband[i] if lowerband[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1] else final_lower[i - 1]
        )

        if close[i] > final_upper[i - 1]:
            direction[i] = 1
        elif close[i] < final_lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]

        trend[i] = final_lower[i] if direction[i] == 1 else final_upper[i]

    return trend, direction


def _rolling_vwap(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray, period: int) -> np.ndarray:
    """Daily bars only (no intraday ticks), so this is a rolling N-day
    volume-weighted typical price, not a true intraday session VWAP."""
    typical = (high + low + close) / 3
    tp_vol = pd.Series(typical * volume)
    vol = pd.Series(volume)
    return (tp_vol.rolling(period).sum() / vol.rolling(period).sum()).to_numpy()


def compute_indicators(df: pd.DataFrame) -> dict:
    """df: chronological OHLCV, indexed by trade_date, columns open/high/low/close/volume.
    Returns indicator values for the last row. Indicators without enough lookback
    history yet are None (NULL) rather than omitted."""
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    v = df["volume"].to_numpy(dtype=float)

    macd, macd_signal, macd_hist = talib.MACD(c, fastperiod=12, slowperiod=26, signalperiod=9)
    stoch_k, stoch_d = talib.STOCH(
        h, l, c, fastk_period=14, slowk_period=3, slowk_matype=0, slowd_period=3, slowd_matype=0
    )
    bb_upper, bb_mid, bb_lower = talib.BBANDS(c, timeperiod=20, nbdevup=2, nbdevdn=2)

    supertrend, st_direction = _supertrend(h, l, c, _SUPERTREND_PERIOD, _SUPERTREND_MULTIPLIER)
    tenkan = _donchian_mid(h, l, _ICHIMOKU_TENKAN)
    kijun = _donchian_mid(h, l, _ICHIMOKU_KIJUN)
    senkou_a = (tenkan + kijun) / 2
    senkou_b = _donchian_mid(h, l, _ICHIMOKU_SENKOU_B)

    keltner_mid = talib.EMA(c, _KELTNER_EMA_PERIOD)
    keltner_atr = talib.ATR(h, l, c, _KELTNER_ATR_PERIOD)
    keltner_upper = keltner_mid + _KELTNER_MULTIPLIER * keltner_atr
    keltner_lower = keltner_mid - _KELTNER_MULTIPLIER * keltner_atr

    st_dir_val = _last(st_direction)
    st_dir = None if st_dir_val is None else ("UP" if st_dir_val > 0 else "DOWN")

    return {
        # Trend
        "ema_9": _last(talib.EMA(c, 9)),
        "ema_21": _last(talib.EMA(c, 21)),
        "ema_50": _last(talib.EMA(c, 50)),
        "ema_100": _last(talib.EMA(c, 100)),
        "ema_200": _last(talib.EMA(c, 200)),
        "sma_20": _last(talib.SMA(c, 20)),
        "sma_50": _last(talib.SMA(c, 50)),
        "sma_200": _last(talib.SMA(c, 200)),
        "adx_14": _last(talib.ADX(h, l, c, 14)),
        "supertrend_7_3": _last(supertrend),
        "supertrend_direction": st_dir,
        "ichimoku_tenkan": _last(tenkan),
        "ichimoku_kijun": _last(kijun),
        "ichimoku_senkou_a": _last(senkou_a),
        "ichimoku_senkou_b": _last(senkou_b),
        "ichimoku_chikou": _last(c),
        # Momentum
        "rsi_14": _last(talib.RSI(c, 14)),
        "macd": _last(macd),
        "macd_signal": _last(macd_signal),
        "macd_hist": _last(macd_hist),
        "stoch_k": _last(stoch_k),
        "stoch_d": _last(stoch_d),
        "roc_12": _last(talib.ROC(c, _ROC_PERIOD)),
        "cci_14": _last(talib.CCI(h, l, c, 14)),
        # Volume
        "obv": _last_int(talib.OBV(c, v)),
        "vwap_20": _last(_rolling_vwap(h, l, c, v, _VWAP_PERIOD)),
        "volume_sma_20": _last_int(talib.SMA(v, 20)),
        "mfi_14": _last(talib.MFI(h, l, c, v, 14)),
        # Volatility
        "bb_upper": _last(bb_upper),
        "bb_mid": _last(bb_mid),
        "bb_lower": _last(bb_lower),
        "atr_14": _last(talib.ATR(h, l, c, 14)),
        "keltner_upper": _last(keltner_upper),
        "keltner_mid": _last(keltner_mid),
        "keltner_lower": _last(keltner_lower),
    }
