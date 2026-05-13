import math
from typing import Any, Dict, List, Optional, Sequence, Tuple


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


def calculate_returns(closes: List[float]) -> Dict[str, Any]:
    if len(closes) < 2:
        return {}
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    total_return = (closes[-1] - closes[0]) / closes[0] * 100
    avg_daily = sum(returns) / len(returns) * 100
    variance = sum((r - sum(returns) / len(returns)) ** 2 for r in returns) / len(returns)
    daily_vol = math.sqrt(variance) * 100
    annual_vol = daily_vol * math.sqrt(252)
    neg_returns = [r for r in returns if r < 0]
    downside_vol = math.sqrt(sum(r ** 2 for r in neg_returns) / len(neg_returns)) * 100 if neg_returns else 0
    annual_downside_vol = downside_vol * math.sqrt(252)
    risk_free = 0.015
    annual_return = avg_daily * 252 / 100
    sharpe = (annual_return - risk_free) / (annual_vol / 100) if annual_vol > 0 else 0
    sortino = (annual_return - risk_free) / (annual_downside_vol / 100) if annual_downside_vol > 0 else 0
    max_drawdown = 0.0
    peak = closes[0]
    for c in closes:
        if c > peak:
            peak = c
        dd = (peak - c) / peak
        if dd > max_drawdown:
            max_drawdown = dd
    calmar = annual_return / max_drawdown if max_drawdown > 0 else 0
    win_days = sum(1 for r in returns if r > 0)
    win_rate = win_days / len(returns) * 100 if returns else 0
    avg_win = sum(r for r in returns if r > 0) / win_days * 100 if win_days > 0 else 0
    avg_loss = sum(r for r in returns if r < 0) / (len(returns) - win_days) * 100 if win_days < len(returns) else 0
    profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
    return {
        'total_return_pct': round(total_return, 2),
        'annual_return_pct': round(annual_return * 100, 2),
        'daily_volatility_pct': round(daily_vol, 4),
        'annual_volatility_pct': round(annual_vol, 2),
        'sharpe_ratio': round(sharpe, 3),
        'sortino_ratio': round(sortino, 3),
        'calmar_ratio': round(calmar, 3),
        'max_drawdown_pct': round(max_drawdown * 100, 2),
        'win_rate_pct': round(win_rate, 1),
        'profit_loss_ratio': round(profit_loss_ratio, 2),
        'avg_daily_return_pct': round(avg_daily, 4),
    }


def calculate_volume_analysis(volumes: List[float], closes: List[float]) -> Dict[str, Any]:
    if len(volumes) < 2 or len(closes) < 2:
        return {}
    avg_vol_5 = sum(volumes[-5:]) / min(5, len(volumes)) if len(volumes) >= 5 else sum(volumes) / len(volumes)
    avg_vol_20 = sum(volumes[-20:]) / min(20, len(volumes)) if len(volumes) >= 20 else sum(volumes) / len(volumes)
    vol_ratio = volumes[-1] / avg_vol_5 if avg_vol_5 > 0 else 0
    obv = 0.0
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv += volumes[i]
        elif closes[i] < closes[i - 1]:
            obv -= volumes[i]
    vol_price_corr = 0.0
    if len(volumes) >= 20:
        recent_v = volumes[-20:]
        recent_c = closes[-20:]
        v_mean = sum(recent_v) / len(recent_v)
        c_mean = sum(recent_c) / len(recent_c)
        cov = sum((recent_v[i] - v_mean) * (recent_c[i] - c_mean) for i in range(len(recent_v)))
        v_std = math.sqrt(sum((x - v_mean) ** 2 for x in recent_v))
        c_std = math.sqrt(sum((x - c_mean) ** 2 for x in recent_c))
        vol_price_corr = cov / (v_std * c_std) if v_std > 0 and c_std > 0 else 0
    return {
        'current_volume': volumes[-1],
        'avg_volume_5d': round(avg_vol_5, 0),
        'avg_volume_20d': round(avg_vol_20, 0),
        'volume_ratio': round(vol_ratio, 2),
        'obv': round(obv, 0),
        'vol_price_correlation': round(vol_price_corr, 3),
    }


def generate_technical_signals(indicators: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not indicators or len(indicators) < 2:
        return {'signals': [], 'overall': 'neutral', 'score': 50}
    latest = indicators[-1]
    prev = indicators[-2] if len(indicators) > 1 else {}
    signals = []
    score = 50
    close = latest.get('ma5')
    if close is None:
        return {'signals': [], 'overall': 'neutral', 'score': 50}

    ma5 = latest.get('ma5')
    ma10 = latest.get('ma10')
    ma20 = latest.get('ma20')
    ma60 = latest.get('ma60')
    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20:
            signals.append({'name': '均线多头排列', 'type': 'bullish', 'desc': 'MA5>MA10>MA20，多头趋势'})
            score += 15
        elif ma5 < ma10 < ma20:
            signals.append({'name': '均线空头排列', 'type': 'bearish', 'desc': 'MA5<MA10<MA20，空头趋势'})
            score -= 15
    if ma5 and prev.get('ma5') and ma10 and prev.get('ma10'):
        if prev.get('ma5', 0) < prev.get('ma10', 0) and ma5 > ma10:
            signals.append({'name': '金叉(MA5上穿MA10)', 'type': 'bullish', 'desc': '短期均线上穿中期均线'})
            score += 10
        elif prev.get('ma5', 0) > prev.get('ma10', 0) and ma5 < ma10:
            signals.append({'name': '死叉(MA5下穿MA10)', 'type': 'bearish', 'desc': '短期均线下穿中期均线'})
            score -= 10

    macd = latest.get('macd')
    macd_signal = latest.get('macd_signal')
    macd_hist = latest.get('macd_hist')
    prev_hist = prev.get('macd_hist')
    if macd_hist is not None:
        if macd_hist > 0:
            signals.append({'name': 'MACD红柱', 'type': 'bullish', 'desc': 'MACD柱线为正'})
            score += 5
        else:
            signals.append({'name': 'MACD绿柱', 'type': 'bearish', 'desc': 'MACD柱线为负'})
            score -= 5
        if prev_hist is not None and macd_hist > prev_hist:
            signals.append({'name': 'MACD柱线放大', 'type': 'bullish', 'desc': 'MACD柱线较前日增大'})
            score += 5
        elif prev_hist is not None and macd_hist < prev_hist:
            signals.append({'name': 'MACD柱线缩小', 'type': 'bearish', 'desc': 'MACD柱线较前日减小'})
            score -= 3
    if macd is not None and macd_signal is not None and prev.get('macd') is not None and prev.get('macd_signal') is not None:
        if prev.get('macd', 0) < prev.get('macd_signal', 0) and macd > macd_signal:
            signals.append({'name': 'MACD金叉', 'type': 'bullish', 'desc': 'DIF上穿DEA'})
            score += 10
        elif prev.get('macd', 0) > prev.get('macd_signal', 0) and macd < macd_signal:
            signals.append({'name': 'MACD死叉', 'type': 'bearish', 'desc': 'DIF下穿DEA'})
            score -= 10

    rsi_6 = latest.get('rsi_6')
    rsi_12 = latest.get('rsi_12')
    if rsi_6 is not None:
        if rsi_6 > 80:
            signals.append({'name': 'RSI6超买', 'type': 'bearish', 'desc': f'RSI6={rsi_6:.1f}>80'})
            score -= 10
        elif rsi_6 < 20:
            signals.append({'name': 'RSI6超卖', 'type': 'bullish', 'desc': f'RSI6={rsi_6:.1f}<20'})
            score += 10

    kdj_k = latest.get('kdj_k')
    kdj_d = latest.get('kdj_d')
    kdj_j = latest.get('kdj_j')
    if kdj_j is not None:
        if kdj_j > 100:
            signals.append({'name': 'KDJ超买', 'type': 'bearish', 'desc': f'J值={kdj_j:.1f}>100'})
            score -= 8
        elif kdj_j < 0:
            signals.append({'name': 'KDJ超卖', 'type': 'bullish', 'desc': f'J值={kdj_j:.1f}<0'})
            score += 8
    if kdj_k is not None and kdj_d is not None and prev.get('kdj_k') is not None and prev.get('kdj_d') is not None:
        if prev.get('kdj_k', 0) < prev.get('kdj_d', 0) and kdj_k > kdj_d:
            signals.append({'name': 'KDJ金叉', 'type': 'bullish', 'desc': 'K线上穿D线'})
            score += 8
        elif prev.get('kdj_k', 0) > prev.get('kdj_d', 0) and kdj_k < kdj_d:
            signals.append({'name': 'KDJ死叉', 'type': 'bearish', 'desc': 'K线下穿D线'})
            score -= 8

    boll_upper = latest.get('boll_upper')
    boll_lower = latest.get('boll_lower')
    boll_mid = latest.get('boll_mid')
    if boll_upper and boll_lower and boll_mid:
        current_close = None
        for key in ['close', 'ma5']:
            if latest.get(key):
                current_close = latest[key]
                break
        if current_close:
            if current_close > boll_upper:
                signals.append({'name': '突破布林上轨', 'type': 'bearish', 'desc': '价格突破布林上轨，可能回调'})
                score -= 5
            elif current_close < boll_lower:
                signals.append({'name': '跌破布林下轨', 'type': 'bullish', 'desc': '价格跌破布林下轨，可能反弹'})
                score += 5

    position = latest.get('position_pct')
    if position is not None:
        if position < 20:
            signals.append({'name': '52周低位', 'type': 'bullish', 'desc': f'52周位置={position:.1f}%，处于低位'})
            score += 10
        elif position > 80:
            signals.append({'name': '52周高位', 'type': 'bearish', 'desc': f'52周位置={position:.1f}%，处于高位'})
            score -= 10

    score = max(0, min(100, score))
    if score >= 70:
        overall = 'bullish'
    elif score <= 30:
        overall = 'bearish'
    else:
        overall = 'neutral'

    return {
        'signals': signals,
        'score': score,
        'overall': overall,
        'bullish_count': sum(1 for s in signals if s['type'] == 'bullish'),
        'bearish_count': sum(1 for s in signals if s['type'] == 'bearish'),
    }


def calculate_support_resistance(highs: List[float], lows: List[float], closes: List[float]) -> Dict[str, Any]:
    if len(closes) < 20:
        return {}
    recent_highs = highs[-20:]
    recent_lows = lows[-20:]
    current = closes[-1]
    resistance_levels = sorted(set(recent_highs), reverse=True)[:3]
    support_levels = sorted(set(recent_lows))[:3]
    nearest_resistance = None
    for r in resistance_levels:
        if r > current:
            nearest_resistance = r
            break
    nearest_support = None
    for s in reversed(support_levels):
        if s < current:
            nearest_support = s
            break
    res_distance = (nearest_resistance - current) / current * 100 if nearest_resistance else None
    sup_distance = (current - nearest_support) / current * 100 if nearest_support else None
    return {
        'current_price': current,
        'nearest_resistance': nearest_resistance,
        'nearest_support': nearest_support,
        'resistance_distance_pct': round(res_distance, 2) if res_distance else None,
        'support_distance_pct': round(sup_distance, 2) if sup_distance else None,
        'resistance_levels': resistance_levels,
        'support_levels': support_levels,
    }
