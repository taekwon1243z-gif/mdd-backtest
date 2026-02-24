import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.font_manager as fm
import os

# Mac 한글 폰트 설정
plt.rcParams['font.family'] = 'AppleGothic'
plt.rcParams['axes.unicode_minus'] = False

# 세 전략 데이터 로드
strategies = {}
for name in ['초반', '중반', '후반']:
    with open(f'backtest_{name}.json', 'r') as f:
        strategies[name] = json.load(f)

dates = [h['date'] for h in strategies['초반']]
hold  = [h['hold_total'] for h in strategies['초반']]

xticks_idx = list(range(0, len(dates), len(dates)//8))
xtick_labels = [dates[i][:7] for i in xticks_idx]

fig, ax = plt.subplots(figsize=(16, 8))
fig.patch.set_facecolor('#1a1a2e')
ax.set_facecolor('#16213e')

colors = {'초반': '#e74c3c', '중반': '#f39c12', '후반': '#2ecc71'}
for name, data in strategies.items():
    totals = [h['total'] for h in data]
    ax.plot(range(len(dates)), totals,
            label=f'{name} 집중형  최종 ${totals[-1]:,.0f}',
            color=colors[name], linewidth=2.5)

ax.plot(range(len(dates)), hold,
        label=f'단순 홀딩  최종 ${hold[-1]:,.0f}',
        color='#74b9ff', linewidth=2, linestyle='--', alpha=0.8)

# 폭락 구간 음영
crash_start = dates.index('2022-01-03')
crash_end = next(i for i, d in enumerate(dates) if d >= '2022-10-01')
ax.axvspan(crash_start, crash_end, alpha=0.15, color='red', label='폭락 구간')

ax.set_xticks(xticks_idx)
ax.set_xticklabels(xtick_labels, rotation=45, color='white', fontsize=11)
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'${x:,.0f}'))
ax.tick_params(colors='white')
ax.yaxis.label.set_color('white')
ax.xaxis.label.set_color('white')

for spine in ax.spines.values():
    spine.set_edgecolor('#444')

ax.set_title('MDD 방어법 전략 비교  (초기 $10,000)', fontsize=18, color='white', pad=20, fontweight='bold')
ax.set_xlabel('날짜', fontsize=13, color='white')
ax.set_ylabel('자산 ($)', fontsize=13, color='white')

legend = ax.legend(fontsize=12, facecolor='#0f3460', labelcolor='white',
                   edgecolor='#444', loc='upper left')
ax.grid(True, alpha=0.2, color='white')

# 시작/최저/최종 값 표시
ax.axhline(y=10000, color='white', linewidth=0.8, linestyle=':', alpha=0.5)
ax.text(5, 10300, '시작 $10,000', color='white', fontsize=10, alpha=0.7)

plt.tight_layout()
plt.savefig('backtest_chart.png', dpi=150, facecolor='#1a1a2e')
print('차트 저장 완료: backtest_chart.png')
