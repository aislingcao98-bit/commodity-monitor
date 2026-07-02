"""
价差均值回归策略回测模块

对每组价差，模拟 Z-Score 偏离后的均值回归交易：
  |Z| ≥ threshold → 入场（做多/做空价差）
  Z 回归到 exit_z → 出场
  输出：汇总表、收益率曲线、交易明细

用法:
    python3 backtest.py                          # 默认参数回测
    python3 backtest.py --threshold 2.0           # 更严格入场阈值
    python3 backtest.py --threshold 1.5 --cost 10 # 含交易成本
    python3 backtest.py --spread PP-LPG           # 只看单组价差
"""

import argparse
import warnings

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path

warnings.filterwarnings("ignore")

# ── 路径 ──
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "backtest_results"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── 价差元信息（与 dashboard.py 同步） ──
SPREAD_FORMULAS = {
    "沥青-原油": "沥青 - 原油",
    "燃油-原油": "燃油 - 原油",
    "原油-LPG": "原油 - LPG",
    "PP-LPG": "PP - 1.2×LPG",
    "PP-原油": "PP - 原油",
    "PE-原油": "PE - 原油",
    "PP-PE": "PP - PE",
    "PX-原油": "PX - 原油",
    "PTA-PX": "PTA - 0.655×PX",
    "EB-BZ": "EB - 0.8×纯苯",
    "EB-原油": "EB - 原油",
    "BZ-原油": "纯苯 - 原油",
    "PTA-EG": "PTA - EG",
    "EG-原油": "EG - 原油",
    "PP-3MA": "PP - 3.0×甲醇",
    "MA-原油": "甲醇 - 原油",
}

SPREAD_MEANINGS = {
    "沥青-原油": "沥青裂解利润",
    "燃油-原油": "燃料油裂解利润",
    "原油-LPG": "原油与LPG相对强弱",
    "PP-LPG": "PDH装置利润",
    "PP-原油": "PP一体化利润",
    "PE-原油": "PE一体化利润",
    "PP-PE": "聚丙烯 vs 聚乙烯",
    "PX-原油": "PX一体化利润",
    "PTA-PX": "PTA加工费",
    "EB-BZ": "苯乙烯加工利润",
    "EB-原油": "苯乙烯一体化利润",
    "BZ-原油": "纯苯一体化利润",
    "PTA-EG": "聚酯原料价差",
    "EG-原油": "乙二醇一体化利润",
    "PP-3MA": "MTO/MTP装置利润",
    "MA-原油": "甲醇相对原油价值",
}

SPREAD_CATEGORIES = {
    "原油链": ["沥青-原油", "燃油-原油", "原油-LPG"],
    "烯烃链": ["PP-LPG", "PP-原油", "PE-原油", "PP-PE"],
    "芳烃链": ["PX-原油", "PTA-PX", "EB-BZ", "EB-原油", "BZ-原油"],
    "聚酯链": ["PTA-EG", "EG-原油"],
    "甲醇链": ["PP-3MA", "MA-原油"],
}
# ── 方向偏好配置（基于产业逻辑） ──
# "both"        - 双向均值回归
# "short_only"  - 只做空（适合产能过剩品种）
# "long_only"   - 只做多（适合供应刚性品种）
DIRECTION_OVERRIDES = {
    "PP-LPG": "short_only",    # PDH利润：PP持续过剩，逢高做空利润
    "PP-3MA": "short_only",    # MTO利润：同上逻辑
    "PP-原油": "short_only",   # PP一体化利润过剩，做空利润
    "PE-原油": "short_only",   # PE一体化利润过剩，做空利润
    "PP-PE": "short_only",     # 聚烯烃整体过剩，做空价差
}




def spread_chain(name: str) -> str:
    for cat, spreads in SPREAD_CATEGORIES.items():
        if name in spreads:
            return cat
    return ""


# ════════════════════════════
#  1. 滚动 Z-Score（无未来数据泄漏）
# ════════════════════════════

def compute_z_history(spreads: pd.DataFrame, lookback: int = 252) -> pd.DataFrame:
    """
    计算每组价差的历史滚动 Z-Score。
    第 t 天的 Z 值基于 [t-lookback, t-1] 窗口的均值和标准差计算。
    前 lookback 天用 expanding 窗口 bootstrap。
    """
    z_all = pd.DataFrame(index=spreads.index, columns=spreads.columns, dtype=float)

    for col in spreads.columns:
        s = spreads[col].dropna()
        if len(s) < lookback + 10:
            continue

        roll_mean = s.rolling(lookback, min_periods=lookback).mean().shift(1)
        roll_std = s.rolling(lookback, min_periods=lookback).std().shift(1)

        # 前 lookback 天用 expanding 代替
        exp_mean = s.expanding(min_periods=lookback).mean().shift(1)
        exp_std = s.expanding(min_periods=lookback).std().shift(1)

        s_mean = roll_mean.fillna(exp_mean)
        s_std = roll_std.fillna(exp_std)

        z = (s - s_mean) / s_std
        z = z.replace([np.inf, -np.inf], np.nan)
        z_all.loc[z.index, col] = z

    return z_all


# ════════════════════════════
#  2. 单组价差回测
# ════════════════════════════

def backtest_single(
    spread_series: pd.Series,
    z_series: pd.Series,
    entry_threshold: float = 1.5,
    exit_z: float = 0.0,
    cost_per_unit: float = 0.0,
    direction: str = "both",
) -> dict:
    """
    对一组价差执行均值回归回测。

    状态机:
      flat(0) → |Z| ≥ entry_threshold 入场 (long/short)
      持仓中  → Z 穿越 exit_z 出场

    返回:
      { trades, daily_pnl, stats }
    """
    df = pd.DataFrame({"spread": spread_series, "z": z_series}).dropna()
    if len(df) < 100:
        return None

    trades = []
    daily_pnl = pd.Series(0.0, index=df.index)
    position = 0  # 0: flat, 1: long, -1: short
    entry_price = 0.0
    entry_date = None
    dir_label = ""

    spread_prev = df["spread"].iloc[0]

    for i in range(1, len(df)):
        date = df.index[i]
        z = df["z"].iloc[i]
        sp = df["spread"].iloc[i]
        sp_prev = df["spread"].iloc[i - 1]

        # ── 状态机 ──
        if position == 0:
            if z < -entry_threshold and direction in ("both", "long_only"):
                position = 1
                entry_price = sp
                entry_date = date
                dir_label = "LONG"
            elif z > entry_threshold and direction in ("both", "short_only"):
                position = -1
                entry_price = sp
                entry_date = date
                dir_label = "SHORT"
        else:
            # 已持仓：检查出场条件
            exit_signal = False
            if position == 1 and z >= exit_z:
                exit_signal = True
            elif position == -1 and z <= exit_z:
                exit_signal = True

            if exit_signal:
                pnl = (sp - entry_price) if position == 1 else (entry_price - sp)
                # 扣交易成本（入场+出场）
                pnl -= cost_per_unit * 2
                trades.append({
                    "入场日期": entry_date,
                    "出场日期": date,
                    "方向": dir_label,
                    "入场价": round(entry_price, 1),
                    "出场价": round(sp, 1),
                    "盈亏": round(pnl, 1),
                    "持有天数": (date - entry_date).days,
                })
                position = 0
                entry_price = 0.0
                entry_date = None
                dir_label = ""

        # 日度 PnL（用于 Sharpe / 回撤计算）
        if position == 1:
            daily_pnl.iloc[i] = sp - sp_prev
        elif position == -1:
            daily_pnl.iloc[i] = -(sp - sp_prev)

        spread_prev = sp

    # 未平仓 → 按最后价格强制平仓
    if position != 0:
        last_date = df.index[-1]
        last_price = df["spread"].iloc[-1]
        pnl = (last_price - entry_price) if position == 1 else (entry_price - last_price)
        pnl -= cost_per_unit * 2
        trades.append({
            "入场日期": entry_date,
            "出场日期": last_date,
            "方向": dir_label,
            "入场价": round(entry_price, 1),
            "出场价": round(last_price, 1),
            "盈亏": round(pnl, 1),
            "持有天数": (last_date - entry_date).days,
        })

    # ── 统计指标 ──
    stats = compute_stats(trades, daily_pnl)

    return {
        "trades": pd.DataFrame(trades) if trades else pd.DataFrame(),
        "daily_pnl": daily_pnl,
        "stats": stats,
    }


# ════════════════════════════
#  3. 统计指标计算
# ════════════════════════════

def compute_stats(trades: list, daily_pnl: pd.Series) -> dict:
    """计算回测统计指标"""
    n_trades = len(trades)

    if n_trades == 0:
        return {
            "交易次数": 0, "胜率": 0, "总盈亏": 0,
            "年化收益率": 0, "Sharpe": 0, "最大回撤": 0,
            "平均持有天数": 0, "利润因子": 0, "平均盈亏": 0,
        }

    pnls = [t["盈亏"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = len(wins) / n_trades * 100
    total_pnl = sum(pnls)
    avg_pnl = total_pnl / n_trades
    avg_holding = sum(t["持有天数"] for t in trades) / n_trades

    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # 年化收益率 & Sharpe（基于日度 PnL）
    daily_returns = daily_pnl
    annual_return = daily_returns.mean() * 252
    daily_std = daily_returns.std()
    sharpe = (daily_returns.mean() / daily_std * np.sqrt(252)) if daily_std > 0 else 0

    # 最大回撤（基于累计盈亏曲线）
    cum = daily_returns.cumsum()
    peak = cum.expanding().max()
    dd = (cum - peak)
    max_dd = dd.min()

    return {
        "交易次数": n_trades,
        "胜率": round(win_rate, 1),
        "总盈亏": round(total_pnl, 1),
        "年化收益率": round(annual_return, 1),
        "Sharpe": round(sharpe, 2),
        "最大回撤": round(max_dd, 1),
        "平均持有天数": round(avg_holding, 1),
        "利润因子": round(profit_factor, 2) if profit_factor != float("inf") else "∞",
        "平均盈亏": round(avg_pnl, 1),
    }


# ════════════════════════════
#  4. 整体运行
# ════════════════════════════

def run_all(spreads: pd.DataFrame, **params) -> dict:
    """对所有价差运行回测"""
    print("计算滚动 Z-Score...", end=" ", flush=True)
    z_all = compute_z_history(spreads, lookback=params.get("lookback", 252))
    print(f"完成（{z_all.shape[1]} 组 × {z_all.shape[0]} 天）")

    results = {}
    for col in spreads.columns:
        if col not in z_all.columns:
            continue
        z_valid = z_all[col].dropna()
        s_valid = spreads[col].loc[z_valid.index]
        if len(s_valid) < 100:
            continue

        result = backtest_single(
            s_valid, z_valid,
            entry_threshold=params.get("entry_threshold", 1.5),
            exit_z=params.get("exit_z", 0.0),
            cost_per_unit=params.get("cost_per_unit", 0.0),
            direction=DIRECTION_OVERRIDES.get(col, params.get("direction", "both")),
        )
        if result:
            results[col] = result

    return results


# ════════════════════════════
#  5. 可视化
# ════════════════════════════

def plot_spread_backtest(name: str, spread_series: pd.Series, z_series: pd.Series,
                         result: dict, params: dict) -> go.Figure:
    """三面板图：价差走势 + Z-Score + 累计盈亏"""
    df = pd.DataFrame({"spread": spread_series, "z": z_series}).dropna()

    trades = result["trades"]
    daily_pnl = result["daily_pnl"]
    cum_pnl = daily_pnl.cumsum()

    # 入场/出场标记
    entry_dates = []
    entry_y = []
    exit_dates = []
    exit_y = []

    if not trades.empty:
        for _, t in trades.iterrows():
            entry_dates.append(t["入场日期"])
            entry_y.append(t["入场价"])
            exit_dates.append(t["出场日期"])
            exit_y.append(t["出场价"])

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[2.0, 1.0, 1.2],
        subplot_titles=(
            f"价差走势（含入场/出场标记）",
            "Z-Score",
            "累计盈亏"
        ),
    )

    # 面板1: 价差
    fig.add_trace(
        go.Scatter(x=df.index, y=df["spread"], mode="lines",
                   line=dict(color="#1a73e8", width=1.5), name="价差"),
        row=1, col=1,
    )
    if entry_dates:
        fig.add_trace(
            go.Scatter(x=entry_dates, y=entry_y, mode="markers",
                       marker=dict(color="#27ae60", size=8, symbol="triangle-up"),
                       name="入场"),
            row=1, col=1,
        )
    if exit_dates:
        fig.add_trace(
            go.Scatter(x=exit_dates, y=exit_y, mode="markers",
                       marker=dict(color="#e74c3c", size=8, symbol="x"),
                       name="出场"),
            row=1, col=1,
        )

    # 面板2: Z-Score
    entry_th = params.get("entry_threshold", 1.5)
    exit_z = params.get("exit_z", 0.0)

    fig.add_trace(
        go.Scatter(x=df.index, y=df["z"], mode="lines",
                   line=dict(color="#8e44ad", width=1.5), name="Z-Score"),
        row=2, col=1,
    )
    fig.add_hline(y=entry_th, line_dash="dash", line_color="#e74c3c",
                  annotation_text=f"入场阈值 ±{entry_th}", row=2, col=1)
    fig.add_hline(y=-entry_th, line_dash="dash", line_color="#e74c3c", row=2, col=1)
    fig.add_hline(y=exit_z, line_dash="dot", line_color="#27ae60",
                  annotation_text=f"出场 {exit_z}", row=2, col=1)

    # 面板3: 累计盈亏
    cum_color = "#27ae60" if cum_pnl.iloc[-1] >= 0 else "#e74c3c"
    fig.add_trace(
        go.Scatter(x=cum_pnl.index, y=cum_pnl, mode="lines",
                   fill="tozeroy", line=dict(color=cum_color, width=2),
                   name="累计盈亏"),
        row=3, col=1,
    )

    chain = spread_chain(name)
    fig.update_layout(
        height=700, margin=dict(l=60, r=30, t=40, b=30),
        title_text=f"{name}（{chain}）均值回归回测",
        hovermode="x unified",
        showlegend=False,
    )
    fig.update_yaxes(title_text="元/吨", row=1, col=1)
    fig.update_yaxes(title_text="Z-Score", row=2, col=1)
    fig.update_yaxes(title_text="累计盈亏", row=3, col=1)

    return fig


# ════════════════════════════
#  6. 控制台输出
# ════════════════════════════

def print_summary(results: dict):
    """打印汇总表格"""
    rows = []
    for name, r in results.items():
        s = r["stats"]
        chain = spread_chain(name)
        rows.append({
            "价差": name,
            "产业链": chain,
            "交易次数": s["交易次数"],
            "胜率%": s["胜率"],
            "总盈亏": s["总盈亏"],
            "年化收益": s["年化收益率"],
            "Sharpe": s["Sharpe"],
            "最大回撤": s["最大回撤"],
            "平均持有天数": s["平均持有天数"],
            "利润因子": s["利润因子"],
        })

    summary = pd.DataFrame(rows)
    pd.set_option("display.max_columns", 12)
    pd.set_option("display.width", 160)
    pd.set_option("display.max_colwidth", 20)

    print("\n" + "=" * 100)
    print("📊  均值回归回测结果汇总")
    print("=" * 100)
    print(summary.to_string(index=False))
    print("=" * 100)

    # 综合统计
    total_trades = summary["交易次数"].sum()
    avg_winrate = summary["胜率%"].mean()
    total_pnl = summary["总盈亏"].sum()
    avg_sharpe = summary["Sharpe"].mean()
    print(f"\n  共计 {len(results)} 组价差 · {total_trades} 笔交易")
    print(f"  平均胜率 {avg_winrate:.1f}% · 总盈亏 {total_pnl:.0f} · 平均 Sharpe {avg_sharpe:.2f}")


# ════════════════════════════
#  7. 主入口
# ════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="价差均值回归策略回测")
    parser.add_argument("--threshold", type=float, default=1.5, help="入场 Z-Score 阈值")
    parser.add_argument("--exit-z", type=float, default=0.0, help="出场 Z-Score")
    parser.add_argument("--lookback", type=int, default=252, help="滚动窗口天数")
    parser.add_argument("--cost", type=float, default=0.0, help="每手交易成本（元/吨）")
    parser.add_argument("--spread", type=str, default=None, help="仅回测单组价差")
    parser.add_argument("--no-plot", action="store_true", help="不生成图表")
    parser.add_argument("--direction",
        choices=["both", "long_only", "short_only"],
        default="both",
        help="全局交易方向（被 DIRECTION_OVERRIDES 覆盖）")
    args = parser.parse_args()

    params = {
        "entry_threshold": args.threshold,
        "exit_z": args.exit_z,
        "lookback": args.lookback,
        "cost_per_unit": args.cost,
        "direction": args.direction,
    }

    print(f"🔄  价差均值回归回测")
    print(f"   参数: 阈值={args.threshold} · 出场Z={args.exit_z} · 窗口={args.lookback}d · 成本={args.cost} · 方向={args.direction}")

    print()

    # 读取价差数据
    csv_path = DATA_DIR / "spreads.csv"
    if not csv_path.exists():
        print(f"[错误] 价差数据不存在: {csv_path}")
        return
    spreads = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    print(f"  加载价差数据: {spreads.shape[1]} 组 × {len(spreads)} 天")

    if args.spread:
        if args.spread not in spreads.columns:
            print(f"[错误] 价差 '{args.spread}' 不存在，可用: {list(spreads.columns)}")
            return
        spreads = spreads[[args.spread]]

    # 运行回测
    results = run_all(spreads, **params)

    if not results:
        print("未产生任何交易信号")
        return

    # 打印汇总
    print_summary(results)

    # 保存图表
    if not args.no_plot:
        z_all = compute_z_history(spreads, lookback=params["lookback"])
        for name, r in results.items():
            z_valid = z_all[name].dropna()
            s_valid = spreads[name].loc[z_valid.index]
            fig = plot_spread_backtest(name, s_valid, z_valid, r, params)
            html_path = OUTPUT_DIR / f"{name}.html"
            fig.write_html(html_path, include_plotlyjs="cdn")
            print(f"  图表已保存: {html_path}")

        # 保存交易明细
        all_trades = []
        for name, r in results.items():
            if not r["trades"].empty:
                t = r["trades"].copy()
                t.insert(0, "价差", name)
                all_trades.append(t)
        if all_trades:
            combined = pd.concat(all_trades).reset_index(drop=True)
            combined.to_csv(OUTPUT_DIR / "all_trades.csv", index=False)
            print(f"  交易明细已保存: {OUTPUT_DIR / 'all_trades.csv'}")

    print("\n✅ 回测完成")


if __name__ == "__main__":
    main()
