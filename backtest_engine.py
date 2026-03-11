import math
import datetime as _dt


def get_fx(fx_dict, fx_sorted, date_str):
    if date_str in fx_dict:
        return fx_dict[date_str]
    past = [d for d in fx_sorted if d <= date_str]
    return fx_dict[past[-1]] if past else 1350


def make_vault_table(trigger):
    # trigger+5부터 시작: 현금풀 마지막 레벨(-trigger)과 겹치지 않게
    levels = [-(trigger + 5 + i * 5) for i in range(6)]
    return list(zip(levels, [0.20, 0.20, 0.20, 0.20, 0.10, 0.10]))


def run_backtest(buy_table, tqqq, fx_dict, fx_sorted, seed_krw, use_vault, vault_krw_init, vault_trigger,
                 use_next_open=False, tqqq_open=None, use_dca=False, dca_amount_krw=0.0, dca_day=1,
                 manual_buys=None, rebalance_band=0.05):
    """
    현금풀/금고 원화 저장 방식 엔진.
    - 현금풀/금고 잔액은 원화로 고정 저장 → 환율 변동에 흔들리지 않음
    - 매수 시에만 그날 환율로 달러 환산하여 주수 계산
    - 현금풀 레벨은 항상 소비(돈 없어도), 부족하면 있는 만큼 매수
    - 갭다운 시 통과한 모든 레벨 동시 매수 (더 좋은 가격에 약정 이행)
    - 금고 첫 투입 직전 현금풀 잔액 완전 소진 (딱 한 번)
    - 금고 레벨도 항상 소비, 부족하면 있는 만큼 매수

    rebalance_band: TQQQ 비율이 목표(70%)에서 이 값 이상 벗어날 때만 리밸런싱
                    0.0 = 신고가마다 항상 리밸런싱 (비현실적)
                    0.05 = ±5% 벗어날 때만 (권장)
    """
    dates = tqqq.index.tolist()
    prices = tqqq.tolist()
    vault_table = make_vault_table(vault_trigger)
    cash_ratio = 0.30
    tqqq_ratio = 0.70

    # ── 초기값 계산 ──
    start_fx = get_fx(fx_dict, fx_sorted, str(dates[0].date()))
    seed_usd = seed_krw / start_fx
    tqqq_shares = math.floor((seed_usd * tqqq_ratio) / prices[0])
    leftover_krw = round((seed_usd * tqqq_ratio - tqqq_shares * prices[0]) * start_fx)
    cash_krw = round(seed_krw * cash_ratio) + leftover_krw
    vault_krw = vault_krw_init if use_vault else 0

    total_cash_pool_krw = cash_krw   # 비율 계산 기준 (초기값 고정)
    total_vault_krw = vault_krw      # 비율 계산 기준 (초기값 고정)

    # 단순홀딩 주수 (시드+금고 전액 투자 기준)
    hold_shares = math.floor((seed_krw + vault_krw_init) / start_fx / prices[0])

    peak = prices[0]
    bought_levels = set()   # 현금풀에서 이미 소비한 레벨
    vault_levels = set()    # 금고에서 이미 소비한 레벨
    cash_drained = False    # 현금풀 잔액소진 실행 여부 (딱 한 번만)

    history = []
    buy_log = []
    rebalance_log = []
    buy_count = 0
    vault_buy_count = 0
    rebalance_count = 0
    opens = tqqq_open.tolist() if tqqq_open is not None else prices

    for i, (date, price) in enumerate(zip(dates, prices)):
        date_str = str(date.date())
        fx = get_fx(fx_dict, fx_sorted, date_str)
        buy_price = opens[i + 1] if (use_next_open and tqqq_open is not None and i + 1 < len(opens)) else price

        # ── 신고가 갱신 → 리밸런싱 ──
        if price > peak:
            peak = price
            total_krw = cash_krw + tqqq_shares * price * fx
            tqqq_ratio_actual = (tqqq_shares * price * fx) / total_krw if total_krw > 0 else 0

            # 리밸런싱: 비율이 밴드 밖으로 벗어났을 때만 실행
            if abs(tqqq_ratio_actual - tqqq_ratio) > rebalance_band:
                new_shares = math.floor((total_krw * tqqq_ratio) / (price * fx))
                leftover = round(total_krw * tqqq_ratio - new_shares * price * fx)
                old_shares = tqqq_shares
                tqqq_shares = new_shares
                cash_krw = round(total_krw * cash_ratio) + leftover
                if new_shares != old_shares:
                    action = '매수' if new_shares > old_shares else '매도'
                    rebalance_count += 1
                    rebalance_log.append({'date': date_str, 'price': round(price, 2), 'action': action,
                                          'shares_diff': abs(new_shares - old_shares), 'shares_after': new_shares})

            # 신고가 → 레벨 리셋은 항상 (리밸런싱 여부와 무관)
            bought_levels = set()
            vault_levels = set()
            cash_drained = False
            total_cash_pool_krw = cash_krw

        mdd = (price - peak) / peak * 100

        # ── 현금풀 분할매수 ──
        # 갭다운 시 통과한 모든 레벨 동시 매수 (더 좋은 가격에 약정 이행)
        for level, ratio in buy_table:
            if mdd <= level and level not in bought_levels:
                invest_krw = total_cash_pool_krw * ratio
                buy_shares = math.floor(invest_krw / (buy_price * fx))
                # 잔액 부족하면 있는 만큼
                if buy_shares * buy_price * fx > cash_krw:
                    buy_shares = math.floor(cash_krw / (buy_price * fx))
                actual_cost_krw = round(buy_shares * buy_price * fx)
                if buy_shares >= 1:
                    tqqq_shares += buy_shares
                    cash_krw -= actual_cost_krw
                    buy_count += 1
                    buy_log.append({'date': date_str, 'price': round(buy_price, 2), 'mdd': round(mdd, 2),
                                    'level': level, 'shares': buy_shares, 'shares_total': tqqq_shares,
                                    'cost_krw': actual_cost_krw, 'source': '현금풀',
                                    'fx': round(fx, 2),
                                    'cash_after_krw': cash_krw, 'vault_after_krw': vault_krw})
                bought_levels.add(level)   # 항상 레벨 소비 (돈 없어도)

        # ── 금고 첫 투입 직전: 현금풀 잔액 완전 소진 (딱 한 번) ──
        if use_vault and vault_krw > 0 and not cash_drained:
            first_vault_triggered = any(mdd <= lvl for lvl, _ in vault_table)
            if first_vault_triggered:
                drain_shares = math.floor(cash_krw / (buy_price * fx))
                drain_cost_krw = round(drain_shares * buy_price * fx)
                if drain_shares >= 1:
                    tqqq_shares += drain_shares
                    cash_krw -= drain_cost_krw
                    buy_count += 1
                    buy_log.append({'date': date_str, 'price': round(buy_price, 2), 'mdd': round(mdd, 2),
                                    'level': -999, 'shares': drain_shares, 'shares_total': tqqq_shares,
                                    'cost_krw': drain_cost_krw, 'source': '현금풀',
                                    'fx': round(fx, 2),
                                    'cash_after_krw': cash_krw, 'vault_after_krw': vault_krw})
                cash_drained = True   # 이후 절대 재실행 안 함

        # ── 금고 분할매수 ──
        if use_vault and vault_krw > 0:
            for level, ratio in vault_table:
                if mdd <= level and level not in vault_levels:
                    invest_krw = total_vault_krw * ratio
                    buy_shares = math.floor(invest_krw / (buy_price * fx))
                    # 잔액 부족하면 있는 만큼
                    if buy_shares * buy_price * fx > vault_krw:
                        buy_shares = math.floor(vault_krw / (buy_price * fx))
                    actual_cost_krw = round(buy_shares * buy_price * fx)
                    if buy_shares >= 1:
                        tqqq_shares += buy_shares
                        vault_krw -= actual_cost_krw
                        vault_buy_count += 1
                        buy_log.append({'date': date_str, 'price': round(buy_price, 2), 'mdd': round(mdd, 2),
                                        'level': level, 'shares': buy_shares, 'shares_total': tqqq_shares,
                                        'cost_krw': actual_cost_krw, 'source': '금고',
                                        'fx': round(fx, 2),
                                        'cash_after_krw': cash_krw, 'vault_after_krw': vault_krw})
                    vault_levels.add(level)   # 항상 레벨 소비

        # ── DCA ──
        if use_dca and dca_amount_krw > 0:
            if date_str[8:10] == f'{dca_day:02d}':
                buy_shares = math.floor(dca_amount_krw / (buy_price * fx))
                actual_cost_krw = round(buy_shares * buy_price * fx)
                if buy_shares >= 1:
                    tqqq_shares += buy_shares
                    buy_count += 1
                    buy_log.append({'date': date_str, 'price': round(buy_price, 2), 'mdd': round(mdd, 2),
                                    'level': 0, 'shares': buy_shares, 'shares_total': tqqq_shares,
                                    'cost_krw': actual_cost_krw, 'source': 'DCA',
                                    'fx': round(fx, 2),
                                    'cash_after_krw': cash_krw, 'vault_after_krw': vault_krw})
                hold_shares += math.floor(dca_amount_krw / (buy_price * fx))

        # ── 사용자 개입 매수 ──
        if manual_buys:
            for mb in manual_buys:
                if mb['date'] == date_str:
                    buy_shares = math.floor(mb['amount_krw'] / (buy_price * fx))
                    actual_cost_krw = round(buy_shares * buy_price * fx)
                    if buy_shares >= 1:
                        tqqq_shares += buy_shares
                        buy_log.append({'date': date_str, 'price': round(buy_price, 2), 'mdd': round(mdd, 2),
                                        'level': 0, 'shares': buy_shares, 'shares_total': tqqq_shares,
                                        'cost_krw': actual_cost_krw, 'source': '사용자개입',
                                        'fx': round(fx, 2),
                                        'cash_after_krw': cash_krw, 'vault_after_krw': vault_krw})

        # ── history 기록 (매주 월요일 + 마지막 날) ──
        total_krw = cash_krw + tqqq_shares * price * fx + vault_krw
        if _dt.datetime.strptime(date_str, '%Y-%m-%d').weekday() == 0 or i == len(tqqq) - 1:
            history.append({'date': date_str, 'price': round(price, 2), 'mdd': round(mdd, 2),
                             'tqqq_shares': tqqq_shares, 'total_krw': round(total_krw, 0),
                             'hold_krw': round(hold_shares * price * fx, 0),
                             'fx': round(fx, 2), 'cash_krw': cash_krw, 'vault_krw': vault_krw})

    stats = {'buy_count': buy_count, 'vault_buy_count': vault_buy_count,
             'rebalance_count': rebalance_count,
             'total_tx': buy_count + vault_buy_count + rebalance_count,
             'buy_log': buy_log, 'rebalance_log': rebalance_log}
    return history, stats


# ── 비율 최적화 ──────────────────────────────────────────────────────────────

LEVELS = [-5, -10, -15, -20, -25, -30, -35, -40, -45, -50]


def _bottom_bucket(mdd, levels=LEVELS):
    """mdd가 속하는 버킷 인덱스 반환. 버킷 i = levels[i] ~ levels[i+1] 구간."""
    n = len(levels)
    for i in range(n - 1):
        if levels[i] >= mdd > levels[i + 1]:
            return i
    return n - 1


def _extract_qqq_episodes(qqq_prices, threshold=-5.0):
    """
    QQQ 가격에서 낙폭 에피소드를 추출한다.
    에피소드 = QQQ ATH 대비 threshold% 이하 진입 ~ QQQ ATH 회복.
    QQQ를 기준으로 쓰는 이유: 25년치 데이터가 완전히 완료된 에피소드로 구성됨.
    """
    prices = list(qqq_prices)
    dates  = list(qqq_prices.index)
    peak   = prices[0]

    episodes = []
    in_ep        = False
    ep_start_i   = 0
    ep_peak_price = prices[0]

    for i, price in enumerate(prices):
        if price > peak:
            peak = price

        mdd = (price - peak) / peak * 100

        if not in_ep and mdd <= threshold:
            in_ep         = True
            ep_start_i    = i
            ep_peak_price = peak          # 에피소드 시작 시점의 QQQ ATH

        elif in_ep:
            if price >= ep_peak_price * 0.999:   # QQQ ATH 회복
                episodes.append({
                    'start_i':    ep_start_i,
                    'end_i':      i,
                    'start_date': dates[ep_start_i],
                    'end_date':   dates[i],
                    'completed':  True,
                })
                in_ep = False

    if in_ep:   # 현재 진행 중
        episodes.append({
            'start_i':    ep_start_i,
            'end_i':      len(prices) - 1,
            'start_date': dates[ep_start_i],
            'end_date':   dates[-1],
            'completed':  False,
        })

    return episodes


def compute_optimal_ratios(qqq_prices, tqqq_prices, levels=None):
    """
    QQQ 에피소드 경계 + TQQQ 증분 하락 기반 최적 비율 도출.

    알고리즘
    --------
    에피소드 정의: QQQ ATH 대비 -5% 이하 진입 ~ QQQ ATH 회복
      → QQQ 기준: 닷컴버블(2000~2016 회복)도 완료 에피소드로 처리 가능
      → 에피소드 수 29개 (QQQ 에피소드 기준)

    TQQQ MDD 기준: 에피소드 시작 시점 TQQQ 가격 = 100%
      → "조정 시작점에서 TQQQ가 얼마나 더 내려가는가" 측정
      → 합성 TQQQ 역산 ATH 오염 완전 제거

    P[i]: 에피소드 내 TQQQ 증분 저점이 버킷 i에 속하는 비율
    E[i]: TQQQ 레벨 i 첫 진입 → QQQ ATH 회복일 TQQQ 가격까지 수익률 평균
    ratio ∝ P × E, 1% 플로어 후 정규화

    Parameters
    ----------
    qqq_prices  : pd.Series  QQQ 종가 (1999~현재, auto_adjust=True)
    tqqq_prices : pd.Series  합성+실제 TQQQ 종가 (1999~현재)
    """
    if levels is None:
        levels = LEVELS
    n = len(levels)

    qqq  = qqq_prices.sort_index()
    tqqq = tqqq_prices.sort_index()

    episodes = _extract_qqq_episodes(qqq, threshold=-5.0)
    if not episodes:
        return None

    bottom_counts    = [0] * n
    returns_by_level = [[] for _ in range(n)]
    ep_details       = []

    for ep in episodes:
        sd, ed = ep['start_date'], ep['end_date']

        # 에피소드 구간 TQQQ 슬라이스
        tqqq_ep = tqqq[(tqqq.index >= sd) & (tqqq.index <= ed)]
        if len(tqqq_ep) < 5:
            continue

        # ★ TQQQ MDD = 에피소드 시작가 기준 증분 하락률
        #   (합성 TQQQ 역산 ATH 오염 제거 — "조정 시작점에서 얼마나 더 빠지나" 측정)
        ep_prices      = list(tqqq_ep)
        ep_start_price = ep_prices[0]
        ep_mdd_arr     = [(p / ep_start_price - 1) * 100 for p in ep_prices]
        bottom_mdd     = min(ep_mdd_arr)

        # P: TQQQ 저점 버킷 카운트 (완료/진행 중 모두 반영)
        b = _bottom_bucket(bottom_mdd, levels)
        bottom_counts[b] += 1

        # E: QQQ ATH 회복일의 TQQQ 가격 → 완료 에피소드만
        if ep['completed']:
            # QQQ 회복일 당일 또는 그 다음 거래일 TQQQ 가격
            tqqq_after = tqqq[tqqq.index >= ed]
            tqqq_recovery_price = float(tqqq_after.iloc[0]) if len(tqqq_after) > 0 else ep_prices[-1]

            for i, lvl in enumerate(levels):
                for j, mdd in enumerate(ep_mdd_arr):
                    if mdd <= lvl:
                        ret = (tqqq_recovery_price / ep_prices[j] - 1) * 100
                        returns_by_level[i].append(ret)
                        break

        ep_details.append({
            'start':           str(sd.date()),
            'end':             str(ed.date()),
            'tqqq_bottom_mdd': round(bottom_mdd, 1),
            'completed':       ep['completed'],
        })

    total  = len(ep_details)
    p_dist = [c / total for c in bottom_counts]
    e_return = [sum(r) / len(r) if r else 0.0 for r in returns_by_level]

    # ── P × E → 정규화 ──
    raw_score   = [p * e for p, e in zip(p_dist, e_return)]
    total_score = sum(raw_score)
    normed      = [r / total_score for r in raw_score] if total_score > 0 else [1 / n] * n

    FLOOR        = 0.01
    floored      = [max(r, FLOOR) for r in normed]
    base_ratios  = [r / sum(floored) for r in floored]

    return {
        'levels':        levels,
        'n_episodes':    total,
        'episodes':      ep_details,
        'bottom_counts': bottom_counts,
        'p_dist':        p_dist,
        'e_return':      e_return,
        'raw_score':     raw_score,
        'base_ratios':   base_ratios,
        'n_returns':     [len(r) for r in returns_by_level],
    }


def make_strategy_variants(base_ratios, levels=None):
    """
    데이터 기반 기본 비율을 3가지 전략으로 변환한다.
    초반 집중형: 앞 버킷 가중치 증가  (front-loaded)
    중반 집중형: 데이터 기반 기본값
    후반 집중형: 뒤 버킷 가중치 증가  (back-loaded)
    """
    if levels is None:
        levels = LEVELS
    n = len(base_ratios)

    def shift(ratios, mult):
        raw = [r * m for r, m in zip(ratios, mult)]
        s = sum(raw)
        return [r / s for r in raw] if s > 0 else list(ratios)

    front_mult = [2.0 - 1.5 * (i / (n - 1)) for i in range(n)]   # 2.0 → 0.5
    back_mult  = [0.5 + 1.5 * (i / (n - 1)) for i in range(n)]    # 0.5 → 2.0

    front = shift(base_ratios, front_mult)
    back  = shift(base_ratios, back_mult)

    return {
        '초반 집중형': list(zip(levels, [round(r, 4) for r in front])),
        '중반 집중형': list(zip(levels, [round(r, 4) for r in base_ratios])),
        '후반 집중형': list(zip(levels, [round(r, 4) for r in back])),
    }
