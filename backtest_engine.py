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
                 use_next_open=False, tqqq_open=None, use_dca=False, dca_amount_krw=0.0, dca_day=1, manual_buys=None):
    """
    현금풀/금고 원화 저장 방식 엔진.
    - 현금풀/금고 잔액은 원화로 고정 저장 → 환율 변동에 흔들리지 않음
    - 매수 시에만 그날 환율로 달러 환산하여 주수 계산
    - 현금풀 레벨은 항상 소비(돈 없어도), 부족하면 있는 만큼 매수
    - 금고 첫 투입 직전 현금풀 잔액 완전 소진 (딱 한 번)
    - 금고 레벨도 항상 소비, 부족하면 있는 만큼 매수
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
            bought_levels = set()
            vault_levels = set()
            cash_drained = False   # 리밸런싱 후 새 사이클 시작
            total_cash_pool_krw = cash_krw

        mdd = (price - peak) / peak * 100

        # ── 현금풀 분할매수 ──
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
