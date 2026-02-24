import streamlit as st
import yfinance as yf
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.font_manager as fm
import urllib.request, os

def setup_korean_font():
    font_path = '/tmp/NanumGothic.ttf'
    if not os.path.exists(font_path):
        url = 'https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf'
        urllib.request.urlretrieve(url, font_path)
    fm.fontManager.addfont(font_path)
    plt.rcParams['font.family'] = fm.FontProperties(fname=font_path).get_name()

setup_korean_font()
import pandas as pd


plt.rcParams['axes.unicode_minus'] = False

st.set_page_config(page_title='MDD 방어법 백테스터', page_icon='📈', layout='wide')

STRATEGIES = {
    '초반 집중형': [(-5,0.10),(-10,0.15),(-15,0.10),(-20,0.10),(-25,0.08),(-30,0.08),(-35,0.08),(-40,0.08),(-45,0.08),(-50,0.08)],
    '중반 집중형': [(-5,0.03),(-10,0.05),(-15,0.15),(-20,0.15),(-25,0.14),(-30,0.10),(-35,0.10),(-40,0.10),(-45,0.09),(-50,0.09)],
    '후반 집중형': [(-5,0.01),(-10,0.02),(-15,0.02),(-20,0.03),(-25,0.05),(-30,0.08),(-35,0.10),(-40,0.13),(-45,0.14),(-50,0.14)]
}

def make_vault_table(trigger):
    levels = [-(trigger + i*5) for i in range(6)]
    return list(zip(levels, [0.20,0.20,0.20,0.20,0.10,0.10]))

@st.cache_data(show_spinner=False)
def load_data(start, end):
    import time
    for attempt in range(3):
        try:
            tqqq = yf.download('TQQQ', start=start, end=end, progress=False, auto_adjust=False)
            fx   = yf.download('USDKRW=X', start=start, end=end, progress=False, auto_adjust=False)
            if 'Close' in tqqq.columns:
                tqqq = tqqq['Close'].dropna().squeeze()
            else:
                tqqq = tqqq.iloc[:, 0].dropna().squeeze()
            if 'Close' in fx.columns:
                fx = fx['Close'].dropna().squeeze()
            else:
                fx = fx.iloc[:, 0].dropna().squeeze()
            if len(tqqq) > 0 and len(fx) > 0:
                return tqqq, fx
        except Exception as e:
            pass
        time.sleep(2)
    st.error('데이터를 불러오지 못했어요. 잠시 후 다시 시도해주세요.')
    st.stop()

def get_fx(fx_dict, fx_sorted, date_str):
    if date_str in fx_dict:
        return fx_dict[date_str]
    past = [d for d in fx_sorted if d <= date_str]
    return fx_dict[past[-1]] if past else 1350

def run_backtest(buy_table, tqqq, fx_dict, fx_sorted, seed_usd, use_vault, vault_usd, vault_trigger):
    dates  = tqqq.index.tolist()
    prices = tqqq.tolist()
    vault_table = make_vault_table(vault_trigger)
    cash_ratio = 0.30; tqqq_ratio = 0.70

    if use_vault:
        w           = vault_usd
        remaining   = seed_usd - w
        tqqq_shares = math.floor((remaining * tqqq_ratio) / prices[0])
        cash        = remaining * cash_ratio + (remaining * tqqq_ratio - tqqq_shares * prices[0])
        vault       = w
    else:
        tqqq_shares = math.floor((seed_usd * tqqq_ratio) / prices[0])
        cash        = seed_usd * cash_ratio + (seed_usd * tqqq_ratio - tqqq_shares * prices[0])
        vault       = 0

    peak = prices[0]
    bought_levels = set(); vault_levels = set()
    total_cash_pool = cash; total_vault = vault
    hold_shares = math.floor(seed_usd / prices[0])
    history = []; buy_log = []; rebalance_log = []
    buy_count = 0; vault_buy_count = 0; rebalance_count = 0

    for date, price in zip(dates, prices):
        date_str = str(date.date())
        fx = get_fx(fx_dict, fx_sorted, date_str)

        if price > peak:
            peak = price
            old_shares = tqqq_shares
            total = cash + tqqq_shares * price
            new_shares = math.floor((total * tqqq_ratio) / price)
            cash = total * cash_ratio + (total * tqqq_ratio - new_shares * price)
            if new_shares != old_shares:
                action = '매수' if new_shares > old_shares else '매도'
                rebalance_count += 1
                rebalance_log.append({'date': date_str, 'price': round(price,2),
                    'action': action, 'shares_diff': abs(new_shares-old_shares), 'shares_after': new_shares})
            tqqq_shares = new_shares
            bought_levels = set(); vault_levels = set()
            total_cash_pool = cash

        mdd = (price - peak) / peak * 100

        for level, ratio in buy_table:
            if mdd <= level and level not in bought_levels:
                invest = total_cash_pool * ratio
                buy_shares = math.floor(invest / price)
                actual_cost = buy_shares * price
                if buy_shares >= 1 and cash >= actual_cost:
                    tqqq_shares += buy_shares; cash -= actual_cost; buy_count += 1
                    buy_log.append({'date': date_str, 'price': round(price,2),
                        'mdd': round(mdd,2), 'level': level, 'shares': buy_shares,
                        'cost_krw': round(actual_cost*fx,0), 'source': '현금풀'})
                bought_levels.add(level)

        if use_vault and vault > 0:
            for level, ratio in vault_table:
                if mdd <= level and level not in vault_levels:
                    invest = total_vault * ratio
                    buy_shares = math.floor(invest / price)
                    actual_cost = buy_shares * price
                    if buy_shares >= 1 and vault >= actual_cost:
                        tqqq_shares += buy_shares; vault -= actual_cost; vault_buy_count += 1
                        buy_log.append({'date': date_str, 'price': round(price,2),
                            'mdd': round(mdd,2), 'level': level, 'shares': buy_shares,
                            'cost_krw': round(actual_cost*fx,0), 'source': '금고'})
                    vault_levels.add(level)

        total_usd = cash + tqqq_shares * price + vault
        history.append({
            'date': date_str, 'price': round(price,2), 'mdd': round(mdd,2),
            'tqqq_shares': tqqq_shares,
            'total_usd': round(total_usd,2), 'total_krw': round(total_usd*fx,0),
            'hold_usd': round(hold_shares*price,2), 'hold_krw': round(hold_shares*price*fx,0),
            'fx': round(fx,2)
        })

    stats = {'buy_count': buy_count, 'vault_buy_count': vault_buy_count,
             'rebalance_count': rebalance_count,
             'total_tx': buy_count+vault_buy_count+rebalance_count,
             'buy_log': buy_log, 'rebalance_log': rebalance_log}
    return history, stats

# ── UI 시작 ──────────────────────────────────────────

st.title('📈 MDD 방어법 백테스터')
st.caption('TQQQ 폭락 구간 분할매수 전략 시뮬레이터')

if 'step' not in st.session_state:
    st.session_state.step = 1
if 'results' not in st.session_state:
    st.session_state.results = None
if 'selected_strategy' not in st.session_state:
    st.session_state.selected_strategy = None

# ── 전략 소개 ──
with st.expander('💡 이 전략이 뭔가요? (처음이시면 꼭 읽어보세요)', expanded=True):
    st.markdown('''
# 📖 MDD 방어법 — 폭락을 기회로 바꾸는 투자 전략

---

## 🧭 이 전략을 만든 이유 — 장투는 심플해야 한다

투자를 오래 지속하려면 **지치지 않아야 해요.**

매일 기업 실적을 분석하고, 산업 트렌드를 공부하고, 뉴스에 반응해 잦은 트레이딩을 하다 보면
3년, 5년을 버티는 게 현실적으로 어려워요.
그렇게 지쳐서 포기하면 복리 수익을 챙길 기회를 잃는 거예요.

> **"심플할수록 오래 간다. 오래 갈수록 복리가 커진다."**

그래서 이 전략은 종목 분석이 필요 없는 **지수 추종 ETF**를 선택했어요.
나스닥100은 애플, 마이크로소프트, 엔비디아 등 미국 최고 기술 기업 100개를 담고 있어요.
개별 기업이 망해도 지수는 살아남고, 역사적으로 항상 우상향했어요.

그리고 규칙을 미리 정해놨어요.
"전고점 대비 -X% 빠지면 Y만큼 산다."
이 규칙이 있으면 폭락장에서 패닉셀 하지 않고, 오히려 기계적으로 매수할 수 있어요.
감정이 아니라 시스템이 투자하는 거예요.

---

## 💥 먼저 솔직한 이야기부터

TQQQ는 나스닥100 지수의 **3배로 움직이는 ETF**예요.

나스닥이 1% 오르면 TQQQ는 3% 오르고, 나스닥이 1% 내리면 TQQQ는 3% 내려요.

2022년에는 나스닥이 약 -33% 빠지면서 TQQQ는 **-81%** 까지 폭락했어요.
1,000만원이 190만원이 된 거예요.

> **"그런데 왜 이걸 사야 하죠?"**

---

## 🏔️ 나스닥은 항상 돌아왔어요

| 폭락 사건 | 낙폭 | 회복 기간 |
|-----------|------|-----------|
| 2000년 닷컴버블 | -83% | 약 15년 |
| 2008년 금융위기 | -54% | 약 4년 |
| 2020년 코로나 | -30% | 약 5개월 |
| 2022년 금리인상 | -33% | 약 2년 |

어떤 폭락도 결국 전고점을 회복했고, 그 이상으로 올라갔어요.

폭락장에서 TQQQ를 쌀 때 사두면, 회복할 때 **3배 레버리지 효과**로 수익이 극대화돼요.

---

## 🧠 그래서 이 전략의 핵심은

> **"폭락을 두려워하지 말고, 폭락할수록 더 많이 사라"**

하지만 폭락이 -80%까지 가는 동안 버티려면 **심리적으로, 자금적으로** 준비가 돼 있어야 해요.
현금 없이 TQQQ만 들고 있으면 -50% 구간에서 결국 패닉셀 하게 돼요.

---

## 🏗️ 자산 구조

이 전략은 시작부터 자산을 세 덩어리로 나눠요.
```
전체 자산 1,000만원 예시
├── TQQQ 즉시매수  700만원 (70%)  → 지금 바로 시작
├── 현금풀         300만원 (30%)  → 폭락 구간마다 분할 매수
└── 금고 (선택)    별도 금액      → -50% 이하 극단적 폭락 전용
```

**현금풀**은 폭락 구간별로 나눠서 투입해요. -5% 빠졌을 때 조금, -30% 빠졌을 때 더 많이.

**금고**는 -50% 이하의 극단적 폭락에서만 여는 비상금이에요. 2022년 같은 상황에서 가장 빛을 발해요.

---

## 📊 세 가지 전략 비교

**🔴 초반 집중형** — "조금만 빠져도 바로 산다"
- -5%부터 적극적으로 매수 시작
- 작은 조정장에서 빠르게 대응
- 단점: 대폭락 때 현금이 일찍 소진될 수 있음

**🟡 중반 집중형** — "균형 잡힌 분산" ← 초보자 추천
- -15% ~ -30% 구간에 집중 투입
- 대부분의 폭락 시나리오에서 안정적

**🟢 후반 집중형** — "크게 빠질 때까지 기다린다"
- -35% ~ -50% 구간에 집중 투입
- 2022년 같은 극단적 폭락에서 가장 강함
- 단점: 작은 조정장에선 현금을 거의 못 씀

---

## 🔄 자동 리밸런싱

전고점을 회복하면 자동으로 **TQQQ 70% / 현금 30%** 비율로 재조정해요.
폭락 때 싸게 산 주식을 고점에서 일부 매도 → 이익 실현, 다음 폭락 대비 현금 재충전.
이 사이클이 장기적으로 복리 효과를 만들어요.

---

## 📈 실제로 어떤 결과가 나왔을까?

아래에서 직접 시뮬레이션 해보세요. 2022년 역대급 폭락 구간 포함 백테스트가 가능해요.

---

> ⚠️ 이 전략은 **장기 투자 (최소 3~5년)** 관점에서 접근해야 해요.
> 단기 손실을 버틸 수 없다면 이 전략은 맞지 않아요.
> 투자 결정은 항상 본인 책임이에요.
    ''')

    st.divider()
    st.markdown('### 📬 투자 정보 & 업데이트 받기')
    st.caption('전략 업데이트, 시장 분석, 매수 타이밍 알림을 이메일로 받아보세요.')
    col_mail, col_btn = st.columns([3, 1])
    with col_mail:
        email = st.text_input('이메일 주소', placeholder='example@email.com', label_visibility='collapsed')
    with col_btn:
        if st.button('구독하기'):
            if '@' in email and '.' in email:
                st.success('✅ 구독 완료! 곧 소식을 전해드릴게요.')
            else:
                st.error('올바른 이메일 주소를 입력해주세요.')

    st.divider()
    st.markdown('''
    <div style="text-align: center; color: #888; font-size: 13px;">
        이 전략을 만들고 직접 운용 중인 창작자 →
        <a href="https://instagram.com/running_for_freedom1" target="_blank" style="color: #e1306c;">
            📸 @running_for_freedom1
        </a>
    </div>
    ''', unsafe_allow_html=True)

# ── STEP 1: 기본 설정 ──
with st.expander('① 기본 설정', expanded=st.session_state.step == 1):
    col1, col2 = st.columns(2)
    with col1:
        seed_krw = st.number_input('시드 금액 (원)', min_value=1000000, max_value=1000000000,
                                    value=10000000, step=1000000, format='%d')
        st.caption(f'입력값: {seed_krw:,}원')
    with col2:
        period = st.selectbox('백테스트 기간', [
            '2022~현재 (금리인상 폭락 포함)',
            '2020~현재 (코로나 포함)',
            '2019~현재 (전체)',
            '직접 입력'
        ])
        if period == '직접 입력':
            col_s, col_e = st.columns(2)
            with col_s:
                start_date = st.date_input('시작일', value=pd.Timestamp('2022-01-01'))
            with col_e:
                end_date = st.date_input('종료일', value=pd.Timestamp('today'))
            start_str = str(start_date); end_str = str(end_date)
        else:
            mapping = {
                '2022~현재 (금리인상 폭락 포함)': ('2022-01-01', None),
                '2020~현재 (코로나 포함)':        ('2020-01-01', None),
                '2019~현재 (전체)':               ('2019-01-01', None),
            }
            start_str, end_str = mapping[period]

    use_vault = st.checkbox('금고 사용 (극단적 폭락 대비 비상금)')
    if use_vault:
        col_v1, col_v2 = st.columns(2)
        with col_v1:
            vault_krw = st.number_input('금고 금액 (원)', min_value=100000,
                                         max_value=int(seed_krw*0.5), value=min(3000000, int(seed_krw*0.3)),
                                         step=100000, format='%d')
        with col_v2:
            vault_trigger = st.slider('금고 투입 시작 MDD (%)', min_value=30, max_value=70, value=50)
        st.caption(f'MDD -{vault_trigger}% 이하부터 {vault_krw:,}원을 6구간에 나눠 투입')
    else:
        vault_krw = 0; vault_trigger = 50

    if st.button('📊 백테스트 실행', type='primary'):
        with st.spinner('데이터 로딩 중... (최초 1회는 30초 정도 걸려요)'):
            try:
                tqqq, fx_series = load_data(start_str, end_str)
                fx_dict   = {str(d.date()): float(v) for d, v in zip(fx_series.index, fx_series.values)}
                fx_sorted = sorted(fx_dict.keys())
                start_fx  = get_fx(fx_dict, fx_sorted, str(tqqq.index[0].date()))
                seed_usd   = seed_krw / start_fx
                vault_usd  = vault_krw / start_fx if use_vault else 0

                results = {}; all_stats = {}
                for name, table in STRATEGIES.items():
                    h, s = run_backtest(table, tqqq, fx_dict, fx_sorted,
                                        seed_usd, use_vault, vault_usd, vault_trigger)
                    results[name] = h; all_stats[name] = s

                st.session_state.results      = results
                st.session_state.all_stats    = all_stats
                st.session_state.seed_krw     = seed_krw
                st.session_state.seed_usd     = seed_usd
                st.session_state.start_fx     = start_fx
                st.session_state.use_vault    = use_vault
                st.session_state.vault_krw    = vault_krw
                st.session_state.vault_trigger = vault_trigger
                st.session_state.fx_dict       = fx_dict
                st.session_state.tqqq         = tqqq
                st.session_state.step         = 2
                st.rerun()
            except Exception as e:
                st.error(f'오류 발생: {e}')

# ── STEP 2: 결과 비교 ──
if st.session_state.results and st.session_state.step >= 2:
    with st.expander('② 전략 비교 결과', expanded=st.session_state.step == 2):
        results   = st.session_state.results
        all_stats = st.session_state.all_stats
        seed_krw  = st.session_state.seed_krw

        seed_krw_val = st.session_state.seed_krw
        cols = st.columns(4)
        strategy_names = list(results.keys())
        for i, name in enumerate(strategy_names):
            h = results[name]
            final_krw   = h[-1]['total_krw']
            initial_krw = h[0]['total_krw']
            rate = (final_krw / initial_krw - 1) * 100
            years = len(h) / 252
            gain  = final_krw - initial_krw
            with cols[i]:
                st.metric(name, f'{final_krw:,.0f}원', f'{rate:+.1f}%')
                cagr = ((final_krw / initial_krw) ** (1/years) - 1) * 100 if years > 0 else 0
                st.caption(f'{seed_krw_val/10000:.0f}만원 → {final_krw/10000:.0f}만원 ({years:.1f}년) | 연평균 {cagr:.1f}%')
        with cols[3]:
            h = results[strategy_names[0]]
            hold_krw  = h[-1]['hold_krw']
            hold_rate = (hold_krw / h[0]['total_krw'] - 1) * 100
            years = len(h) / 252
            st.metric('단순 홀딩', f'{hold_krw:,.0f}원', f'{hold_rate:+.1f}%')
            hold_cagr = ((hold_krw / h[0]['total_krw']) ** (1/years) - 1) * 100 if years > 0 else 0
            st.caption(f'{seed_krw_val/10000:.0f}만원 → {hold_krw/10000:.0f}만원 ({years:.1f}년) | 연평균 {hold_cagr:.1f}%')

        # QQQ, VIX 데이터 로드
        import pandas as pd
        first = results[strategy_names[0]]
        dates_list = [h['date'] for h in first]
        start_dt = dates_list[0]
        end_dt   = dates_list[-1]

        @st.cache_data(show_spinner=False)
        def load_extra(start, end):
            import time
            for _ in range(3):
                try:
                    qqq = yf.download('QQQ', start=start, end=end, progress=False, auto_adjust=False)['Close'].dropna().squeeze()
                    vix = yf.download('^VIX', start=start, end=end, progress=False, auto_adjust=False)['Close'].dropna().squeeze()
                    return qqq, vix
                except:
                    time.sleep(2)
            return None, None

        qqq_data, vix_data = load_extra(start_dt, end_dt)

        # RSI 계산 함수
        def calc_rsi(series, period=14):
            delta = series.diff()
            gain  = delta.clip(lower=0).rolling(period).mean()
            loss  = (-delta.clip(upper=0)).rolling(period).mean()
            rs    = gain / loss
            return 100 - (100 / (1 + rs))

        fig, axes = plt.subplots(3, 1, figsize=(14, 14),
                                  gridspec_kw={'height_ratios': [4, 1.5, 1.5]})
        fig.patch.set_facecolor('#1a1a2e')
        ax = axes[0]
        ax_rsi = axes[1]
        ax_vix = axes[2]
        for a in axes:
            a.set_facecolor('#16213e')
            a.tick_params(colors='white')
            a.spines['bottom'].set_color('#444')
            a.spines['top'].set_color('#444')
            a.spines['left'].set_color('#444')
            a.spines['right'].set_color('#444')

        colors = {'초반 집중형': '#e74c3c', '중반 집중형': '#f39c12', '후반 집중형': '#2ecc71'}
        xticks_idx = list(range(0, len(dates_list), max(1, len(dates_list)//8)))

        for name, history in results.items():
            totals = [h['total_krw'] for h in history]
            rate   = (totals[-1] / totals[0] - 1) * 100
            ax.plot(range(len(dates_list)), totals,
                    label=f'{name}  {totals[-1]:,.0f}원 ({rate:+.1f}%)',
                    color=colors[name], linewidth=2.5)

            # 매수 시점 표시
            buy_log = st.session_state.results_stats[name]['buy_log'] if 'results_stats' in st.session_state else []
            buy_dates = [b['date'] for b in buy_log]
            buy_idx = [i for i, d in enumerate(dates_list) if d in buy_dates]
            buy_vals = [totals[i] for i in buy_idx]
            if buy_idx:
                ax.scatter(buy_idx, buy_vals, color=colors[name],
                           marker='^', s=30, alpha=0.6, zorder=5)

        hold = [h['hold_krw'] for h in first]
        hold_rate = (hold[-1] / hold[0] - 1) * 100
        ax.plot(range(len(dates_list)), hold,
                label=f'단순 홀딩  {hold[-1]:,.0f}원 ({hold_rate:+.1f}%)',
                color='#74b9ff', linewidth=2, linestyle='--', alpha=0.8)

        # QQQ 동일 시드 원화 기준으로 변환
        if qqq_data is not None and len(qqq_data) > 0:
            qqq_dates = [str(d.date()) for d in qqq_data.index]
            qqq_vals  = qqq_data.values
            # 첫날 QQQ 가격으로 시드 전액 매수한 것처럼 계산
            first_qqq_price = None
            first_fx = None
            for i, d in enumerate(dates_list):
                if d in qqq_dates:
                    idx = qqq_dates.index(d)
                    first_qqq_price = float(qqq_vals[idx])
                    first_fx = st.session_state.get('start_fx', 1350)
                    break
            if first_qqq_price:
                qqq_shares = (st.session_state.seed_krw / first_fx) / first_qqq_price
                qqq_idx, qqq_krw = [], []
                fx_dict_local = st.session_state.get('fx_dict', {})
                fx_sorted_local = sorted(fx_dict_local.keys())
                for i, d in enumerate(dates_list):
                    if d in qqq_dates:
                        idx = qqq_dates.index(d)
                        price = float(qqq_vals[idx])
                        fx = fx_dict_local.get(d, 1350)
                        if not fx and fx_sorted_local:
                            past = [x for x in fx_sorted_local if x <= d]
                            fx = fx_dict_local[past[-1]] if past else 1350
                        qqq_idx.append(i)
                        qqq_krw.append(qqq_shares * price * fx)
                if qqq_krw:
                    qqq_rate = (qqq_krw[-1] / qqq_krw[0] - 1) * 100
                    ax.plot(qqq_idx, qqq_krw, color='#a29bfe', linewidth=1.5,
                            linestyle=':', alpha=0.9,
                            label=f'QQQ 100% 홀딩  {qqq_krw[-1]:,.0f}원 ({qqq_rate:+.1f}%)')

        ax.set_xticks(xticks_idx)
        ax.set_xticklabels([dates_list[i][:7] for i in xticks_idx], rotation=45, color='white')
        ax.tick_params(colors='white')
        ax.set_ylabel('자산 (원)', color='white')
        # y축 한글 포맷
        def krw_fmt(x, pos):
            if x >= 1e8:
                return f'{x/1e8:.0f}억원'
            elif x >= 1e4:
                return f'{x/1e4:.0f}만원'
            return f'{x:.0f}원'
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(krw_fmt))
        ax.legend(facecolor='#0f3460', labelcolor='white', edgecolor='#444')

        # RSI 차트
        if qqq_data is not None and len(qqq_data) > 0:
            rsi = calc_rsi(qqq_data)
            rsi_dates = [str(d.date()) for d in rsi.index]
            rsi_idx, rsi_vals = [], []
            for i, d in enumerate(dates_list):
                if d in rsi_dates:
                    v = rsi.iloc[rsi_dates.index(d)]
                    if not pd.isna(v):
                        rsi_idx.append(i)
                        rsi_vals.append(v)
            if rsi_vals:
                ax_rsi.plot(rsi_idx, rsi_vals, color='#fdcb6e', linewidth=1.5)
                ax_rsi.axhline(70, color='#e17055', linestyle='--', alpha=0.7, linewidth=1)
                ax_rsi.axhline(30, color='#00b894', linestyle='--', alpha=0.7, linewidth=1)
                ax_rsi.fill_between(rsi_idx, rsi_vals, 30,
                                    where=[v < 30 for v in rsi_vals],
                                    color='#00b894', alpha=0.3)
                ax_rsi.fill_between(rsi_idx, rsi_vals, 70,
                                    where=[v > 70 for v in rsi_vals],
                                    color='#e17055', alpha=0.3)
                ax_rsi.set_xlim(0, len(dates_list)-1)
                ax_rsi.set_ylim(0, 100)
                ax_rsi.set_xticks(xticks_idx)
                ax_rsi.set_xticklabels([dates_list[i][:7] for i in xticks_idx], rotation=45, color='white')
                ax_rsi.set_ylabel('RSI (QQQ)', color='white')
                ax_rsi.text(0.01, 0.85, '과매수 (70)', transform=ax_rsi.transAxes,
                            color='#e17055', fontsize=8)
                ax_rsi.text(0.01, 0.05, '과매도 (30)', transform=ax_rsi.transAxes,
                            color='#00b894', fontsize=8)

        # VIX 차트
        if vix_data is not None and len(vix_data) > 0:
            vix_dates = [str(d.date()) for d in vix_data.index]
            vix_idx, vix_vals = [], []
            for i, d in enumerate(dates_list):
                if d in vix_dates:
                    v = vix_data.iloc[vix_dates.index(d)]
                    if not pd.isna(v):
                        vix_idx.append(i)
                        vix_vals.append(v)
            if vix_vals:
                ax_vix.plot(vix_idx, vix_vals, color='#fd79a8', linewidth=1.5)
                ax_vix.axhline(30, color='#e17055', linestyle='--', alpha=0.7, linewidth=1)
                ax_vix.fill_between(vix_idx, vix_vals, 30,
                                    where=[v > 30 for v in vix_vals],
                                    color='#e17055', alpha=0.3)
                ax_vix.set_xlim(0, len(dates_list)-1)
                ax_vix.set_xticks(xticks_idx)
                ax_vix.set_xticklabels([dates_list[i][:7] for i in xticks_idx], rotation=45, color='white')
                ax_vix.set_ylabel('VIX', color='white')
                ax_vix.text(0.01, 0.85, '공포 구간 (30+)', transform=ax_vix.transAxes,
                            color='#e17055', fontsize=8)
                ax_vix.text(0.99, 0.05, '⚠️ VIX는 S&P500 기반 공포지수로 참고용입니다',
                            transform=ax_vix.transAxes, color='#aaa', fontsize=8, ha='right')

        plt.tight_layout()
        ax.grid(True, alpha=0.2, color='white')
        for spine in ax.spines.values():
            spine.set_edgecolor('#444')
        plt.tight_layout()
        st.pyplot(fig)
        plt.close()

        st.subheader('전략별 상세')
        for name in strategy_names:
            h = results[name]; s = all_stats[name]
            worst_mdd = min(x['mdd'] for x in h)
            max_krw   = max(x['total_krw'] for x in h)
            min_krw   = min(x['total_krw'] for x in h)
            with st.expander(f'{name} 상세보기'):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric('최고 자산', f'{max_krw:,.0f}원')
                c2.metric('최저 자산', f'{min_krw:,.0f}원')
                c3.metric('TQQQ 최대 낙폭', f'{worst_mdd:.1f}%')
                c4.metric('총 거래 횟수', f'{s["total_tx"]}회')

                if s['buy_log']:
                    st.write('**최근 매수 내역**')
                    df = pd.DataFrame(s['buy_log'][-10:])
                    df = df[['date','mdd','level','shares','cost_krw','source']]
                    df.columns = ['날짜','낙폭(%)','매수구간(%)','매수주수','투입금액(원)','출처']
                    st.dataframe(df, use_container_width=True)
                    st.caption('💡 낙폭이 해당 구간에 도달할 때마다 현금풀 또는 금고에서 자동으로 매수한 내역이에요.')
                if s['rebalance_log']:
                    st.write('**최근 리밸런싱 내역**')
                    df = pd.DataFrame(s['rebalance_log'][-10:])
                    df.columns = ['날짜','TQQQ 가격($)','매도/매수','거래주수','거래후 보유주수']
                    st.dataframe(df, use_container_width=True)
                    st.caption('💡 전고점 회복 시 TQQQ 70% / 현금 30% 비율로 자동 재조정한 내역이에요. 폭락 때 산 주식을 고점에서 일부 매도해 이익을 실현하고 다음 폭락을 대비해요.')

        st.subheader('전략 선택')
        selected = st.radio('마음에 드는 전략을 선택하세요', strategy_names, horizontal=True)
        if st.button('이 전략으로 진행하기 →', type='primary'):
            st.session_state.selected_strategy = selected
            st.session_state.step = 3
            st.rerun()

# ── STEP 3: 내 현재 상황 ──
if st.session_state.selected_strategy and st.session_state.step >= 3:
    with st.expander('③ 내 현재 상황 입력', expanded=st.session_state.step == 3):
        st.write(f'선택한 전략: **{st.session_state.selected_strategy}**')

        col1, col2, col3 = st.columns(3)
        with col1:
            my_shares = st.number_input('현재 보유 주수', min_value=0, value=0, step=1)
        with col2:
            my_avg    = st.number_input('평균 매수단가 ($)', min_value=0.0, value=0.0, step=0.01)
        with col3:
            my_cash   = st.number_input('남은 현금 (원)', min_value=0, value=0, step=100000, format='%d')

        if st.button('현재 상황 분석'):
            tqqq      = st.session_state.tqqq
            cur_price = float(tqqq.iloc[-1])
            cur_fx    = list(st.session_state.results.values())[0][-1]['fx']
            cur_mdd   = list(st.session_state.results.values())[0][-1]['mdd']

            st.subheader('📊 현재 상황 분석')
            c1, c2, c3 = st.columns(3)
            c1.metric('현재 TQQQ 가격', f'${cur_price:.2f}')
            c2.metric('현재 MDD', f'{cur_mdd:.1f}%')
            c3.metric('현재 환율', f'{cur_fx:,.0f}원')

            if my_shares > 0 and my_avg > 0:
                my_tqqq_value_krw = my_shares * cur_price * cur_fx
                my_total_krw      = my_tqqq_value_krw + my_cash
                my_profit_rate    = (cur_price / my_avg - 1) * 100
                st.metric('내 TQQQ 평가금액', f'{my_tqqq_value_krw:,.0f}원', f'{my_profit_rate:+.1f}%')
                st.metric('내 총 자산 (추정)', f'{my_total_krw:,.0f}원')

            st.subheader('📍 다음 매수 구간 안내')
            strategy_table = STRATEGIES[st.session_state.selected_strategy]
            next_levels = [(level, ratio) for level, ratio in strategy_table if level > cur_mdd]
            triggered   = [(level, ratio) for level, ratio in strategy_table if level <= cur_mdd]

            if next_levels:
                next_level = max(next_levels, key=lambda x: x[0])
                st.info(f'현재 MDD {cur_mdd:.1f}% → 다음 매수 구간: **{next_level[0]}%** (현금풀의 {next_level[1]*100:.0f}% 투입)')
            if triggered:
                st.success(f'이미 진입한 구간: {[l for l,r in triggered]}')

            st.session_state.step = 4
