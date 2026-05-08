import math
from typing import Any, Dict, List, Optional, Sequence


def ema(previous: Optional[float], value: float, period: int) -> float:
    alpha = 2 / (period + 1)
    return value if previous is None else value * alpha + previous * (1 - alpha)


def calculate_ma(values: List[float], window: int) -> List[Optional[float]]:
    if len(values) < window:
        return [None] * len(values)

    result = []
    window_sum = sum(values[:window])
    result.append(window_sum / window)

    for i in range(window, len(values)):
        window_sum += values[i] - values[i - window]
        result.append(window_sum / window)

    return [None] * (window - 1) + result


def rsi(values: List[float], period: int) -> Optional[float]:
    if len(values) <= period:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    recent_gains = gains[-period:]
    recent_losses = losses[-period:]
    avg_gain = sum(recent_gains) / period
    avg_loss = sum(recent_losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def calculate_technical_indicators(
    daily_rows: Sequence[Sequence[Any]],
    created_at: str,
) -> List[Dict[str, Any]]:
    closes = [float(r[1]) for r in daily_rows]
    highs = [float(r[2]) for r in daily_rows]
    lows = [float(r[3]) for r in daily_rows]
    volumes = [float(r[4] or 0) for r in daily_rows]
    dates = [r[0] for r in daily_rows]

    first_close = closes[0] if closes else None
    last_close = closes[-1] if closes else None
    year_change = (last_close - first_close) / first_close * 100 if first_close and last_close else None

    ma5_list = calculate_ma(closes, 5)
    ma10_list = calculate_ma(closes, 10)
    ma20_list = calculate_ma(closes, 20)
    ma60_list = calculate_ma(closes, 60)

    ema12 = None
    ema26 = None
    dea = None
    kdj_k = 50.0
    kdj_d = 50.0
    obv = 0.0
    result = []

    for i, date in enumerate(dates):
        close = closes[i]
        high = highs[i]
        low = lows[i]

        window_start_52w = max(0, i - 249)
        high_52w = max(highs[window_start_52w:i + 1])
        low_52w = min(lows[window_start_52w:i + 1])
        position = (close - low_52w) / (high_52w - low_52w) * 100 if high_52w and low_52w and high_52w != low_52w else None

        ema12 = ema(ema12, close, 12)
        ema26 = ema(ema26, close, 26)
        dif = ema12 - ema26 if ema12 is not None and ema26 is not None else None
        dea = ema(dea, dif, 9) if dif is not None else None
        macd_hist = (dif - dea) * 2 if dif is not None and dea is not None else None

        rsi_6 = rsi(closes[:i + 1], 6)
        rsi_12 = rsi(closes[:i + 1], 12)
        rsi_24 = rsi(closes[:i + 1], 24)

        kdj_start = max(0, i - 8)
        period_high = max(highs[kdj_start:i + 1])
        period_low = min(lows[kdj_start:i + 1])
        rsv = (close - period_low) / (period_high - period_low) * 100 if period_high != period_low else 50
        kdj_k = kdj_k * 2 / 3 + rsv / 3
        kdj_d = kdj_d * 2 / 3 + kdj_k / 3
        kdj_j = 3 * kdj_k - 2 * kdj_d

        boll_mid = ma20_list[i]
        if i >= 19:
            boll_window = closes[i - 19:i + 1]
            variance = sum((x - boll_mid) ** 2 for x in boll_window) / 20
            boll_std = math.sqrt(variance)
            boll_upper = boll_mid + 2 * boll_std
            boll_lower = boll_mid - 2 * boll_std
        else:
            boll_upper = boll_lower = None

        tr_values = []
        atr_start = max(0, i - 13)
        for j in range(atr_start, i + 1):
            prev_close = closes[j - 1] if j > 0 else closes[j]
            tr_values.append(max(highs[j] - lows[j], abs(highs[j] - prev_close), abs(lows[j] - prev_close)))
        atr = sum(tr_values) / len(tr_values) if len(tr_values) >= 14 else None

        if i > 0:
            if close > closes[i - 1]:
                obv += volumes[i]
            elif close < closes[i - 1]:
                obv -= volumes[i]

        result.append({
            'data_date': date,
            'ma5': ma5_list[i],
            'ma10': ma10_list[i],
            'ma20': ma20_list[i],
            'ma60': ma60_list[i],
            'ema12': ema12,
            'ema26': ema26,
            'macd': dif,
            'macd_signal': dea,
            'macd_hist': macd_hist,
            'rsi_6': rsi_6,
            'rsi_12': rsi_12,
            'rsi_24': rsi_24,
            'kdj_k': kdj_k,
            'kdj_d': kdj_d,
            'kdj_j': kdj_j,
            'boll_upper': boll_upper,
            'boll_mid': boll_mid,
            'boll_lower': boll_lower,
            'atr': atr,
            'obv': obv,
            'high_52w': high_52w,
            'low_52w': low_52w,
            'position_pct': position,
            'year_change_pct': year_change,
            'created_at': created_at,
        })

    return result
