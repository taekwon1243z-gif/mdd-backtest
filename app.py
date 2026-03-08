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
    import platform
    if platform.system() == 'Windows':
        plt.rcParams['font.family'] = 'Malgun Gothic'
        return
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

from backtest_engine import get_fx, make_vault_table, run_backtest

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
            raw = yf.download('TQQQ', start=tqqq_start, end=end, progress=False, auto_adjust=False)
            fx = yf.download('USDKRW=X', start=start, end=end, progress=False, auto_adjust=False)
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
            if use_synthetic:
                qqq_raw = yf.download('QQQ', start=start, end=TQQQ_IPO, progress=False, auto_adjust=False)
                if len(qqq_raw) > 0:
                    qqq_c = qqq_raw['Close'].dropna().squeeze()
                    qqq_o = qqq_raw['Open'].dropna().squeeze()
                    qqq_ret = qqq_c.pct_change().fillna(0)
                    first_price = float(tqqq.iloc[0])
                    synth = [first_price]
                    for r in reversed((qqq_ret * 3 - DAILY_EXPENSE).values[1:]):
                        synth.insert(0, synth[0] / (1 + r) if (1 + r) != 0 else synth[0])
                    tqqq_synth = pd.Series(synth, index=qqq_c.index)
                    qqq_o_ret = qqq_o.pct_change().fillna(0)
                    first_open = float(tqqq_open.iloc[0])
                    synth_o = [first_open]
                    for r in reversed((qqq_o_ret * 3 - DAILY_EXPENSE).values[1:]):
                        synth_o.insert(0, synth_o[0] / (1 + r) if (1 + r) != 0 else synth_o[0])
                    tqqq_open_synth = pd.Series(synth_o, index=qqq_o.index)
                    tqqq = pd.concat([tqqq_synth, tqqq])
                    tqqq_open = pd.concat([tqqq_open_synth, tqqq_open])
            if len(tqqq) > 0 and len(fx) > 0:
                return tqqq, fx, tqqq_open
        except Exception as e:
            pass
        time.sleep(2)
    st.error('데이터를 불러오지 못했어요. 잠시 후 다시 시도해주세요.')
    st.stop()

# ── UI 시작 ──────────────────────────────────────────
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

if 'step' not in st.session_state: st.session_state.step = 1
if 'results' not in st.session_state: st.session_state.results = None
if 'selected_strategy' not in st.session_state: st.session_state.selected_strategy = None

tab_main, tab_qna = st.tabs(['📊 백테스터', '❓ Q&A'])

with tab_main:

 # ── 전략 소개 ──
 with st.expander('💡 이 전략이 뭔가요? (처음이시면 꼭 읽어보세요)', expanded=False):
    st.markdown("""
## TQQQ Adaptive Defense Strategy
*나스닥 3배 레버리지 ETF의 구조적 하락을 기회로 전환하는 동적 자산배분 모델*

---

### 들어가며
주식 시장에서 장기투자가 실패하는 이유는 대부분 수익률이 아니라 심리에 있다. 2002년 노벨경제학상을 수상한 대니얼 카너먼은 인간이 동일한 크기의 이익보다 손실을 약 2.5배 더 고통스럽게 인식한다는 것을 실증했다. 이 비대칭적 고통이 하락장에서의 패닉셀을 유발하고, 장기복리의 기회를 스스로 끊어낸다. 이 전략은 그 관찰에서 출발했다. 어떻게 하면 인간의 손실 회피 본능을 시스템으로 대체할 수 있을까. 감정이 아닌 구조로 하락장을 버티고, 오히려 기회로 전환할 수 있을까.

---

### 왜 나스닥인가
미국 기술주 중심의 나스닥 100은 단순한 주가지수가 아니다. 현재 글로벌 경제의 인프라를 구성하는 기업들의 집합체다. 애플의 생태계, 엔비디아의 AI 반도체, 마이크로소프트의 클라우드가 무너지지 않는 한 이 지수는 우상향한다는 것이 본 전략의 대전제다. 역설적으로, 만약 나스닥이 장기 우상향하지 못한다면 다른 어떤 자산도 안전하지 않다. 고금리 장기화, 반독점 규제, 지정학적 리스크 등이 나스닥의 밸류에이션을 압박할 수 있다. 본 전략은 그 리스크를 부정하지 않는다. 다만 확률적으로 우상향에 베팅하되, 하락 시 시스템이 자동으로 대응하도록 설계함으로써 불확실성을 관리한다.

---

### 왜 3배 레버리지인가
현대 시장은 두 가지 구조적 변화를 겪고 있다. 하나는 **알고리즘 매매의 확산**이다. 특정 지지선이 붕괴될 때 기계적 손절 물량이 연쇄적으로 출회되면서 하락의 기울기가 과거보다 가팔라졌다. 2020년 코로나 폭락이 단 33일 만에 -34%를 기록한 것은 우연이 아니다. 다른 하나는 **정책적 유동성의 비대칭성**이다. 각국 중앙은행은 위기 시 즉각적인 유동성 공급으로 대응하는 이른바 'Fed Put' 구조를 사실상 제도화했다. 그 결과 하락은 가팔라졌고, 반등은 빨라졌다.

| 폭락 사건 | 최대 낙폭 | 회복 기간 |
|:---|:---:|:---:|
| 2000년 닷컴버블 | -83% | 약 15년 |
| 2008년 금융위기 | -54% | 약 4년 |
| 2020년 코로나 | -30% | 약 5개월 |
| 2022년 긴축 충격 | -33% | 약 2년 |

회복 속도는 빨라지고 있다. 저점에서 매집한 TQQQ는 지수가 단순히 제자리로 돌아오는 것만으로도 기하급수적인 회복력을 발휘한다.

---

### 레버리지의 수학 : 양날의 검
TQQQ를 이해하려면 레버리지 복리의 수학적 구조를 먼저 알아야 한다. 지수가 하루 10% 오른 뒤 다음 날 약 9.1% 하락해 제자리로 돌아왔다고 가정하자.

```
1일차: 100 → 130 (+30%)
2일차: 130 → 94.5 (-27.3%)
결과: -5.5% ← 지수는 본전인데 TQQQ는 손실
```

이것이 **변동성 잠식(Volatility Drag)**이다. 수식으로 표현하면 다음과 같다.

```
Drag ≈ ½ × L² × σ²
```

L은 레버리지 배수, σ²는 변동성(분산)이다. TQQQ처럼 L=3이면 L²=9가 되어, 1배 ETF보다 변동성에 의한 손실이 **9배 증폭**된다. 시장이 방향 없이 위아래로 진동할수록 계좌는 조용히 마모된다. 반면 시장이 한 방향으로 꾸준히 오를 때는 반대 현상이 일어난다.

```
3일 연속 +3% 상승 시
단순 3배 계산: +9.09%
실제 TQQQ: +9.27% ← 3배를 초과하는 수익 발생
```

레버리지는 횡보장에서는 독이고, 추세장에서는 가속기다. 본 전략은 이 비대칭성을 이용한다.

---

### 전략의 핵심 : 하락을 버티는 것이 아니라 설계하는 것
레버리지 ETF의 가장 큰 적은 하락이 아니라 횡보다. 본 전략은 현금풀과 금고라는 두 개의 예비 자본 레이어를 설계해, MDD가 깊어질수록 오히려 매수 여력이 활성화되도록 구조화했다. MDD -5% 구간부터 -50% 구간까지 10단계로 분할 매수가 자동 집행되며, -50%를 초과하는 극단적 폭락 구간에서는 별도로 적립된 금고 자산이 추가 투입된다. **하락은 리스크가 아니라 시스템이 작동하는 트리거다.**

전고점 회복 시 TQQQ 70% / 현금 30% 비율로 자동 리밸런싱이 집행된다. 폭락 구간에서 낮은 단가로 매집한 물량을 고점 회복 시 일부 현금화함으로써, 다음 폭락을 위한 실탄을 재확보한다.

---

### 환율 반영 방법론
본 모델은 단순 달러 기준 수익률이 아닌, 매 거래일의 실제 USD/KRW 환율을 적용한 원화 기준 실질 수익률을 산출한다. 한국인 투자자에게 TQQQ의 실질 손익은 주가 변동과 환율 변동의 합산이다. 달러 강세 구간에서는 추가 수익이, 달러 약세 구간에서는 수익이 압축되는 효과가 모든 거래일에 자동으로 반영된다.

---

### 백테스트 방법론 및 데이터 출처
본 시뮬레이션은 yfinance를 통해 수집한 수정주가(Adjusted Price) 기반 일별 데이터를 사용한다. 수정주가는 배당 및 액면분할을 소급 반영하여 장기 수익률 왜곡을 최소화한다. 다음 항목은 현재 모델에 반영되지 않았으며 실제 투자 성과와 괴리가 발생할 수 있다. 거래 수수료 및 세금, 슬리피지(체결 가격 오차), 환전 비용, TQQQ 운용보수(연 0.98%). 본 백테스터는 전략의 논리적 타당성을 검증하기 위한 이론적 시뮬레이션이며, **과거 성과가 미래 수익을 보장하지 않는다.**

---

### 전략의 한계
본 전략이 가장 취약한 시나리오는 두 가지다.

**첫째**, 2000년 닷컴버블과 같은 구조적 장기 침체다. 나스닥이 -83% 하락한 뒤 15년간 전고점을 회복하지 못하는 구간에서는 현금풀과 금고 자산이 순차적으로 소진되며 이후 대응 여력이 사라진다.

**둘째**, 횡보 장기화다. V자 반등 없이 수년간 박스권이 지속될 경우 변동성 잠식이 누적되며 레버리지 원금이 지속적으로 감소한다. 이 구간에서 본 전략은 단순 홀딩 대비 열위에 놓일 수 있다.

이 한계를 인지하는 것이 전략을 올바르게 운용하는 전제 조건이다.

---

### 만든 사람
개인 투자에 대한 관심으로 시작해 여러 차례의 투자 실패를 경험했다. 그 경험이 금융에 대한 체계적 이해의 필요성을 깨닫게 했고, 금융투자분석사, 투자자산운용사, 신용분석사 자격증 취득으로 이어졌다. 이 사이트는 그 과정에서 직접 설계하고 검증한 전략을 구현한 결과물이며, 향후 포트폴리오로 활용될 예정이다.

📎 [@running\_for\_freedom1](https://www.instagram.com/running_for_freedom1)
""")

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
        st.caption(f'✅ 입력값: {seed_krw:,}원')
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
            '2022~현재 (금리인상 폭락 포함)': ('2022-01-01', None),
            '2020~현재 (코로나 포함)': ('2020-01-01', None),
            '2019~현재 (전체)': ('2019-01-01', None),
            '2010~현재 (TQQQ 상장 이후 전체)': ('2010-02-11', None),
            '2000~현재 (닷컴버블 포함 ⚠️합성)': ('2000-01-01', None),
            '2000~2010 (닷컴+금융위기 ⚠️합성)': ('2000-01-01', '2010-02-11'),
        }
        start_str, end_str = mapping[period]

    use_vault = st.checkbox('금고 사용 (극단적 폭락 대비 비상금)')
    if use_vault:
        col_v1, col_v2 = st.columns(2)
        with col_v1:
            # ✅ 버그1 수정: session_state로 금고 금액 유지
            if 'vault_krw_value' not in st.session_state:
                st.session_state.vault_krw_value = 3000000
            vault_krw = st.number_input(
                '금고 금액 (원)',
                min_value=100000,
                max_value=500000000,  # max_value를 시드에 묶지 않고 고정
                value=st.session_state.vault_krw_value,
                step=100000,
                format='%d',
                key='vault_krw_input'
            )
            st.session_state.vault_krw_value = vault_krw  # 입력값 저장
        with col_v2:
            vault_trigger = st.slider('금고 투입 시작 MDD (%)', min_value=30, max_value=70, value=50)
        st.caption(f'✅ 금고: {vault_krw:,}원 | MDD -{vault_trigger}% 이하부터 6구간에 나눠 투입')
    else:
        vault_krw = 0; vault_trigger = 50

    use_next_open = st.checkbox("📅 다음날 시가 매수 (현실적 체결가)", value=False,
                                help="MDD 도달 당일 종가 대신 다음날 시가로 체결. 실전과 더 유사합니다.")

    st.markdown('**⚙️ 고급 설정**')
    rebalance_band_pct = st.slider(
        '리밸런싱 민감도 (±%)',
        min_value=0, max_value=15, value=5,
        help='TQQQ 비율이 70%에서 이 값 이상 벗어날 때만 리밸런싱. 0이면 신고가마다 항상 실행 (비현실적).'
    )
    rebalance_band = rebalance_band_pct / 100
    st.caption(f'TQQQ 비율이 {70 - rebalance_band_pct}%~{70 + rebalance_band_pct}% 벗어날 때만 리밸런싱')

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

    is_dotcom = start_str and start_str.startswith('2000')
    if is_dotcom:
        st.warning('⚠️ 닷컴버블 구간은 합성 데이터 + 긴 기간으로 메모리가 많이 필요합니다. 전략 1개만 선택해주세요.')
        dotcom_strategy = st.radio('계산할 전략 선택', list(STRATEGIES.keys()), horizontal=True)

    if st.button("📊 백테스트 실행", type="primary"):
        with st.spinner('데이터 로딩 중... (최초 1회는 30초 정도 걸려요)'):
            try:
                tqqq, fx_series, tqqq_open = load_data(start_str, end_str)
                fx_dict = {str(d.date()): float(v) for d, v in zip(fx_series.index, fx_series.values)}
                fx_sorted = sorted(fx_dict.keys())
                start_fx = get_fx(fx_dict, fx_sorted, str(tqqq.index[0].date()))
                results = {}; all_stats = {}
                strategy_items = [(dotcom_strategy, STRATEGIES[dotcom_strategy])] if is_dotcom else STRATEGIES.items()
                for name, table in strategy_items:
                    h, s = run_backtest(table, tqqq, fx_dict, fx_sorted, seed_krw, use_vault, vault_krw if use_vault else 0, vault_trigger,
                                        use_next_open=use_next_open, tqqq_open=tqqq_open,
                                        use_dca=use_dca, dca_amount_krw=dca_amount_krw, dca_day=dca_day,
                                        rebalance_band=rebalance_band)
                    results[name] = h; all_stats[name] = s
                st.session_state.results = results
                st.session_state.all_stats = all_stats
                st.session_state.seed_krw = seed_krw
                st.session_state.start_fx = start_fx
                st.session_state.use_vault = use_vault
                st.session_state.vault_krw = vault_krw
                st.session_state.vault_trigger = vault_trigger
                st.session_state.fx_dict = fx_dict
                st.session_state.tqqq = tqqq
                st.session_state.step = 2
                st.rerun()
            except Exception as e:
                st.error(f'오류 발생: {e}')

# ── STEP 2: 결과 비교 ──
if st.session_state.results and st.session_state.step >= 2:
    with st.expander('② 전략 비교 결과', expanded=st.session_state.step == 2):
        results = st.session_state.results
        all_stats = st.session_state.all_stats
        seed_krw = st.session_state.seed_krw
        seed_krw_val = st.session_state.seed_krw
        cols = st.columns(4)
        strategy_names = list(results.keys())
        for i, name in enumerate(strategy_names):
            h = results[name]
            final_krw = h[-1]['total_krw']
            initial_krw = h[0]['total_krw']
            rate = (final_krw / initial_krw - 1) * 100
            years = len(h) / 52
            with cols[i]:
                st.metric(name, f'{final_krw:,.0f}원', f'{rate:+.1f}%')
                cagr = ((final_krw / initial_krw) ** (1/years) - 1) * 100 if years > 0 else 0
                st.caption(f'{seed_krw_val/10000:.0f}만원 → {final_krw/10000:.0f}만원 ({years:.1f}년) | 연평균 {cagr:.1f}%')
        with cols[3]:
            h = results[strategy_names[0]]
            hold_krw = h[-1]['hold_krw']
            hold_rate = (hold_krw / h[0]['total_krw'] - 1) * 100
            years = len(h) / 52
            st.metric('단순 홀딩', f'{hold_krw:,.0f}원', f'{hold_rate:+.1f}%')
            hold_cagr = ((hold_krw / h[0]['total_krw']) ** (1/years) - 1) * 100 if years > 0 else 0
            st.caption(f'{seed_krw_val/10000:.0f}만원 → {hold_krw/10000:.0f}만원 ({years:.1f}년) | 연평균 {hold_cagr:.1f}%')

        import pandas as pd
        first = results[strategy_names[0]]
        dates_list = [h['date'] for h in first]
        start_dt = dates_list[0]
        end_dt = dates_list[-1]

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

        def calc_rsi(series, period=14):
            delta = series.diff()
            gain = delta.clip(lower=0).rolling(period).mean()
            loss = (-delta.clip(upper=0)).rolling(period).mean()
            rs = gain / loss
            return 100 - (100 / (1 + rs))

        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        colors_map = {'초반 집중형': '#e74c3c', '중반 집중형': '#f39c12', '후반 집중형': '#2ecc71'}

        fig = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            row_heights=[0.6, 0.2, 0.2],
            vertical_spacing=0.03
        )

        # ── 전략별 수익률 ──
        for strat_name, history in results.items():
            totals = [h['total_krw'] for h in history]
            rate = (totals[-1] / totals[0] - 1) * 100

            def fmt_krw(x):
                if x >= 1e8: return f'{x/1e8:.1f}억원'
                elif x >= 1e4: return f'{x/1e4:.0f}만원'
                return f'{x:.0f}원'

            hover_texts = [
                f"<b>{strat_name}</b><br>날짜: {h['date']}<br>자산: {fmt_krw(h['total_krw'])}<br>TQQQ: ${h['price']:.2f}<br>MDD: {h['mdd']:.1f}%"
                for h in history
            ]
            fig.add_trace(go.Scatter(
                x=[h['date'] for h in history],
                y=totals,
                name=f"{strat_name} ({rate:+.1f}%)",
                line=dict(color=colors_map[strat_name], width=1.5),
                hovertemplate="%{customdata}<extra></extra>",
                customdata=hover_texts
            ), row=1, col=1)

        # TQQQ 홀딩
        hold = [h['hold_krw'] for h in first]
        hold_rate = (hold[-1] / hold[0] - 1) * 100
        hold_hover = [
            f"<b>TQQQ 홀딩</b><br>날짜: {h['date']}<br>자산: {fmt_krw(h['hold_krw'])}<br>TQQQ: ${h['price']:.2f}"
            for h in first
        ]
        fig.add_trace(go.Scatter(
            x=[h['date'] for h in first],
            y=hold,
            name=f"TQQQ 홀딩 ({hold_rate:+.1f}%)",
            line=dict(color='#74b9ff', width=1.5),
            hovertemplate="%{customdata}<extra></extra>",
            customdata=hold_hover
        ), row=1, col=1)

        # QQQ 홀딩
        if qqq_data is not None and len(qqq_data) > 0:
            qqq_dates = [str(d.date()) for d in qqq_data.index]
            qqq_vals = qqq_data.values
            first_qqq_price = None
            first_fx = st.session_state.get('start_fx', 1350)
            for d in dates_list:
                if d in qqq_dates:
                    first_qqq_price = float(qqq_vals[qqq_dates.index(d)])
                    break
            if first_qqq_price:
                total_krw_for_qqq = st.session_state.seed_krw + st.session_state.get('vault_krw', 0)
                qqq_shares = (total_krw_for_qqq / first_fx) / first_qqq_price
                fx_dict_local = st.session_state.get('fx_dict', {})
                fx_sorted_local = sorted(fx_dict_local.keys())
                qqq_x, qqq_y = [], []
                for d in dates_list:
                    if d in qqq_dates:
                        price = float(qqq_vals[qqq_dates.index(d)])
                        fx = fx_dict_local.get(d, 1350)
                        if not fx and fx_sorted_local:
                            past = [x for x in fx_sorted_local if x <= d]
                            fx = fx_dict_local[past[-1]] if past else 1350
                        qqq_x.append(d)
                        qqq_y.append(qqq_shares * price * fx)
                if qqq_y:
                    qqq_rate = (qqq_y[-1] / qqq_y[0] - 1) * 100
                    fig.add_trace(go.Scatter(
                        x=qqq_x, y=qqq_y,
                        name=f"QQQ 홀딩 ({qqq_rate:+.1f}%)",
                        line=dict(color='#6c5ce7', width=1.5),
                        hovertemplate="<b>QQQ 홀딩</b><br>날짜: %{x}<br>자산: %{y:,.0f}원<extra></extra>"
                    ), row=1, col=1)

        # ── RSI ──
        if qqq_data is not None and len(qqq_data) > 0:
            rsi = calc_rsi(qqq_data)
            rsi_x = [str(d.date()) for d in rsi.index if not pd.isna(rsi[d])]
            rsi_y = [float(rsi[d]) for d in rsi.index if not pd.isna(rsi[d])]
            if rsi_y:
                fig.add_trace(go.Scatter(
                    x=rsi_x, y=rsi_y,
                    name='RSI (QQQ)',
                    line=dict(color='#fdcb6e', width=1),
                    hovertemplate="RSI: %{y:.1f}<extra></extra>"
                ), row=2, col=1)
                fig.add_hline(y=70, line_color='#e17055', line_dash='dash', line_width=1, row=2, col=1)
                fig.add_hline(y=30, line_color='#00b894', line_dash='dash', line_width=1, row=2, col=1)

        # ── VIX ──
        if vix_data is not None and len(vix_data) > 0:
            vix_x = [str(d.date()) for d in vix_data.index]
            vix_y = [float(v) for v in vix_data.values]
            fig.add_trace(go.Scatter(
                x=vix_x, y=vix_y,
                name='VIX',
                line=dict(color='#fd79a8', width=1),
                fill='tozeroy',
                fillcolor='rgba(253,121,168,0.1)',
                hovertemplate="VIX: %{y:.1f}<extra></extra>"
            ), row=3, col=1)
            fig.add_hline(y=30, line_color='#e17055', line_dash='dash', line_width=1, row=3, col=1)

        # ── 레이아웃 ──
        fig.update_layout(
            height=650,
            paper_bgcolor='#1a1a2e',
            plot_bgcolor='#16213e',
            font=dict(color='white', size=11),
            legend=dict(
                bgcolor='rgba(15,52,96,0.8)',
                bordercolor='#444',
                font=dict(color='white', size=11)
            ),
            hovermode='x unified',
            margin=dict(l=60, r=20, t=20, b=40)
        )
        fig.update_yaxes(
            gridcolor='rgba(255,255,255,0.1)',
            tickfont=dict(color='white'),
            tickformat=',.0f',
            row=1, col=1
        )
        fig.update_yaxes(title_text='RSI', tickfont=dict(color='white'), range=[0,100], row=2, col=1)
        fig.update_yaxes(title_text='VIX', tickfont=dict(color='white'), row=3, col=1)
        fig.update_xaxes(tickfont=dict(color='white'), gridcolor='rgba(255,255,255,0.1)')

        st.plotly_chart(fig, use_container_width=True)

        if start_str < TQQQ_IPO:
            st.warning('⚠️ 선택한 기간에 TQQQ 상장일(2010-02-11) 이전이 포함되어 있습니다. 해당 구간은 QQQ 일간수익률 × 3배로 합성한 데이터이며 실제 TQQQ와 괴리가 있을 수 있습니다.')

        st.subheader('📊 전략별 상세')
        for name in strategy_names:
            h = results[name]; s = all_stats[name]
            tqqq_mdd = min(x['mdd'] for x in h)
            # 포트폴리오 MDD 직접 계산
            port_vals = [x['total_krw'] for x in h]
            port_peak = port_vals[0]; port_mdd = 0
            for v in port_vals:
                if v > port_peak: port_peak = v
                dd = (v - port_peak) / port_peak * 100
                port_mdd = min(port_mdd, dd)
            worst_mdd = tqqq_mdd
            final_krw = h[-1]['total_krw']
            init_krw = h[0]['total_krw']
            years = len(h) / 52
            cagr = ((final_krw / init_krw) ** (1/years) - 1) * 100 if years > 0 else 0
            with st.expander(f'{name} | 최종 {final_krw/10000:.0f}만원 | 연평균 {cagr:.1f}%'):
                c1, c2, c3, c4, c5, c6 = st.columns(6)
                c1.metric('최종 자산', f'{final_krw/10000:.0f}만원', f'{(final_krw/init_krw-1)*100:+.1f}%')
                c2.metric('연평균 수익률', f'{cagr:.1f}%')
                c3.metric('포트폴리오 MDD', f'{port_mdd:.1f}%', f'TQQQ {tqqq_mdd:.1f}%')
                total_tx = s["buy_count"] + s["vault_buy_count"] + s["rebalance_count"]
                # Recovery Factor: 총수익률 / 포트폴리오 MDD (같은 단위 % / % → 무차원)
                recovery_factor = (final_krw / init_krw - 1) / (abs(port_mdd) / 100) if port_mdd != 0 else 0
                history = h
                weekly_returns = pd.Series([x['total_krw'] for x in history]).pct_change().dropna()
                sharpe = (weekly_returns.mean() / weekly_returns.std() * (52**0.5)) if weekly_returns.std() > 0 else 0
                c4.metric('Recovery Factor', f'{recovery_factor:.2f}x')
                c5.metric('Sharpe Ratio', f'{sharpe:.2f}')
                c6.metric('총 거래 횟수', f'{total_tx}회')
                st.caption(f'매수 {s["buy_count"] + s["vault_buy_count"]}회 (현금풀 {s["buy_count"]}회 · 금고 {s["vault_buy_count"]}회) 리밸런싱(매도) {s["rebalance_count"]}회')

                hold_returns = pd.Series([x['hold_krw'] for x in history]).pct_change().dropna()
                hold_sharpe_val = (hold_returns.mean() / hold_returns.std() * (52**0.5)) if hold_returns.std() > 0 else 0
                if recovery_factor >= 1 and sharpe > hold_sharpe_val:
                    insight = f'✅ 단순 TQQQ 홀딩보다 Sharpe가 {sharpe/hold_sharpe_val:.1f}배 높고, 낙폭 대비 수익 회복력도 양호합니다. 리스크 관리가 효과적인 구간입니다.'
                elif sharpe > hold_sharpe_val:
                    insight = f'📈 단순 홀딩보다 Sharpe가 {sharpe/hold_sharpe_val:.1f}배 높습니다. 변동성 대비 수익은 효율적이나, 아직 낙폭 회복 중인 구간입니다.'
                elif recovery_factor >= 1:
                    insight = f'💰 낙폭 대비 수익은 양호하나, 변동성이 커서 Sharpe는 홀딩({hold_sharpe_val:.2f})보다 낮습니다. 장기 보유 시 유리한 전략입니다.'
                else:
                    insight = f'⚠️ 현재 구간은 낙폭 회복 중입니다. Sharpe {sharpe:.2f} / 홀딩 {hold_sharpe_val:.2f} — 백테스트 기간을 길게 잡을수록 전략 효과가 뚜렷하게 나타납니다.'
                st.info(insight)

                # ✅ 사용자 개입 시뮬레이션
                st.divider()
                st.markdown('#### 🧪 사용자 개입 시뮬레이션')
                st.caption('특정 날짜에 추가 매수했다면 결과가 어떻게 달라졌는지 비교해보세요.')
                st.warning('⚠️ 개입 시점은 사후 판단입니다. 실제 그 시점에 동일한 결정을 내릴 수 있었는지 고려하세요.')

                # 세션 키 (전략별로 분리)
                key_prefix = f'manual_buys_{name}'
                if key_prefix not in st.session_state:
                    st.session_state[key_prefix] = []

                # 입력 UI
                col_date, col_amount, col_add = st.columns([2, 2, 1])
                with col_date:
                    mb_date = st.date_input('날짜', key=f'mb_date_{name}',
                                            min_value=pd.Timestamp(h[0]['date']),
                                            max_value=pd.Timestamp(h[-1]['date']),
                                            value=pd.Timestamp(h[0]['date']))
                with col_amount:
                    mb_amount = st.number_input('금액 (원)', min_value=100000, value=1000000,
                                                step=100000, format='%d', key=f'mb_amount_{name}')
                with col_add:
                    st.write('')
                    st.write('')
                    if st.button('추가', key=f'mb_add_{name}'):
                        st.session_state[key_prefix].append({
                            'date': str(mb_date),
                            'amount_krw': mb_amount
                        })

                # 입력된 개입 목록 표시
                if st.session_state[key_prefix]:
                    mb_list = st.session_state[key_prefix]
                    for idx, mb in enumerate(mb_list):
                        col_info, col_del = st.columns([5, 1])
                        with col_info:
                            st.caption(f"📅 {mb['date']} — {mb['amount_krw']:,}원")
                        with col_del:
                            if st.button('삭제', key=f'mb_del_{name}_{idx}'):
                                st.session_state[key_prefix].pop(idx)
                                st.rerun()

                    if st.button('🔄 개입 시나리오 계산', key=f'mb_calc_{name}', type='primary'):
                        # 개입 포함 백테스트 재실행
                        _tqqq = st.session_state.tqqq
                        _fx_dict = st.session_state.fx_dict
                        _fx_sorted = sorted(_fx_dict.keys())
                        _buy_table = STRATEGIES[name]
                        _seed_krw = st.session_state.seed_krw
                        _use_vault = st.session_state.use_vault
                        _vault_krw = st.session_state.vault_krw if _use_vault else 0
                        _vault_trigger = st.session_state.vault_trigger

                        h2, s2 = run_backtest(
                            _buy_table, _tqqq, _fx_dict, _fx_sorted,
                            _seed_krw, _use_vault, _vault_krw, _vault_trigger,
                            manual_buys=mb_list
                        )

                        # 결과 비교 표시
                        st.markdown('**📊 규칙 기반 vs 개입 포함 비교**')
                        orig_final = h[-1]['total_krw']
                        new_final = h2[-1]['total_krw']
                        orig_rate = (orig_final / h[0]['total_krw'] - 1) * 100
                        new_rate = (new_final / h2[0]['total_krw'] - 1) * 100
                        total_mb_krw = sum(mb['amount_krw'] for mb in mb_list)

                        # 포트폴리오 MDD 계산
                        def calc_portfolio_mdd(hist):
                            vals = [x['total_krw'] for x in hist]
                            peak = vals[0]; mdd_p = 0
                            for v in vals:
                                if v > peak: peak = v
                                dd = (v - peak) / peak * 100
                                mdd_p = min(mdd_p, dd)
                            return mdd_p

                        orig_pmdd = calc_portfolio_mdd(h)
                        new_pmdd = calc_portfolio_mdd(h2)

                        _years = len(h) / 52
                        orig_cagr = ((orig_final / h[0]['total_krw']) ** (1/_years) - 1) * 100 if _years > 0 else 0
                        new_cagr = ((new_final / h2[0]['total_krw']) ** (1/_years) - 1) * 100 if _years > 0 else 0

                        comp_data = {
                            '지표': ['최종 자산', '총 수익률', '연평균 수익률', '포트폴리오 MDD'],
                            '규칙 기반': [
                                f'{orig_final:,.0f}원',
                                f'{orig_rate:+.1f}%',
                                f'{orig_cagr:.1f}%',
                                f'{orig_pmdd:.1f}%'
                            ],
                            '개입 포함': [
                                f'{new_final:,.0f}원',
                                f'{new_rate:+.1f}%',
                                f'{new_cagr:.1f}%',
                                f'{new_pmdd:.1f}%'
                            ],
                            '차이': [
                                f'{new_final - orig_final:+,.0f}원',
                                f'{new_rate - orig_rate:+.1f}%p',
                                f'{new_cagr - orig_cagr:+.1f}%p',
                                f'{new_pmdd - orig_pmdd:+.1f}%p'
                            ]
                        }
                        st.dataframe(pd.DataFrame(comp_data), use_container_width=True, hide_index=True)
                        st.caption(f'💡 총 개입 금액: {total_mb_krw:,}원 | 개입 없이 같은 금액을 시드에 추가했을 때와 비교해보세요.')

                st.divider()
                st.write('**📋 거래 내역 (매수 🟢 / 리밸런싱 🔵)**')
                unified_log = []
                hist_dict = {x['date']: x for x in results[name]}
                use_vault_display = st.session_state.get('use_vault', False)
                start_fx_val = st.session_state.get('start_fx', 1350)
                vault_krw_set = st.session_state.get('vault_krw', 0)

                for b in s['buy_log']:
                    h_match = hist_dict.get(b['date'])
                    fx_val = h_match['fx'] if h_match else 1350
                    shares_after = b.get('shares_total', h_match['tqqq_shares'] if h_match else '-')
                    price_day = h_match['price'] if h_match else b['price']
                    eval_krw = round(shares_after * price_day * fx_val / 10000) if isinstance(shares_after, (int, float)) else '-'
                    cash_remain = round(b.get('cash_after_krw', 0) / 10000) if 'cash_after_krw' in b else '-'
                    # ✅ 버그2 수정: vault_after는 이미 run_backtest에서 실제 차감 후 값으로 저장됨
                    vault_remain = round(b.get('vault_after_krw', 0) / 10000) if 'vault_after_krw' in b else '-'
                    unified_log.append({
                        '_type': 'buy',
                        '날짜': b['date'],
                        '이벤트': ('🔴' if b['source'] == '사용자개입' else ('🟡' if b['source'] == 'DCA' else '🟢')) + f" {b['shares']}주 매수 ({b['source']})",
                        'TQQQ가격': f"${price_day:.2f}",
                        'MDD': f"{b['mdd']:.1f}%",
                        '보유주수': f"{shares_after:.1f}주" if isinstance(shares_after, (int, float)) else '-',
                        '평가금액': f'{int(eval_krw)*10000:,}원' if isinstance(eval_krw, (int,float)) else '-',
                        '현금풀': f'{int(cash_remain)*10000:,}원' if isinstance(cash_remain, (int,float)) else '-',
                        '금고': f'{int(vault_remain)*10000:,}원' if isinstance(vault_remain, (int,float)) else '-',
                    })

                for r in s['rebalance_log']:
                    h_match = hist_dict.get(r['date'])
                    fx_val = h_match['fx'] if h_match else 1350
                    shares_after = h_match['tqqq_shares'] if h_match else '-'
                    price_day = h_match['price'] if h_match else r['price']
                    eval_krw = round(shares_after * price_day * fx_val / 10000) if isinstance(shares_after, (int, float)) else '-'
                    cash_krw_val = h_match.get('cash_krw', 0) if h_match else 0
                    vault_krw_val = h_match.get('vault_krw', 0) if h_match else 0
                    cash_remain = round(cash_krw_val / 10000)
                    vault_remain = round(vault_krw_val / 10000)
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
                        elif '🟡' in str(row['이벤트']):
                            return ['background-color: rgba(253,203,110,0.15)'] * len(row)
                        elif '🔴' in str(row['이벤트']):
                            return ['background-color: rgba(231,76,60,0.15)'] * len(row)
                        return [''] * len(row)

                    if not use_vault_display or s['vault_buy_count'] == 0:
                        df_unified = df_unified.drop(columns=['금고'], errors='ignore')
                    styled = df_unified.style.apply(highlight_row, axis=1)
                    row_h = 35
                    table_h = min(600, max(200, len(unified_log) * row_h + 40))
                    st.dataframe(styled, use_container_width=True, hide_index=True, height=table_h)

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
        styled = year_df.style.applymap(color_rate, subset=numeric_cols).format(fmt_rate, subset=numeric_cols)
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
            my_avg = st.number_input('평균 매수단가 ($)', min_value=0.0, value=0.0, step=0.01)
        with col3:
            my_cash = st.number_input('남은 현금 (원)', min_value=0, value=0, step=100000, format='%d')

        if st.button('현재 상황 분석'):
            tqqq = st.session_state.tqqq
            cur_price = float(tqqq.iloc[-1])
            cur_fx = list(st.session_state.results.values())[0][-1]['fx']
            cur_mdd = list(st.session_state.results.values())[0][-1]['mdd']
            st.subheader('📊 현재 상황 분석')
            c1, c2, c3 = st.columns(3)
            c1.metric('현재 TQQQ 가격', f'${cur_price:.2f}')
            c2.metric('현재 MDD', f'{cur_mdd:.1f}%')
            c3.metric('현재 환율', f'{cur_fx:,.0f}원')

            if my_shares > 0 and my_avg > 0:
                my_tqqq_value_krw = my_shares * cur_price * cur_fx
                my_total_krw = my_tqqq_value_krw + my_cash
                my_profit_rate = (cur_price / my_avg - 1) * 100
                st.metric('내 TQQQ 평가금액', f'{my_tqqq_value_krw:,.0f}원', f'{my_profit_rate:+.1f}%')
                st.metric('내 총 자산 (추정)', f'{my_total_krw:,.0f}원')

            st.subheader('📍 다음 매수 구간 안내')
            strategy_table = STRATEGIES[st.session_state.selected_strategy]
            next_levels = [(level, ratio) for level, ratio in strategy_table if level < cur_mdd]
            triggered = [(level, ratio) for level, ratio in strategy_table if level >= cur_mdd]
            cash_pool = my_cash if my_cash > 0 else 0

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

# ── Q&A 탭 ──
with tab_qna:
    st.markdown('## ❓ 자주 묻는 질문')
    st.caption('사이트 이용 중 궁금한 점을 정리했어요.')

    # ── 기본 설정 ──
    with st.expander('📌 기본 설정'):
        st.markdown("""
**Q. 시드 금액은 뭔가요?**
백테스트에 사용할 초기 투자 원금이에요. 이 금액의 70%는 TQQQ를 첫날 시가에 매수하고, 30%는 현금풀로 보유해요.

---

**Q. 금고는 시드와 별개인가요?**
네, 완전히 별개예요. 시드 1,000만원 + 금고 300만원이면 총 1,300만원 투자예요. 금고는 현금풀 계산에 포함되지 않아요.

---

**Q. 다음날 시가 매수 옵션은 뭔가요?**
MDD 조건은 당일 종가로 판단하지만, 실제 매수 체결은 다음날 시가로 계산해요. 끄면 당일 종가로 바로 체결돼요. 현실적인 시뮬레이션을 원하면 켜는 게 맞아요.

---

**Q. 현금풀 30%는 왜 30%인가요?**
폭락 시 분할매수 실탄을 확보하면서도 초기 수익 참여를 극대화하는 균형점으로 설계된 비율이에요. 70%는 TQQQ 상승장의 복리 효과를 최대한 누리고, 30%는 하락 시 10단계 매수에 쓰이는 구조예요.
""")

    # ── 환율 계산 ──
    with st.expander('💱 환율 계산 방식'):
        st.markdown("""
**Q. 환율은 어떻게 반영되나요?**
yfinance에서 받은 실제 USD/KRW 일별 환율을 사용해요. 매수할 때는 그날의 환율로 달러 환산해서 주수를 계산하고, 평가금액도 그날 환율 기준 원화로 표시해요.

---

**Q. 주말이나 공휴일 환율은요?**
거래일이 아닌 날은 직전 마지막 거래일 환율을 그대로 사용해요.

---

**Q. 현금풀/금고 잔액이 환율에 따라 변하나요?**
아니요. 현금풀과 금고는 원화로 저장돼요. 환율이 올라도 잔액이 늘어 보이는 일이 없어요. 매수할 때만 그날 환율로 달러 환산해요.
""")

    # ── 수수료 및 데이터 ──
    with st.expander('💸 수수료 및 데이터 출처'):
        st.markdown("""
**Q. 수수료가 반영되나요?**
아니요. 매수/매도 수수료, 환전 비용, 세금은 반영되지 않아요. 실제 투자 결과는 이보다 낮을 수 있어요.

---

**Q. TQQQ 운용보수는 반영되나요?**
아니요. TQQQ 연간 운용보수 0.98%는 반영되지 않아요. 장기 백테스트일수록 실제와의 괴리가 커져요.

---

**Q. 슬리피지(체결 가격 오차)는요?**
반영 안 돼요. 수수료·운용보수·슬리피지 세 가지가 실제 투자 결과와 차이가 나는 주된 요인이에요.

---

**Q. TQQQ 데이터는 어디서 가져오나요?**
yfinance를 통해 수정주가(Adjusted Price) 일별 데이터를 받아요. 수정주가는 배당과 액면분할을 소급 반영해서 장기 수익률 왜곡을 최소화한 가격이에요.

---

**Q. 2010년 이전 데이터는 실제 TQQQ인가요?**
아니요. TQQQ는 2010년 2월 11일 상장이에요. 그 이전 구간(닷컴버블 포함)은 QQQ 일간 수익률에 3배를 곱해서 합성한 데이터예요. 실제 TQQQ와 괴리가 있을 수 있어요.
""")

    # ── 리스크 지표 ──
    with st.expander('📊 리스크 지표 산정 방식'):
        st.markdown("""
**Q. 포트폴리오 MDD는 어떻게 계산하나요?**
백테스트 기간 중 역대 최고 총자산 대비 가장 많이 떨어진 비율이에요. 현금풀·금고가 있어서 TQQQ 자체 MDD보다 항상 낮아요.

---

**Q. Recovery Factor는 뭔가요?**
`총수익률 ÷ 포트폴리오 MDD`예요. 예를 들어 총수익률 +60%, MDD -30%이면 Recovery Factor = 2.0이에요. 숫자가 클수록 손실 대비 수익 회복력이 좋다는 의미고, 1.0 이상이면 낙폭보다 수익이 더 크다는 뜻이에요.

---

**Q. Sharpe Ratio는 어떻게 계산하나요?**
주간 수익률 기준으로 `(주간 평균 수익률 ÷ 주간 수익률 표준편차) × √52`로 연환산해요. 무위험 수익률은 0으로 가정해요. 단순홀딩 Sharpe보다 높으면 리스크 관리 면에서 전략이 유효하다는 의미예요.

---

**Q. 연평균 수익률(CAGR)은 어떻게 계산하나요?**
`(최종자산 ÷ 초기자산)^(1/연수) - 1`로 계산해요. 연수는 히스토리 기록 횟수 ÷ 52로 환산해요.

---

**Q. RSI는 뭘 기준으로 계산하나요?**
QQQ(나스닥 100 ETF) 14일 RSI예요. 70 이상이면 과매수, 30 이하면 과매도 구간이에요.

---

**Q. VIX는 뭔가요?**
시카고옵션거래소(CBOE)의 변동성 지수예요. 30 이상이면 시장 공포 구간으로 봐요. 차트의 빨간 점선이 30 기준선이에요.

---

**Q. 단순 홀딩은 어떻게 계산하나요?**
시드 + 금고 전액으로 첫날 TQQQ를 살 수 있는 만큼 사서 끝까지 보유한 결과예요. 전략과 동일한 초기 자금을 기준으로 비교해요.
""")

    # ── 실제 투자 주의사항 ──
    with st.expander('⚠️ 실제 투자 시 주의사항 (레버리지 리스크)'):
        st.markdown("""
**Q. 이 전략대로 그냥 따라 투자하면 되나요?**
아니요. 이 사이트는 전략의 논리적 타당성을 검증하는 **시뮬레이터**예요. 실제 투자 결과는 수수료, 세금, 환전 비용, 슬리피지 등으로 인해 달라질 수 있어요. 투자 결정은 본인 책임이에요.

---

**Q. TQQQ는 얼마나 위험한가요?**
TQQQ는 나스닥 100 지수의 일간 수익률을 **3배** 추종하는 레버리지 ETF예요. 나스닥이 -33% 하락하면 이론상 TQQQ는 -99%에 가까워질 수 있어요. 2022년 한 해에만 -79%를 기록했어요. 단기 변동성이 극심하고, 횡보 구간에서는 **변동성 잠식(Volatility Drag)** 으로 원금이 서서히 감소할 수 있어요.

---

**Q. 닷컴버블 같은 상황이 다시 오면 어떻게 되나요?**
본 전략의 가장 취약한 시나리오예요. 2000년 닷컴버블 당시 나스닥은 -83% 하락 후 15년간 전고점을 회복하지 못했어요. 이 경우 현금풀과 금고가 순차적으로 소진되고 이후 대응 여력이 사라져요. 닷컴버블 포함 구간 백테스트로 최악의 시나리오를 반드시 확인해보세요.

---

**Q. 레버리지 ETF는 장기 보유해도 되나요?**
조건부로 가능해요. 나스닥이 장기 우상향하는 구간에서는 레버리지 복리 효과로 일반 ETF를 크게 초과해요. 그러나 장기 횡보·하락 구간에서는 변동성 잠식이 누적돼 손실이 커질 수 있어요. 이 전략은 그 위험을 분할매수 시스템으로 관리하는 구조지만, **원금 손실 가능성은 항상 존재해요.**

---

**Q. 어느 정도 금액을 투자해야 하나요?**
잃어도 생활에 지장 없는 금액만 투자하는 것이 원칙이에요. 레버리지 ETF는 단기간에 자산이 반토막 날 수 있어요. 생활비·비상금과 철저히 분리된 여유 자금으로만 운용하세요.
""")

    # ── 활용 가이드 ──
    with st.expander('🧭 이 사이트를 어떻게 활용하면 좋은가요?'):
        st.markdown("""
**STEP 1. 전략 소개 먼저 읽기**
'이 전략이 뭔가요?' 섹션을 펼쳐 전략의 설계 원리와 한계를 먼저 이해하세요. 백테스트 숫자보다 논리를 먼저 납득하는 게 중요해요.

---

**STEP 2. 기간을 다양하게 설정해보기**
- 2022~현재: 금리 인상 폭락 구간 — 전략이 잘 작동하는 구간
- 2000~현재: 닷컴버블 포함 — 전략의 한계를 확인하는 최악의 시나리오
- 두 구간을 모두 돌려보고 전략의 강점과 약점을 파악하세요.

---

**STEP 3. 3가지 전략 비교하기**
초반·중반·후반 집중형이 같은 시드, 같은 기간에서 어떻게 다른 결과를 내는지 비교해보세요. 내 심리와 맞는 전략을 고르는 게 핵심이에요.

---

**STEP 4. 금고 옵션 켜고 비교하기**
금고 없는 결과와 있는 결과를 비교해보면 극단적 폭락 시 금고의 효과를 체감할 수 있어요.

---

**STEP 5. 현재 상황 입력하기**
이미 TQQQ를 보유 중이라면 ③ 현재 상황 입력 섹션에서 지금 MDD 기준 남은 매수 구간을 확인해보세요.

---

**⚠️ 주의**
백테스트는 과거 데이터 기반 시뮬레이션이에요. 좋은 결과가 나왔다고 바로 투자하지 말고, 전략의 한계와 리스크를 충분히 이해한 후 본인 판단으로 결정하세요.
""")
