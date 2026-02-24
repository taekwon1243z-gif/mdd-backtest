import yfinance as yf
import json
import sys
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import subprocess

plt.rcParams['font.family'] = 'AppleGothic'
plt.rcParams['axes.unicode_minus'] = False

INITIAL_SEED = 10000  # USD 기본값

STRATEGIES = {
    '초반': [
        (-5,  0.10), (-10, 0.15), (-15, 0.10), (-20, 0.10),
        (-25, 0.08), (-30, 0.08), (-35, 0.08), (-40, 0.08),
        (-45, 0.08), (-50, 0.08)
    ],
    '중반': [
        (-5,  0.03), (-10, 0.05), (-15, 0.15), (-20, 0.15),
        (-25, 0.14), (-30, 0.10), (-35, 0.10), (-40, 0.10),
        (-45, 0.09), (-50, 0.09)
    ],
    '후반': [
        (-5,  0.01), (-10, 0.02), (-15, 0.02), (-20, 0.03),
        (-25, 0.05), (-30, 0.08), (-35, 0.10), (-40, 0.13),
        (-45, 0.14), (-50, 0.14)
    ]
}

def make_wallet_table(trigger):
    levels = [trigger - i*5 for i in range(6)]
    ratios = [0.20, 0.20, 0.20, 0.20, 0.10, 0.10]
    return list(zip(levels, ratios))

args = sys.argv[1:]
strategy_name  = '후반'
start_date     = '2010-01-01'
end_date       = None
use_wallet     = False
wallet_amount  = None
wallet_trigger = -50
seed_krw       = None  # 원화 초기 투자금

for i, arg in enumerate(args):
    if arg == '--strategy'       and i+1 < len(args): strategy_name  = args[i+1]
    if arg == '--start'          and i+1 < len(args): start_date     = args[i+1]
    if arg == '--end'            and i+1 < len(args): end_date       = args[i+1]
    if arg == '--wallet':        use_wallet = True
    if arg == '--wallet-amount'  and i+1 < len(args):
        wallet_amount = float(args[i+1]); use_wallet = True
    if arg == '--wallet-trigger' and i+1 < len(args):
        wallet_trigger = -abs(float(args[i+1])); use_wallet = True
    if arg == '--seed-krw'       and i+1 < len(args):
        seed_krw = float(args[i+1])

print('환율 데이터 로딩 중...')
fx_df = yf.download('USDKRW=X', start=start_date, end=end_date, progress=False)['Close']
fx_df = fx_df.dropna().squeeze()
fx_dict = {str(d.date()): float(v) for d, v in zip(fx_df.index, fx_df.values)}
fx_sorted = sorted(fx_dict.keys())

def get_fx(date_str):
    if date_str in fx_dict:
        return fx_dict[date_str]
    past = [d for d in fx_sorted if d <= date_str]
    return fx_dict[past[-1]] if past else 1350

def run_backtest(buy_table):
    df = yf.download('TQQQ', start=start_date, end=end_date, progress=False)['Close']
    df = df.dropna()
    dates  = df.index.tolist()
    prices = df.squeeze().tolist()

    # 시작일 환율로 원화 → 달러 환산
    start_fx = get_fx(str(dates[0].date()))
    if seed_krw is not None:
        seed_usd      = seed_krw / start_fx
        wallet_usd    = (wallet_amount * 10000) / start_fx if wallet_amount else 0
    else:
        seed_usd      = INITIAL_SEED
        wallet_usd    = wallet_amount if wallet_amount else 0

    wallet_table = make_wallet_table(wallet_trigger)
    cash_ratio   = 0.30
    tqqq_ratio   = 0.70

    if use_wallet:
        w           = wallet_usd if wallet_usd else seed_usd * 0.20
        remaining   = seed_usd - w
        tqqq_shares = math.floor((remaining * tqqq_ratio) / prices[0])
        cash        = remaining * cash_ratio + (remaining * tqqq_ratio - tqqq_shares * prices[0])
        wallet      = w
    else:
        tqqq_shares = math.floor((seed_usd * tqqq_ratio) / prices[0])
        cash        = seed_usd * cash_ratio + (seed_usd * tqqq_ratio - tqqq_shares * prices[0])
        wallet      = 0

    peak            = prices[0]
    bought_levels   = set()
    wallet_levels   = set()
    total_cash_pool = cash
    total_wallet    = wallet
    hold_shares     = math.floor(seed_usd / prices[0])
    history         = []

    buy_count        = 0
    wallet_buy_count = 0
    rebalance_count  = 0
    buy_log          = []
    rebalance_log    = []

    for date, price in zip(dates, prices):
        date_str = str(date.date())
        fx = get_fx(date_str)

        if price > peak:
            peak       = price
            old_shares = tqqq_shares
            total      = cash + tqqq_shares * price
            new_shares = math.floor((total * tqqq_ratio) / price)
            cash       = total * cash_ratio + (total * tqqq_ratio - new_shares * price)

            if new_shares != old_shares:
                action = '매수' if new_shares > old_shares else '매도'
                rebalance_count += 1
                rebalance_log.append({
                    'date': date_str, 'price': round(price, 2),
                    'action': action,
                    'shares_diff': abs(new_shares - old_shares),
                    'shares_after': new_shares
                })

            tqqq_shares     = new_shares
            bought_levels   = set()
            wallet_levels   = set()
            total_cash_pool = cash

        mdd = (price - peak) / peak * 100

        for level, ratio in buy_table:
            if mdd <= level and level not in bought_levels:
                invest      = total_cash_pool * ratio
                buy_shares  = math.floor(invest / price)
                actual_cost = buy_shares * price
                if buy_shares >= 1 and cash >= actual_cost:
                    tqqq_shares += buy_shares
                    cash        -= actual_cost
                    buy_count   += 1
                    buy_log.append({
                        'date': date_str, 'price': round(price, 2),
                        'mdd': round(mdd, 2), 'level': level,
                        'shares': buy_shares, 'cost_usd': round(actual_cost, 2),
                        'cost_krw': round(actual_cost * fx, 0),
                        'source': '현금풀'
                    })
                bought_levels.add(level)

        if use_wallet and wallet > 0:
            for level, ratio in wallet_table:
                if mdd <= level and level not in wallet_levels:
                    invest      = total_wallet * ratio
                    buy_shares  = math.floor(invest / price)
                    actual_cost = buy_shares * price
                    if buy_shares >= 1 and wallet >= actual_cost:
                        tqqq_shares      += buy_shares
                        wallet           -= actual_cost
                        wallet_buy_count += 1
                        buy_log.append({
                            'date': date_str, 'price': round(price, 2),
                            'mdd': round(mdd, 2), 'level': level,
                            'shares': buy_shares, 'cost_usd': round(actual_cost, 2),
                            'cost_krw': round(actual_cost * fx, 0),
                            'source': '지갑'
                        })
                    wallet_levels.add(level)

        total_usd = cash + tqqq_shares * price + wallet
        history.append({
            'date':        date_str,
            'price':       round(price, 2),
            'mdd':         round(mdd, 2),
            'cash':        round(cash, 2),
            'wallet':      round(wallet, 2),
            'tqqq_shares': tqqq_shares,
            'tqqq_value':  round(tqqq_shares * price, 2),
            'total_usd':   round(total_usd, 2),
            'total_krw':   round(total_usd * fx, 0),
            'hold_shares': hold_shares,
            'hold_usd':    round(hold_shares * price, 2),
            'hold_krw':    round(hold_shares * price * fx, 0),
            'fx':          round(fx, 2)
        })

    stats = {
        'seed_usd':         round(seed_usd, 2),
        'start_fx':         round(start_fx, 2),
        'buy_count':        buy_count,
        'wallet_buy_count': wallet_buy_count,
        'rebalance_count':  rebalance_count,
        'total_tx':         buy_count + wallet_buy_count + rebalance_count,
        'buy_log':          buy_log,
        'rebalance_log':    rebalance_log
    }
    return history, stats

def print_result(name, history, stats):
    initial_usd  = history[0]['total_usd']
    final_usd    = history[-1]['total_usd']
    final_krw    = history[-1]['total_krw']
    hold_usd     = history[-1]['hold_usd']
    hold_krw     = history[-1]['hold_krw']
    max_krw      = max(h['total_krw'] for h in history)
    min_krw      = min(h['total_krw'] for h in history)
    worst_mdd    = min(h['mdd'] for h in history)
    final_fx     = history[-1]['fx']
    final_shares = history[-1]['tqqq_shares']
    hold_shares  = history[-1]['hold_shares']
    rate         = (final_usd / initial_usd - 1) * 100
    hold_rate    = (hold_usd / initial_usd - 1) * 100

    # 원화 기준 초기 자산
    initial_krw  = history[0]['total_krw']
    krw_rate     = (final_krw / initial_krw - 1) * 100

    w_label = ''
    if use_wallet:
        w_krw = int(wallet_amount * 10000) if seed_krw and wallet_amount else int((wallet_amount or stats['seed_usd']*0.2) * final_fx)
        w_label = f' + 지갑({w_krw:,}원 / {wallet_trigger}%부터)'

    seed_label = f'{int(seed_krw):,}원' if seed_krw else f'${stats["seed_usd"]:,.0f}'

    print(f"\n{'='*62}")
    print(f"  [{name} 집중형{w_label}]")
    print(f"  초기 투자금: {seed_label}  (시작 환율: {stats['start_fx']:,.0f}원)")
    print(f"  {history[0]['date']} ~ {history[-1]['date']}  |  현재 환율: {final_fx:,.0f}원")
    print(f"{'='*62}")
    print(f"초기 자산:         {initial_krw:,.0f}원  (${initial_usd:,.0f})")
    print(f"최종 자산 (전략):  {final_krw:,.0f}원  (${final_usd:,.0f})  {krw_rate:+.1f}%")
    print(f"최종 자산 (홀딩):  {hold_krw:,.0f}원  (${hold_usd:,.0f})  {hold_rate:+.1f}%")
    print(f"최고 자산:         {max_krw:,.0f}원")
    print(f"최저 자산:         {min_krw:,.0f}원")
    print(f"TQQQ 최대 낙폭:    {worst_mdd:.1f}%")
    print(f"{'─'*62}")
    print(f"현재 보유 (전략):  {final_shares}주")
    print(f"현재 보유 (홀딩):  {hold_shares}주")
    print(f"{'─'*62}")
    print(f"📊 거래 내역")
    print(f"  현금풀 매수:     {stats['buy_count']}회")
    if use_wallet:
        print(f"  지갑 매수:       {stats['wallet_buy_count']}회")
    print(f"  리밸런싱:        {stats['rebalance_count']}회")
    print(f"  총 거래 횟수:    {stats['total_tx']}회")
    if stats['buy_log']:
        print(f"{'─'*62}")
        print(f"📋 최근 매수 내역 (최대 5건)")
        for b in stats['buy_log'][-5:]:
            print(f"  {b['date']}  MDD {b['mdd']:+.1f}%  {b['level']}% 구간  {b['shares']}주  {b['cost_krw']:,.0f}원  [{b['source']}]")
    if stats['rebalance_log']:
        print(f"{'─'*62}")
        print(f"📋 최근 리밸런싱 내역 (최대 5건)")
        for r in stats['rebalance_log'][-5:]:
            action_label = '매수 ▲' if r['action'] == '매수' else '매도 ▼'
            print(f"  {r['date']}  ${r['price']:,.2f}  {action_label}  {r['shares_diff']}주  → 보유 {r['shares_after']}주")

def draw_chart(results, all_stats):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 12), gridspec_kw={'height_ratios': [3, 1]})
    fig.patch.set_facecolor('#1a1a2e')
    for ax in [ax1, ax2]:
        ax.set_facecolor('#16213e')

    colors = {'초반': '#e74c3c', '중반': '#f39c12', '후반': '#2ecc71'}

    for name, history in results.items():
        stats      = all_stats[name]
        dates_list = [h['date'] for h in history]
        totals_krw = [h['total_krw'] for h in history]
        final_krw  = totals_krw[-1]
        initial_krw = totals_krw[0]
        rate       = (final_krw / initial_krw - 1) * 100
        shares     = history[-1]['tqqq_shares']
        tx         = stats['total_tx']
        ax1.plot(range(len(dates_list)), totals_krw,
                 label=f"{name}  {final_krw:,.0f}원 ({rate:+.1f}%)  |  {shares}주  |  거래 {tx}회",
                 color=colors[name], linewidth=2.5)
        for b in stats['buy_log']:
            try:
                idx = dates_list.index(b['date'])
                ax1.scatter(idx, totals_krw[idx], color=colors[name], s=40, zorder=5, alpha=0.7, marker='^')
            except ValueError:
                pass

    first       = list(results.values())[0]
    dates_list  = [h['date'] for h in first]
    hold_krw    = [h['hold_krw'] for h in first]
    initial_krw = first[0]['total_krw']
    hold_rate   = (hold_krw[-1] / initial_krw - 1) * 100
    hold_shares = first[-1]['hold_shares']
    ax1.plot(range(len(dates_list)), hold_krw,
             label=f"단순 홀딩  {hold_krw[-1]:,.0f}원 ({hold_rate:+.1f}%)  |  {hold_shares}주",
             color='#74b9ff', linewidth=2, linestyle='--', alpha=0.8)

    ax1.axhline(y=initial_krw, color='white', linewidth=0.8, linestyle=':', alpha=0.4)
    ax1.text(5, initial_krw * 1.02, f'시작 {initial_krw:,.0f}원', color='white', fontsize=10, alpha=0.6)

    fx_vals = [h['fx'] for h in first]
    ax2.plot(range(len(dates_list)), fx_vals, color='#a29bfe', linewidth=1.5, label='USD/KRW 환율')
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{x:,.0f}'))
    ax2.set_ylabel('환율 (원)', fontsize=11, color='white')
    ax2.tick_params(colors='white')
    ax2.legend(fontsize=10, facecolor='#0f3460', labelcolor='white', edgecolor='#444')
    ax2.grid(True, alpha=0.2, color='white')
    for spine in ax2.spines.values():
        spine.set_edgecolor('#444')

    xticks_idx   = list(range(0, len(dates_list), max(1, len(dates_list)//8)))
    xtick_labels = [dates_list[i][:7] for i in xticks_idx]
    for ax in [ax1, ax2]:
        ax.set_xticks(xticks_idx)
        ax.set_xticklabels(xtick_labels, rotation=45, color='white', fontsize=10)

    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{x:,.0f}원'))
    ax1.tick_params(colors='white')
    ax1.set_ylabel('자산 (원)', fontsize=12, color='white')
    for spine in ax1.spines.values():
        spine.set_edgecolor('#444')

    seed_label = f'{int(seed_krw):,}원' if seed_krw else f'${list(all_stats.values())[0]["seed_usd"]:,.0f}'
    w_label = ''
    if use_wallet:
        w_krw = int(wallet_amount * 10000) if seed_krw and wallet_amount else ''
        w_label = f' + 지갑({w_krw:,}원 / {wallet_trigger}%부터)' if w_krw else f' + 지갑'
    ax1.set_title(
        f'MDD 방어법 전략 비교 (원화 기준){w_label}\n'
        f'초기 {seed_label}  |  {dates_list[0]} ~ {dates_list[-1]}  |  ▲ 매수 시점',
        fontsize=15, color='white', pad=15, fontweight='bold')
    ax1.legend(fontsize=11, facecolor='#0f3460', labelcolor='white', edgecolor='#444', loc='upper left')
    ax1.grid(True, alpha=0.2, color='white')

    plt.tight_layout()
    plt.savefig('backtest_chart.png', dpi=150, facecolor='#1a1a2e')
    print('\n차트 저장 완료: backtest_chart.png')

print('TQQQ 데이터 로딩 중...')
results   = {}
all_stats = {}

if strategy_name == '전체':
    for name, table in STRATEGIES.items():
        history, stats = run_backtest(table)
        print_result(name, history, stats)
        results[name]   = history
        all_stats[name] = stats
        with open(f'backtest_{name}.json', 'w') as f:
            json.dump({'history': history, 'stats': stats}, f, ensure_ascii=False)
else:
    if strategy_name not in STRATEGIES:
        print(f"오류: 초반 / 중반 / 후반 / 전체 중 선택하세요")
        sys.exit(1)
    history, stats = run_backtest(STRATEGIES[strategy_name])
    print_result(strategy_name, history, stats)
    results[strategy_name]   = history
    all_stats[strategy_name] = stats
    with open('backtest_result.json', 'w') as f:
        json.dump({'history': history, 'stats': stats}, f, ensure_ascii=False)
    with open(f'backtest_{strategy_name}.json', 'w') as f:
        json.dump({'history': history, 'stats': stats}, f, ensure_ascii=False)

draw_chart(results, all_stats)
subprocess.Popen(['open', 'backtest_chart.png'])
