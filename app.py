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
    '초반 집중형': [(-5,0.05),(-10,0.18),(-15,0.18),(-20,0.14),(-25,0.12),(-30,0.08),(-35,0.07),(-40,0.06),(-45,0.06),(-50,0.06)],
    '중반 집중형': [(-5,0.02),(-10,0.03),(-15,0.12),(-20,0.20),(-25,0.18),(-30,0.15),(-35,0.13),(-40,0.07),(-45,0.06),(-50,0.04)],
    '후반 집중형': [(-5,0.01),(-10,0.01),(-15,0.01),(-20,0.02),(-25,0.08),(-30,0.16),(-35,0.20),(-40,0.22),(-45,0.15),(-50,0.14)]
}

def make_vault_table(trigger):
    levels = [-(trigger + i*5) for i in range(6)]
    return list(zip(levels, [0.20,0.20,0.20,0.20,0.10,0.10]))

TQQQ_IPO = '2010-02-11'
DAILY_EXPENSE = 0.0098 / 252

@st.cache_data(show_spinner=False)
def load_data(start, end):
    import time
    import pandas as pd
    for attempt in range(3):
        try:
            use_synthetic = start < TQQQ_IPO
            tqqq_start = TQQQ_IPO if use_synthetic else start
            raw  = yf.download('TQQQ', start=tqqq_start, end=end, progress=False, auto_adjust=False)
            fx   = yf.download('USDKRW=X', start=start, end=end, progress=False, auto_adjust=False)
            if 'Close' in raw.columns:
                tqqq = raw['Close'].dropna().squeeze()
            else:
                tqqq = raw.iloc[:, 0].dropna().squeeze()
            if 'Open' in raw.columns:
                tqqq_open = raw['Open'].reindex(tqqq.index).ffill().squeeze()
            else:
                tqqq_open = tqqq.copy()
            if 'Close' in fx.columns:
                fx = fx['Close'].dropna().squeeze()
            else:
                fx = fx.iloc[:, 0].dropna().squeeze()
            # 합성 TQQQ 생성 (상장 이전 구간)
            if use_synthetic:
                qqq_raw = yf.download('QQQ', start=start, end=TQQQ_IPO, progress=False, auto_adjust=False)
                if len(qqq_raw) > 0:
                    qqq_c = qqq_raw['Close'].dropna().squeeze()
                    qqq_o = qqq_raw['Open'].dropna().squeeze()
                    # 일간 수익률 × 3배 - 운용보수
                    qqq_ret = qqq_c.pct_change().fillna(0)
                    # TQQQ 첫날 가격 기준 역산
                    first_price = float(tqqq.iloc[0])
                    synth = [first_price]
                    for r in reversed((qqq_ret * 3 - DAILY_EXPENSE).values[1:]):
                        synth.insert(0, synth[0] / (1 + r) if (1 + r) != 0 else synth[0])
                    tqqq_synth = pd.Series(synth, index=qqq_c.index)
                    # 시가 합성
                    qqq_o_ret = qqq_o.pct_change().fillna(0)
                    first_open = float(tqqq_open.iloc[0])
                    synth_o = [first_open]
                    for r in reversed((qqq_o_ret * 3 - DAILY_EXPENSE).values[1:]):
                        synth_o.insert(0, synth_o[0] / (1 + r) if (1 + r) != 0 else synth_o[0])
                    tqqq_open_synth = pd.Series(synth_o, index=qqq_o.index)
                    # 연결
                    tqqq = pd.concat([tqqq_synth, tqqq])
                    tqqq_open = pd.concat([tqqq_open_synth, tqqq_open])

            if len(tqqq) > 0 and len(fx) > 0:
                return tqqq, fx, tqqq_open
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

def run_backtest(buy_table, tqqq, fx_dict, fx_sorted, seed_usd, use_vault, vault_usd, vault_trigger, use_next_open=False, tqqq_open=None, use_dca=False, dca_amount_usd=0.0, dca_day=1):
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
    total_seed_usd = seed_usd + vault_usd  # 단순홀딩은 시드+금고 합산으로 공정 비교
    hold_shares = math.floor(total_seed_usd / prices[0])
    history = []; buy_log = []; rebalance_log = []
    buy_count = 0; vault_buy_count = 0; rebalance_count = 0

    opens = tqqq_open.tolist() if tqqq_open is not None else prices

    for i, (date, price) in enumerate(zip(dates, prices)):
        date_str = str(date.date())
        fx = get_fx(fx_dict, fx_sorted, date_str)
        # 매수 체결가: 다음날 시가 or 당일 종가
        if use_next_open and tqqq_open is not None and i + 1 < len(opens):
            buy_price = opens[i + 1]  # 다음날 시가
        else:
            buy_price = price  # 당일 종가

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
                buy_shares = math.floor(invest / buy_price)
                actual_cost = buy_shares * buy_price
                if buy_shares >= 1 and cash >= actual_cost:
                    tqqq_shares += buy_shares; cash -= actual_cost; buy_count += 1
                    buy_log.append({'date': date_str, 'price': round(buy_price,2),
                        'mdd': round(mdd,2), 'level': level, 'shares': buy_shares,
                        'shares_total': tqqq_shares,
                        'cost_krw': round(actual_cost*fx,0), 'source': '현금풀',
                        'cash_after': round(cash,2), 'vault_after': round(vault,2)})
                bought_levels.add(level)

        if use_vault and vault > 0:
            for level, ratio in vault_table:
                if mdd <= level and level not in vault_levels:
                    invest = total_vault * ratio
                    buy_shares = math.floor(invest / buy_price)
                    actual_cost = buy_shares * buy_price
                    if buy_shares >= 1 and vault >= actual_cost:
                        tqqq_shares += buy_shares; vault -= actual_cost; vault_buy_count += 1
                        buy_log.append({'date': date_str, 'price': round(buy_price,2),
                            'mdd': round(mdd,2), 'level': level, 'shares': buy_shares,
                            'shares_total': tqqq_shares,
                            'cost_krw': round(actual_cost*fx,0), 'source': '금고',
                            'cash_after': round(cash,2), 'vault_after': round(vault,2)})
                    vault_levels.add(level)

        # DCA 적립식 매수
        if use_dca and dca_amount_usd > 0:
            if date_str[8:10] == f'{dca_day:02d}':
                buy_shares = math.floor(dca_amount_usd / buy_price)
                actual_cost = buy_shares * buy_price
                if buy_shares >= 1:
                    tqqq_shares += buy_shares; buy_count += 1
                    buy_log.append({'date': date_str, 'price': round(buy_price,2),
                        'mdd': round(mdd,2), 'level': 0, 'shares': buy_shares,
                        'shares_total': tqqq_shares,
                        'cost_krw': round(actual_cost*fx,0), 'source': 'DCA',
                        'cash_after': round(cash,2), 'vault_after': round(vault,2)})

        total_usd = cash + tqqq_shares * price + vault
        history.append({
            'date': date_str, 'price': round(price,2), 'mdd': round(mdd,2),
            'tqqq_shares': tqqq_shares,
            'total_usd': round(total_usd,2), 'total_krw': round(total_usd*fx,0),
            'hold_usd': round(hold_shares*price,2), 'hold_krw': round(hold_shares*price*fx,0),
            'fx': round(fx,2),
            'cash_usd': round(cash,2), 'vault_usd': round(vault,2)
        })

    stats = {'buy_count': buy_count, 'vault_buy_count': vault_buy_count,
             'rebalance_count': rebalance_count,
             'total_tx': buy_count+vault_buy_count+rebalance_count,
             'buy_log': buy_log, 'rebalance_log': rebalance_log}
    return history, stats

# ── UI 시작 ──────────────────────────────────────────

# 다크모드 토글
if 'dark_mode' not in st.session_state:
    st.session_state.dark_mode = False

col_title, col_dark = st.columns([8, 1])
with col_title:
    st.title('📈 MDD 방어법 백테스터')
with col_dark:
    st.session_state.dark_mode = st.toggle('🌙', value=st.session_state.dark_mode)

if st.session_state.dark_mode:
    st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #fafafa; }
    .stMarkdown, .stText, p, h1, h2, h3, h4, h5, h6, li { color: #fafafa !important; }
    .stExpander { background-color: #1a1f2e; border: 1px solid #333; }
    .stDataFrame { background-color: #1a1f2e; }
    .stMetric { background-color: #1a1f2e; padding: 8px; border-radius: 8px; }
    .stSelectbox > div, .stNumberInput > div { background-color: #1a1f2e; }
    div[data-testid="stExpander"] { background-color: #1a1f2e; }
    </style>
    """, unsafe_allow_html=True)
st.caption('TQQQ 폭락 구간 분할매수 전략 시뮬레이터')

if 'step' not in st.session_state:
    st.session_state.step = 1
if 'results' not in st.session_state:
    st.session_state.results = None
if 'selected_strategy' not in st.session_state:
    st.session_state.selected_strategy = None

# ── 전략 소개 ──
with st.expander('💡 이 전략이 뭔가요? (처음이시면 꼭 읽어보세요)', expanded=False):
    st.markdown("""
## TQQQ Adaptive Defense Strategy
*나스닥 3배 레버리지 ETF의 구조적 하락을 기회로 전환하는 동적 자산배분 모델*

---

### 들어가며

주식 시장에서 장기투자가 실패하는 이유는 대부분 수익률이 아니라 심리에 있다.
2002년 노벨경제학상을 수상한 대니얼 카너먼은 인간이 동일한 크기의 이익보다 손실을 약 2.5배 더 고통스럽게 인식한다는 것을 실증했다.
이 비대칭적 고통이 하락장에서의 패닉셀을 유발하고, 장기복리의 기회를 스스로 끊어낸다.

이 전략은 그 관찰에서 출발했다. 어떻게 하면 인간의 손실 회피 본능을 시스템으로 대체할 수 있을까.
감정이 아닌 구조로 하락장을 버티고, 오히려 기회로 전환할 수 있을까.

---

### 왜 나스닥인가

미국 기술주 중심의 나스닥 100은 단순한 주가지수가 아니다. 현재 글로벌 경제의 인프라를 구성하는 기업들의 집합체다.
애플의 생태계, 엔비디아의 AI 반도체, 마이크로소프트의 클라우드가 무너지지 않는 한 이 지수는 우상향한다는 것이 본 전략의 대전제다.

역설적으로, 만약 나스닥이 장기 우상향하지 못한다면 다른 어떤 자산도 안전하지 않다.
고금리 장기화, 반독점 규제, 지정학적 리스크 등이 나스닥의 밸류에이션을 압박할 수 있다.
본 전략은 그 리스크를 부정하지 않는다. 다만 확률적으로 우상향에 베팅하되,
하락 시 시스템이 자동으로 대응하도록 설계함으로써 불확실성을 관리한다.

---

### 왜 3배 레버리지인가

현대 시장은 두 가지 구조적 변화를 겪고 있다.

하나는 **알고리즘 매매의 확산**이다. 특정 지지선이 붕괴될 때 기계적 손절 물량이 연쇄적으로 출회되면서
하락의 기울기가 과거보다 가팔라졌다. 2020년 코로나 폭락이 단 33일 만에 -34%를 기록한 것은 우연이 아니다.

다른 하나는 **정책적 유동성의 비대칭성**이다. 각국 중앙은행은 위기 시 즉각적인 유동성 공급으로 대응하는
이른바 'Fed Put' 구조를 사실상 제도화했다. 그 결과 하락은 가팔라졌고, 반등은 빨라졌다.

| 폭락 사건 | 최대 낙폭 | 회복 기간 |
|:---|:---:|:---:|
| 2000년 닷컴버블 | -83% | 약 15년 |
| 2008년 금융위기 | -54% | 약 4년 |
| 2020년 코로나 | -30% | 약 5개월 |
| 2022년 긴축 충격 | -33% | 약 2년 |

회복 속도는 빨라지고 있다. 저점에서 매집한 TQQQ는 지수가 단순히 제자리로 돌아오는 것만으로도
기하급수적인 회복력을 발휘한다.

---

### 레버리지의 수학 : 양날의 검

TQQQ를 이해하려면 레버리지 복리의 수학적 구조를 먼저 알아야 한다.
지수가 하루 10% 오른 뒤 다음 날 약 9.1% 하락해 제자리로 돌아왔다고 가정하자.
```
1일차: 100 → 130 (+30%)
2일차: 130 → 94.5 (-27.3%)
결과: -5.5%  ← 지수는 본전인데 TQQQ는 손실
```

이것이 **변동성 잠식(Volatility Drag)**이다. 수식으로 표현하면 다음과 같다.
```
Drag ≈ ½ × L² × σ²
```

L은 레버리지 배수, σ²는 변동성(분산)이다.
TQQQ처럼 L=3이면 L²=9가 되어, 1배 ETF보다 변동성에 의한 손실이 **9배 증폭**된다.
시장이 방향 없이 위아래로 진동할수록 계좌는 조용히 마모된다.

반면 시장이 한 방향으로 꾸준히 오를 때는 반대 현상이 일어난다.
```
3일 연속 +3% 상승 시
단순 3배 계산: +9.09%
실제 TQQQ:   +9.27%  ← 3배를 초과하는 수익 발생
```

레버리지는 횡보장에서는 독이고, 추세장에서는 가속기다. 본 전략은 이 비대칭성을 이용한다.

---

### 전략의 핵심 : 하락을 버티는 것이 아니라 설계하는 것

레버리지 ETF의 가장 큰 적은 하락이 아니라 횡보다.
본 전략은 현금풀과 금고라는 두 개의 예비 자본 레이어를 설계해,
MDD가 깊어질수록 오히려 매수 여력이 활성화되도록 구조화했다.

MDD -5% 구간부터 -50% 구간까지 10단계로 분할 매수가 자동 집행되며,
-50%를 초과하는 극단적 폭락 구간에서는 별도로 적립된 금고 자산이 추가 투입된다.
**하락은 리스크가 아니라 시스템이 작동하는 트리거다.**

전고점 회복 시 TQQQ 70% / 현금 30% 비율로 자동 리밸런싱이 집행된다.
폭락 구간에서 낮은 단가로 매집한 물량을 고점 회복 시 일부 현금화함으로써, 다음 폭락을 위한 실탄을 재확보한다.

---

### 환율 반영 방법론

본 모델은 단순 달러 기준 수익률이 아닌, 매 거래일의 실제 USD/KRW 환율을 적용한 원화 기준 실질 수익률을 산출한다.
한국인 투자자에게 TQQQ의 실질 손익은 주가 변동과 환율 변동의 합산이다.
달러 강세 구간에서는 추가 수익이, 달러 약세 구간에서는 수익이 압축되는 효과가 모든 거래일에 자동으로 반영된다.

---

### 백테스트 방법론 및 데이터 출처

본 시뮬레이션은 yfinance를 통해 수집한 수정주가(Adjusted Price) 기반 일별 데이터를 사용한다.
수정주가는 배당 및 액면분할을 소급 반영하여 장기 수익률 왜곡을 최소화한다.

다음 항목은 현재 모델에 반영되지 않았으며 실제 투자 성과와 괴리가 발생할 수 있다.
거래 수수료 및 세금, 슬리피지(체결 가격 오차), 환전 비용, TQQQ 운용보수(연 0.98%).
본 백테스터는 전략의 논리적 타당성을 검증하기 위한 이론적 시뮬레이션이며,
**과거 성과가 미래 수익을 보장하지 않는다.**

---

### 전략의 한계

본 전략이 가장 취약한 시나리오는 두 가지다.

**첫째**, 2000년 닷컴버블과 같은 구조적 장기 침체다.
나스닥이 -83% 하락한 뒤 15년간 전고점을 회복하지 못하는 구간에서는
현금풀과 금고 자산이 순차적으로 소진되며 이후 대응 여력이 사라진다.

**둘째**, 횡보 장기화다. V자 반등 없이 수년간 박스권이 지속될 경우
변동성 잠식이 누적되며 레버리지 원금이 지속적으로 감소한다.
이 구간에서 본 전략은 단순 홀딩 대비 열위에 놓일 수 있다.

이 한계를 인지하는 것이 전략을 올바르게 운용하는 전제 조건이다.

---

### 만든 사람

개인 투자에 대한 관심으로 시작해 여러 차례의 투자 실패를 경험했다.
그 경험이 금융에 대한 체계적 이해의 필요성을 깨닫게 했고,
금융투자분석사, 투자자산운용사, 신용분석사 자격증 취득으로 이어졌다.
이 사이트는 그 과정에서 직접 설계하고 검증한 전략을 구현한 결과물이며, 향후 포트폴리오로 활용될 예정이다.

📎 [@running\_for\_freedom1](https://www.instagram.com/running_for_freedom1)
""")


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
            '2010~현재 (TQQQ 상장 이후 전체)',
            '2000~현재 (닷컴버블 포함 ⚠️합성)',
            '2000~2010 (닷컴+금융위기 ⚠️합성)',
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
                '2022~현재 (금리인상 폭락 포함)':           ('2022-01-01', None),
                '2020~현재 (코로나 포함)':                  ('2020-01-01', None),
                '2019~현재 (전체)':                        ('2019-01-01', None),
                '2010~현재 (TQQQ 상장 이후 전체)':          ('2010-02-11', None),
                '2000~현재 (닷컴버블 포함 ⚠️합성)':         ('2000-01-01', None),
                '2000~2010 (닷컴+금융위기 ⚠️합성)':         ('2000-01-01', '2010-02-11'),
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

    use_next_open = st.checkbox("📅 다음날 시가 매수 (현실적 체결가)", value=False, help="MDD 도달 당일 종가 대신 다음날 시가로 체결. 실전과 더 유사합니다.")
    use_dca = st.checkbox("📅 적립식 추매 (DCA) - 매월 고정 금액 자동 매수", value=False)
    dca_amount_krw = 0
    dca_day = 1
    if use_dca:
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            dca_amount_krw = st.number_input("월 적립 금액 (원)", min_value=10000, value=100000, step=10000, format="%d")
        with col_d2:
            dca_day = st.slider("매월 몇 일에 매수?", min_value=1, max_value=28, value=1)
        st.caption(f"매월 {dca_day}일에 {dca_amount_krw:,}원씩 자동 매수")
    if st.button("📊 백테스트 실행", type="primary"):
        with st.spinner('데이터 로딩 중... (최초 1회는 30초 정도 걸려요)'):
            try:
                tqqq, fx_series, tqqq_open = load_data(start_str, end_str)
                fx_dict   = {str(d.date()): float(v) for d, v in zip(fx_series.index, fx_series.values)}
                fx_sorted = sorted(fx_dict.keys())
                start_fx  = get_fx(fx_dict, fx_sorted, str(tqqq.index[0].date()))
                seed_usd   = seed_krw / start_fx
                vault_usd  = vault_krw / start_fx if use_vault else 0

                results = {}; all_stats = {}
                for name, table in STRATEGIES.items():
                    h, s = run_backtest(table, tqqq, fx_dict, fx_sorted,
                                        seed_usd, use_vault, vault_usd, vault_trigger,
                                        use_next_open=use_next_open, tqqq_open=tqqq_open,
                                        use_dca=use_dca, dca_amount_usd=dca_amount_krw/start_fx, dca_day=dca_day)
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
            return None, None, None

        qqq_data, vix_data = load_extra(start_dt, end_dt)

        # RSI 계산 함수
        def calc_rsi(series, period=14):
            delta = series.diff()
            gain  = delta.clip(lower=0).rolling(period).mean()
            loss  = (-delta.clip(upper=0)).rolling(period).mean()
            rs    = gain / loss
            return 100 - (100 / (1 + rs))

        fig, axes = plt.subplots(3, 1, figsize=(12, 8),
                                  gridspec_kw={'height_ratios': [3.5, 1.0, 1.0],
                                               'hspace': 0.05})
        fig.patch.set_facecolor('#1a1a2e')
        ax     = axes[0]   # 메인: 수익률
        ax_rsi = axes[1]   # RSI
        ax_vix = axes[2]   # VIX
        for a in axes:
            a.set_facecolor('#16213e')
            a.tick_params(colors='white', labelsize=7)
            a.spines['bottom'].set_color('#444')
            a.spines['top'].set_color('#444')
            a.spines['left'].set_color('#444')
            a.spines['right'].set_color('#444')
        ax.xaxis.set_visible(False)
        ax_rsi.xaxis.set_visible(False)

        colors = {'초반 집중형': '#e74c3c', '중반 집중형': '#f39c12', '후반 집중형': '#2ecc71'}
        xticks_idx = list(range(0, len(dates_list), max(1, len(dates_list)//8)))

        for name, history in results.items():
            totals = [h['total_krw'] for h in history]
            rate   = (totals[-1] / totals[0] - 1) * 100
            ax.plot(range(len(dates_list)), totals,
                    label=f'{name}  {totals[-1]:,.0f}원 ({rate:+.1f}%)',
                    color=colors[name], linewidth=1.0)

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
                label=f'TQQQ 100% 단순홀딩  {hold[-1]:,.0f}원 ({hold_rate:+.1f}%)',
                color='#74b9ff', linewidth=1.0, linestyle='-', alpha=0.9)

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
                total_krw_for_qqq = st.session_state.seed_krw + st.session_state.get('vault_krw', 0)
                qqq_shares = (total_krw_for_qqq / first_fx) / first_qqq_price
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
                    ax.plot(qqq_idx, qqq_krw, color='#6c5ce7', linewidth=1.0,
                            linestyle='-', alpha=0.9,
                            label=f'QQQ 100% 단순홀딩  {qqq_krw[-1]:,.0f}원 ({qqq_rate:+.1f}%)')

        # QQQ 패널 제거 (메인 차트에 통합)

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
                ax_rsi.plot(rsi_idx, rsi_vals, color='#fdcb6e', linewidth=1.0)
                ax_rsi.axhline(70, color='#e17055', linestyle='-', alpha=0.7, linewidth=1)
                ax_rsi.axhline(30, color='#00b894', linestyle='-', alpha=0.7, linewidth=1)
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
                ax_vix.plot(vix_idx, vix_vals, color='#fd79a8', linewidth=1.0)
                ax_vix.axhline(30, color='#e17055', linestyle='-', alpha=0.7, linewidth=1)
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
        plt.close("all")

        # 합성 데이터 경고
        if start_str < TQQQ_IPO:
            st.warning('⚠️ 선택한 기간에 TQQQ 상장일(2010-02-11) 이전이 포함되어 있습니다. 해당 구간은 QQQ 일간수익률 × 3배로 합성한 데이터이며 실제 TQQQ와 괴리가 있을 수 있습니다.')

        # 1. 전략별 상세 요약 카드
        st.subheader('📊 전략별 상세')
        for name in strategy_names:
            h = results[name]; s = all_stats[name]
            worst_mdd = min(x['mdd'] for x in h)
            max_krw   = max(x['total_krw'] for x in h)
            final_krw = h[-1]['total_krw']
            init_krw  = h[0]['total_krw']
            years     = len(h) / 252
            cagr      = ((final_krw / init_krw) ** (1/years) - 1) * 100 if years > 0 else 0

            with st.expander(f'{name}  |  최종 {final_krw/10000:.0f}만원  |  연평균 {cagr:.1f}%'):
                # 요약 카드
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric('최종 자산', f'{final_krw/10000:.0f}만원', f'{(final_krw/init_krw-1)*100:+.1f}%')
                c2.metric('연평균 수익률', f'{cagr:.1f}%')
                c3.metric('TQQQ 최대 낙폭', f'{worst_mdd:.1f}%')
                total_tx = s["buy_count"] + s["vault_buy_count"] + s["rebalance_count"]
                recovery_factor = (final_krw / init_krw - 1) / abs(worst_mdd) if worst_mdd != 0 else 0
                c4.metric('Recovery Factor', f'{recovery_factor:.2f}x')
                c5.metric('총 거래 횟수', f'{total_tx}회')
                st.caption(f'매수 {s["buy_count"] + s["vault_buy_count"]}회 (현금풀 {s["buy_count"]}회 · 금고 {s["vault_buy_count"]}회)　　리밸런싱(매도) {s["rebalance_count"]}회')

                # 2. 통합 거래 내역 표
                st.write('**📋 거래 내역 (매수 🟢 / 리밸런싱 🔵)**')
                unified_log = []
                # 매수 내역
                hist_dict = {h['date']: h for h in results[name]}
                for b in s['buy_log']:
                    h_match = hist_dict.get(b['date'])
                    fx_val = h_match['fx'] if h_match else 1350
                    shares_after = b.get('shares_total', h_match['tqqq_shares'] if h_match else '-')
                    price_day = h_match['price'] if h_match else b['price']
                    eval_krw = round(shares_after * price_day * fx_val / 10000) if isinstance(shares_after, (int, float)) else '-'
                    cash_remain = round(b.get('cash_after', 0) * fx_val / 10000) if 'cash_after' in b else '-'
                    vault_remain = round(b.get('vault_after', 0) * fx_val / 10000) if 'vault_after' in b else '-'
                    unified_log.append({
                        '_type': 'buy',
                        '날짜': b['date'],
'이벤트': f"{'🟡' if b['source'] == 'DCA' else '🟢'} {b['shares']}주 매수 ({b['level']}% / {b['source']})",                        'TQQQ가격': f"${price_day:.2f}",
                        'MDD': f"{b['mdd']:.1f}%",
                        '보유주수': f"{shares_after:.1f}주" if isinstance(shares_after, (int, float)) else '-',
                        '평가금액': f'{int(eval_krw)*10000:,}원' if isinstance(eval_krw, (int,float)) else '-',
                        '현금풀': f'{int(cash_remain)*10000:,}원' if isinstance(cash_remain, (int,float)) else '-',
                        '금고': f'{int(vault_remain)*10000:,}원' if isinstance(vault_remain, (int,float)) else '-',
                    })
                # 리밸런싱 내역
                for r in s['rebalance_log']:
                    h_match = hist_dict.get(r['date'])
                    fx_val = h_match['fx'] if h_match else 1350
                    shares_after = h_match['tqqq_shares'] if h_match else '-'
                    price_day = h_match['price'] if h_match else r['price']
                    eval_krw = round(shares_after * price_day * fx_val / 10000) if isinstance(shares_after, (int, float)) else '-'
                    cash_usd_val = h_match.get('cash_usd', 0) if h_match else 0
                    vault_usd_val = h_match.get('vault_usd', 0) if h_match else 0
                    cash_remain = round(cash_usd_val * fx_val / 10000)
                    vault_remain = round(vault_usd_val * fx_val / 10000)
                    unified_log.append({
                        '_type': 'rebalance',
                        '날짜': r['date'],
                        '이벤트': f"🔵 전고점 회복 · 리밸런싱 ({r['shares_diff']}주 {r['action']})",
                        'TQQQ가격': f"${price_day:.2f}",
                        'MDD': '-',
                        '보유주수': f"{shares_after:.1f}주" if isinstance(shares_after, (int, float)) else '-',
                        '평가금액': f'{int(eval_krw)*10000:,}원' if isinstance(eval_krw, (int,float)) else '-',
                        '현금풀': f'{int(cash_remain)*10000:,}원' if isinstance(cash_remain, (int,float)) else '-',
                        '금고': f'{int(vault_remain)*10000:,}원' if isinstance(vault_remain, (int,float)) else '-',
                    })

                if unified_log:
                    unified_log.sort(key=lambda x: x['날짜'])
                    df_unified = pd.DataFrame(unified_log).drop(columns=['_type'])

                    def highlight_row(row):
                        if '🟢' in str(row['이벤트']):
                            return ['background-color: rgba(46,204,113,0.15)'] * len(row)
                        elif '🔵' in str(row['이벤트']):
                            return ['background-color: rgba(52,152,219,0.15)'] * len(row)
                        return [''] * len(row)

                    # 금고 미사용 시 컬럼 숨기기
                    if not use_vault or s['vault_buy_count'] == 0:
                        df_unified = df_unified.drop(columns=['금고'], errors='ignore')
                    styled = df_unified.style.apply(highlight_row, axis=1)
                    row_h = 35
                    table_h = min(600, max(200, len(unified_log) * row_h + 40))
                    st.dataframe(styled, use_container_width=True, hide_index=True, height=table_h)



        # 3. 연도별 수익률 표 색상 강조
        st.subheader('📅 연도별 수익률')
        years_set = sorted(set([h['date'][:4] for h in first]))
        year_data = []
        for year in years_set:
            row = {'연도': year}
            for name, history in results.items():
                year_hist = [h for h in history if h['date'][:4] == year]
                if year_hist:
                    s_val = year_hist[0]['total_krw']
                    e_val = year_hist[-1]['total_krw']
                    row[name] = (e_val / s_val - 1) * 100
                else:
                    row[name] = None
            hold_year = [h for h in first if h['date'][:4] == year]
            if hold_year:
                row['단순홀딩'] = (hold_year[-1]['hold_krw'] / hold_year[0]['hold_krw'] - 1) * 100
            year_data.append(row)

        year_df = pd.DataFrame(year_data)

        def color_rate(val):
            if val is None: return ''
            color = 'rgba(46,204,113,0.3)' if val >= 0 else 'rgba(231,76,60,0.3)'
            return f'background-color: {color}'

        def fmt_rate(val):
            if val is None: return '-'
            return f'{val:+.1f}%'

        numeric_cols = [c for c in year_df.columns if c != '연도']
        styled = year_df.style            .applymap(color_rate, subset=numeric_cols)            .format(fmt_rate, subset=numeric_cols)
        st.dataframe(styled, use_container_width=True, hide_index=True)
        st.caption('💡 초록: 수익 / 빨강: 손실 | 해당 연도 첫 거래일 대비 마지막 거래일 기준')

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
            next_levels = [(level, ratio) for level, ratio in strategy_table if level < cur_mdd]
            triggered   = [(level, ratio) for level, ratio in strategy_table if level >= cur_mdd]

            # 현금풀 = 입력한 남은 현금 (my_cash)
            cash_pool = my_cash if my_cash > 0 else 0

            # 다음 매수 구간
            if next_levels:
                next_level = max(next_levels, key=lambda x: x[0])
                invest_krw = cash_pool * next_level[1]
                invest_usd = invest_krw / cur_fx if cur_fx > 0 else 0
                shares_to_buy = invest_usd / cur_price if cur_price > 0 else 0
                st.info(
                    f'현재 MDD **{cur_mdd:.1f}%** → 다음 매수 구간: **{next_level[0]}%** 진입 시\n\n'
                    f'- 투입 비율: 현금풀의 **{next_level[1]*100:.0f}%**\n'
                    f'- 투입 금액: **{invest_krw:,.0f}원** (${invest_usd:,.0f})\n'
                    f'- 매수 주수: 약 **{shares_to_buy:.2f}주** (현재가 ${cur_price:.2f} 기준)'
                )

            # 이미 지나친 구간 상세
            if triggered:
                st.subheader('📋 이미 지나친 구간별 매수 안내 (소급)')
                import pandas as pd
                rows = []
                total_invest_krw = 0
                total_shares = 0
                for level, ratio in sorted(triggered, reverse=True):
                    invest_krw = cash_pool * ratio
                    invest_usd = invest_krw / cur_fx if cur_fx > 0 else 0
                    shares = invest_usd / cur_price if cur_price > 0 else 0
                    total_invest_krw += invest_krw
                    total_shares += shares
                    rows.append({
                        'MDD 구간': f'{level}%',
                        '투입 비율': f'{ratio*100:.0f}%',
                        '투입 금액 (원)': f'{invest_krw:,.0f}',
                        '매수 주수 (주)': f'{shares:.2f}'
                    })
                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.warning(
                    f'💡 위 구간을 모두 매수했다면\n\n'
                    f'- 총 투입 금액: **{total_invest_krw:,.0f}원**\n'
                    f'- 총 매수 주수: 약 **{total_shares:.2f}주**\n'
                    f'- 현재가 기준 평가금액: **{total_shares * cur_price * cur_fx:,.0f}원**'
                )

            st.session_state.step = 4
