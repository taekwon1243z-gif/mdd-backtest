"""
backtest_engine.py 검증 테스트
실행: pytest test_backtest_engine.py -v
"""
import math
import pandas as pd
import pytest
from backtest_engine import get_fx, make_vault_table, run_backtest

# ── 공통 설정 ────────────────────────────────────────
SEED_KRW    = 10_000_000  # 1천만원
FX          = 1300        # 1달러 = 1300원 (고정)
START_PRICE = 50.0        # TQQQ 시작가 $50

# 테스트용 단순 전략 (중반 집중형)
STRATEGY = [
    (-5,  0.02), (-10, 0.03), (-15, 0.12), (-20, 0.20),
    (-25, 0.18), (-30, 0.15), (-35, 0.13), (-40, 0.07),
    (-45, 0.06), (-50, 0.04),
]

def make_tqqq(prices, start='2022-01-03'):
    """mock TQQQ 시리즈 생성 (영업일 기준)"""
    idx = pd.date_range(start=start, periods=len(prices), freq='B')
    return pd.Series(prices, index=idx)

def make_fx_dict(tqqq, fx_val=FX):
    """고정 환율 fx_dict 생성"""
    dates = [str(d.date()) for d in tqqq.index]
    fx_dict = {d: fx_val for d in dates}
    return fx_dict, sorted(dates)

def calc_expected_init(seed_krw, start_price, fx):
    """초기 주수/현금풀 수동 계산"""
    seed_usd     = seed_krw / fx
    shares       = math.floor(seed_usd * 0.70 / start_price)
    leftover_krw = round((seed_usd * 0.70 - shares * start_price) * fx)
    cash_krw     = round(seed_krw * 0.30) + leftover_krw
    return shares, cash_krw


# ── 1. 초기화 검증 ────────────────────────────────────
def test_initialization():
    """시드 1천만원, FX=1300, 시작가 $50 → 초기 주수/현금풀이 수동 계산과 일치하는지"""
    tqqq = make_tqqq([START_PRICE, START_PRICE])
    fx_dict, fx_sorted = make_fx_dict(tqqq)
    history, stats = run_backtest(STRATEGY, tqqq, fx_dict, fx_sorted,
                                  SEED_KRW, False, 0, 50)

    expected_shares, expected_cash = calc_expected_init(SEED_KRW, START_PRICE, FX)
    h = history[-1]

    assert h['tqqq_shares'] == expected_shares,  f"주수 불일치: {h['tqqq_shares']} != {expected_shares}"
    assert h['cash_krw']    == expected_cash,    f"현금풀 불일치: {h['cash_krw']} != {expected_cash}"
    assert stats['buy_count']       == 0
    assert stats['rebalance_count'] == 0


# ── 2. 단일 매수 검증 (-10% 구간) ─────────────────────
def test_single_buy_at_minus10():
    """$50 → $45 (-10%) 하락 시 -5%, -10% 두 레벨 모두 트리거 → 매수 2회, -10% 레벨 비용 검증"""
    tqqq = make_tqqq([50.0, 45.0])
    fx_dict, fx_sorted = make_fx_dict(tqqq)
    history, stats = run_backtest(STRATEGY, tqqq, fx_dict, fx_sorted,
                                  SEED_KRW, False, 0, 50)

    # -10% 하락 시 -5%(-10% 통과), -10% 두 레벨 동시 트리거 → 2회
    assert stats['buy_count'] == 2

    _, init_cash = calc_expected_init(SEED_KRW, 50.0, FX)

    # -10% 레벨 매수 검증 (buy_log 순서: -5% → -10%)
    b = [x for x in stats['buy_log'] if x['level'] == -10][0]
    expected_invest = init_cash * 0.03                           # 현금풀의 3%
    expected_shares = math.floor(expected_invest / (45.0 * FX))
    expected_cost   = round(expected_shares * 45.0 * FX)

    assert b['source']   == '현금풀'
    assert b['shares']   == expected_shares, f"매수 주수 불일치: {b['shares']} != {expected_shares}"
    assert b['cost_krw'] == expected_cost,   f"매수 비용 불일치: {b['cost_krw']} != {expected_cost}"


# ── 3. 레벨 중복 방지 ─────────────────────────────────
def test_level_not_repeated():
    """같은 레벨(-10%)에서 두 번 매수하지 않는다"""
    # Day2: $45 (-10% 진입), Day3: $44 (여전히 -10%~-15% 사이, -10% 레벨 재진입 없음)
    tqqq = make_tqqq([50.0, 45.0, 44.0])
    fx_dict, fx_sorted = make_fx_dict(tqqq)
    history, stats = run_backtest(STRATEGY, tqqq, fx_dict, fx_sorted,
                                  SEED_KRW, False, 0, 50)

    minus10_buys = [b for b in stats['buy_log'] if b['level'] == -10]
    assert len(minus10_buys) == 1, f"-10% 레벨 매수가 {len(minus10_buys)}회 발생 (기대: 1회)"


# ── 4. 신고가 갱신 후 레벨 리셋 ───────────────────────
def test_level_reset_on_new_peak():
    """신고가 갱신 후 동일 MDD 구간에서 다시 매수 가능해야 한다"""
    # Day2: $45 (-10% → 매수), Day3: $55 (신고가 → 레벨 리셋), Day4: $49.5 (-10% of $55 → 재매수)
    tqqq = make_tqqq([50.0, 45.0, 55.0, 49.5])
    fx_dict, fx_sorted = make_fx_dict(tqqq)
    history, stats = run_backtest(STRATEGY, tqqq, fx_dict, fx_sorted,
                                  SEED_KRW, False, 0, 50)

    minus10_buys = [b for b in stats['buy_log'] if b['level'] == -10]
    assert len(minus10_buys) == 2, f"-10% 레벨 매수가 {len(minus10_buys)}회 (기대: 2회)"
    # 리밸런싱은 밴드 초과 여부에 따라 발생 안 할 수 있음 → 별도 테스트(test_rebalance_band_*)에서 검증


# ── 5. 리밸런싱 70/30 비율 검증 ───────────────────────
def test_rebalancing_ratio():
    """신고가 갱신 + 밴드 초과 시 TQQQ 약 70% / 현금 약 30% 복원 (±2% 허용)"""
    # $50 → $100 (100% 상승): 리밸런싱 전 TQQQ 비율 ≈ 82% → 밴드(5%) 초과 → 리밸런싱 발생
    tqqq = make_tqqq([50.0, 100.0])
    fx_dict, fx_sorted = make_fx_dict(tqqq)
    history, stats = run_backtest(STRATEGY, tqqq, fx_dict, fx_sorted,
                                  SEED_KRW, False, 0, 50,
                                  rebalance_band=0.05)

    assert stats['rebalance_count'] >= 1, "밴드 초과했는데 리밸런싱 미발생"

    h = history[-1]
    tqqq_value = h['tqqq_shares'] * 100.0 * FX
    cash_krw   = h['cash_krw']
    total      = tqqq_value + cash_krw
    tqqq_ratio = tqqq_value / total

    assert 0.68 <= tqqq_ratio <= 0.72, f"리밸런싱 후 TQQQ 비율 이상: {tqqq_ratio:.3f} (기대: 0.68~0.72)"


# ── 6. 현금 부족 시 가능한 만큼만 매수 ───────────────
def test_cash_exhaustion():
    """현금이 바닥나도 음수가 되지 않고, 발생한 매수는 항상 1주 이상"""
    small_seed = 500_000  # 50만원 (현금풀 약 15만원 → 금방 소진)
    # 연속 하락으로 여러 레벨 동시 진입
    tqqq = make_tqqq([50.0, 30.0])
    fx_dict, fx_sorted = make_fx_dict(tqqq)
    history, stats = run_backtest(STRATEGY, tqqq, fx_dict, fx_sorted,
                                  small_seed, False, 0, 50)

    assert history[-1]['cash_krw'] >= 0, "현금풀이 음수가 됨"
    for b in stats['buy_log']:
        assert b['shares'] >= 1, f"0주 매수 발생: {b}"


# ── 7. 금고 투입 시점 검증 ────────────────────────────
def test_vault_trigger():
    """vault_trigger=50 설정 → MDD -55% 이하에서 금고 매수 발생"""
    # $50 → $22 = MDD -56% → make_vault_table(50) 첫 레벨 -55% 진입
    tqqq = make_tqqq([50.0, 22.0])
    fx_dict, fx_sorted = make_fx_dict(tqqq)
    history, stats = run_backtest(STRATEGY, tqqq, fx_dict, fx_sorted,
                                  SEED_KRW, True, 3_000_000, 50)

    assert stats['vault_buy_count'] >= 1, "금고 매수 미발생"
    vault_buys = [b for b in stats['buy_log'] if b['source'] == '금고']
    assert len(vault_buys) >= 1


# ── 8. 상승장 매수 0회 ────────────────────────────────
def test_no_buy_in_uptrend():
    """전고점을 계속 갱신하는 상승장 → 분할매수 0회"""
    tqqq = make_tqqq([50.0, 52.0, 54.0, 56.0, 58.0, 60.0])
    fx_dict, fx_sorted = make_fx_dict(tqqq)
    history, stats = run_backtest(STRATEGY, tqqq, fx_dict, fx_sorted,
                                  SEED_KRW, False, 0, 50)

    assert stats['buy_count']       == 0, f"상승장에서 매수 발생: {stats['buy_count']}회"
    assert stats['vault_buy_count'] == 0


# ── 11. 리밸런싱 밴드: 소폭 상승 → 리밸런싱 안 함 ────
def test_rebalance_band_no_trigger():
    """5% 밴드 설정 시 소폭 신고가(TQQQ 비율 밴드 내) → 리밸런싱 없음"""
    # $50 → $60 (20% 상승): 리밸런싱 전 TQQQ 비율 ≈ 73.3% → 밴드(5%) 이내 → 리밸런싱 없음
    tqqq = make_tqqq([50.0, 60.0])
    fx_dict, fx_sorted = make_fx_dict(tqqq)
    history, stats = run_backtest(STRATEGY, tqqq, fx_dict, fx_sorted,
                                  SEED_KRW, False, 0, 50,
                                  rebalance_band=0.05)

    assert stats['rebalance_count'] == 0, \
        f"밴드 내 소폭 상승에서 리밸런싱 발생: {stats['rebalance_count']}회"


# ── 12. 리밸런싱 밴드: 대폭 상승 → 리밸런싱 함 ─────
def test_rebalance_band_triggers():
    """5% 밴드 설정 시 대폭 신고가(TQQQ 비율 밴드 초과) → 리밸런싱 발생"""
    # $50 → $100 (100% 상승): 리밸런싱 전 TQQQ 비율 ≈ 82% → 밴드(5%) 초과 → 리밸런싱 발생
    tqqq = make_tqqq([50.0, 100.0])
    fx_dict, fx_sorted = make_fx_dict(tqqq)
    history, stats = run_backtest(STRATEGY, tqqq, fx_dict, fx_sorted,
                                  SEED_KRW, False, 0, 50,
                                  rebalance_band=0.05)

    assert stats['rebalance_count'] >= 1, "밴드 초과 대폭 상승에서 리밸런싱 미발생"


# ── 13. 갭다운: 통과한 모든 레벨 소급 매수 ──────────
def test_gap_down_all_levels():
    """$50 → $35 (-30%) 갭다운 시 -5%~-30% 모든 레벨을 현재가에 소급 매수"""
    tqqq = make_tqqq([50.0, 35.0])
    fx_dict, fx_sorted = make_fx_dict(tqqq)
    history, stats = run_backtest(STRATEGY, tqqq, fx_dict, fx_sorted,
                                  SEED_KRW, False, 0, 50)

    # -5%, -10%, -15%, -20%, -25%, -30% → 6개 레벨 모두 트리거 (더 좋은 가격에 약정 이행)
    assert stats['buy_count'] == 6, f"갭다운 시 레벨 매수 {stats['buy_count']}회 (기대: 6회)"
    levels = [b['level'] for b in stats['buy_log']]
    assert -30 in levels and -5 in levels, "모든 중간 레벨이 매수됐는지 확인"


# ── 9. make_vault_table 레벨 검증 ────────────────────
def test_make_vault_table():
    """vault_trigger=50 → 금고 레벨이 -55, -60, -65, -70, -75, -80"""
    table = make_vault_table(50)
    levels = [lvl for lvl, _ in table]
    assert levels == [-55, -60, -65, -70, -75, -80], f"금고 레벨 오류: {levels}"
    ratios = [r for _, r in table]
    assert abs(sum(ratios) - 1.0) < 1e-9, f"금고 비율 합계가 1이 아님: {sum(ratios)}"


# ── 10. get_fx 폴백 검증 ─────────────────────────────
def test_get_fx_fallback():
    """해당 날짜 환율 없으면 직전 날짜 환율 반환, 아무것도 없으면 1350"""
    fx_dict   = {'2022-01-03': 1300.0, '2022-01-04': 1310.0}
    fx_sorted = sorted(fx_dict.keys())

    assert get_fx(fx_dict, fx_sorted, '2022-01-03') == 1300.0
    assert get_fx(fx_dict, fx_sorted, '2022-01-05') == 1310.0  # 직전 날짜
    assert get_fx({}, [], '2022-01-01') == 1350                # 폴백
