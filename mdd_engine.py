import json

# 후반 집중형 매수 구간 테이블
# {MDD 구간: 현금 풀에서 사용할 비율}
STRATEGY = {
    -5:  0.01,
    -10: 0.02,
    -15: 0.02,
    -20: 0.03,
    -25: 0.05,
    -30: 0.08,
    -35: 0.10,
    -40: 0.13,
    -45: 0.14,
    -50: 0.14,
}

def load_config():
    with open("config.json", "r") as f:
        return json.load(f)

def load_state():
    with open("state.json", "r") as f:
        return json.load(f)

def save_state(state):
    with open("state.json", "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def calc_mdd(current_price, peak_price):
    if peak_price == 0:
        return 0
    return round((current_price - peak_price) / peak_price * 100, 2)

def get_action(current_price, current_date):
    config = load_config()
    state = load_state()

    peak = config["peak_price"]
    total_seed = config["total_seed"]
    cash_ratio = config["cash_ratio"]
    wallet = config["wallet"]

    cash_pool = total_seed * cash_ratio  # 현금 풀 총액
    mdd = calc_mdd(current_price, peak)
    mdd_int = int(mdd)  # 소수점 버림 (전략 구간은 정수)

    actions = []

    # 전고점 회복 체크
    if current_price >= peak and peak > 0:
        actions.append({
            "type": "리밸런싱",
            "message": f"🎯 전고점 회복! 현재가 ${current_price}\n리밸런싱 필요: TQQQ 일부 매도 후 현금 {int(cash_ratio*100)}% 복원"
        })
        return actions, mdd

    # 매수 구간 체크
    for level in sorted(STRATEGY.keys(), reverse=True):
        if mdd_int <= level and level not in state["bought_levels"]:
            buy_ratio = STRATEGY[level]
            buy_amount = cash_pool * buy_ratio
            actions.append({
                "type": "매수",
                "level": level,
                "message": (
                    f"📉 TQQQ MDD 알림\n"
                    f"현재가: ${current_price}\n"
                    f"전고점: ${peak}\n"
                    f"현재 MDD: {mdd}% → {level}% 구간 진입\n\n"
                    f"💰 매수 권장 금액: ${round(buy_amount, 2)}\n"
                    f"(현금 풀의 {int(buy_ratio*100)}%)"
                )
            })

    if not actions:
        actions.append({
            "type": "대기",
            "message": f"⏳ 대기 중\n현재가: ${current_price} / MDD: {mdd}%\n매수 구간 아님"
        })

    return actions, mdd
