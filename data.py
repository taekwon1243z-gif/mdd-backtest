import yfinance as yf

def get_tqqq_price():
    ticker = yf.Ticker("TQQQ")
    hist = ticker.history(period="5d", auto_adjust=True)
    latest_price = hist["Close"].iloc[-1]
    latest_date = hist.index[-1].strftime("%Y-%m-%d")
    return latest_date, round(latest_price, 2)

if __name__ == "__main__":
    date, price = get_tqqq_price()
    print(f"날짜: {date}")
    print(f"TQQQ 수정 종가: ${price}")

