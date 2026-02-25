from data import get_tqqq_price
from mdd_engine import get_action
import json

def update_peak(current_price):
    with open("config.json", "r") as f:
        config = json.load(f)
    if current_price > config["peak_price"]:
        config["peak_price"] = current_price
        with open("config.json", "w") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print(f"📈 새 전고점 갱신: ${current_price}")

def run():
    print("=== MDD 방어법 봇 실행 ===")
    date, price = get_tqqq_price()
    print(f"날짜: {date} / TQQQ: ${price}")

    update_peak(price)

    actions, mdd = get_action(price, date)
    print(f"현재 MDD: {mdd}%\n")

    for action in actions:
        print("─" * 30)
        print(action["message"])

if __name__ == "__main__":
    run()
