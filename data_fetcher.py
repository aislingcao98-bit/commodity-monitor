"""
能化品种数据获取模块
拉取国内期货主力合约历史数据 + 计算核心价差
数据源：akshare (新浪财经)
"""

import akshare as ak
import pandas as pd
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

# 项目根目录
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# 品种配置：代码 -> (名称, 交易所, 品类)
SYMBOLS = {
    "SC0": ("原油", "上期所", "原油"),
    "PG0": ("LPG", "大商所", "液化气"),
    "BU0": ("沥青", "上期所", "沥青"),
    "FU0": ("燃油", "上期所", "燃料油"),
    "PP0": ("PP", "大商所", "聚丙烯"),
    "L0":  ("PE", "大商所", "聚乙烯"),
    "TA0": ("PTA", "郑商所", "精对苯二甲酸"),
    "MA0": ("甲醇", "郑商所", "甲醇"),
    "PX0": ("PX", "郑商所", "对二甲苯"),
    "EG0": ("EG", "大商所", "乙二醇"),
    "EB0": ("EB", "大商所", "苯乙烯"),
    "BZ0": ("纯苯", "大商所", "纯苯"),
}


def fetch_single(symbol: str) -> pd.DataFrame:
    """拉取单个品种主力合约日度数据"""
    try:
        df = ak.futures_zh_daily_sina(symbol=symbol)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception as e:
        print(f"  [{symbol}] 拉取失败: {e}")
        return pd.DataFrame()


def fetch_all() -> dict[str, pd.DataFrame]:
    """拉取全部品种数据，返回 {代码: DataFrame}"""
    results = {}
    for sym, (name, exchange, category) in SYMBOLS.items():
        print(f"正在拉取 {sym} {name} ({exchange})...")
        df = fetch_single(sym)
        if not df.empty:
            results[sym] = df
            # 存 CSV
            csv_path = DATA_DIR / f"{sym}.csv"
            df.to_csv(csv_path, index=False)
            print(f"  -> {len(df)} 条, {df['date'].min().date()} ~ {df['date'].max().date()}, 已保存")
        else:
            print(f"  -> 跳过")
    return results


def build_price_table(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    构建统一价格表：日期为索引，每个品种收盘价为列
    保留所有日期（新品种上市前的日期为 NaN）
    """
    closes = {}
    volumes = {}
    for sym, df in data.items():
        name = SYMBOLS[sym][0]
        closes[name] = df.set_index("date")["close"]
        volumes[name] = df.set_index("date")["volume"]

    price_df = pd.DataFrame(closes)
    volume_df = pd.DataFrame(volumes).reindex(price_df.index)

    # 原油单位换算：元/桶 → 元/吨（1吨 ≈ 7.33桶，国际均值）
    if "原油" in price_df.columns:
        price_df["原油"] = (price_df["原油"] * 7.33).round(0)

    return price_df, volume_df


def calculate_spreads(price_df: pd.DataFrame) -> pd.DataFrame:
    """
    计算核心价差（按产业链分类）
    """
    spreads = pd.DataFrame(index=price_df.index)

    # ==================== 🛢️ 原油链 ====================
    # 1. 沥青-原油 — 沥青裂解利润
    if "原油" in price_df.columns and "沥青" in price_df.columns:
        spreads["沥青-原油"] = price_df["沥青"] - price_df["原油"]

    # 2. 燃油-原油 — 燃料油裂解利润
    if "原油" in price_df.columns and "燃油" in price_df.columns:
        spreads["燃油-原油"] = price_df["燃油"] - price_df["原油"]

    # 3. 原油-LPG — 原油与LPG相对强弱
    if "LPG" in price_df.columns and "原油" in price_df.columns:
        spreads["原油-LPG"] = price_df["原油"] - price_df["LPG"]

    # ==================== 🧪 烯烃链 ====================
    # 4. PP-LPG — PDH 装置利润
    if "LPG" in price_df.columns and "PP" in price_df.columns:
        spreads["PP-LPG"] = price_df["PP"] - 1.2 * price_df["LPG"]

    # 5. PP-原油 — PP一体化利润（石脑油路线）
    if "原油" in price_df.columns and "PP" in price_df.columns:
        spreads["PP-原油"] = price_df["PP"] - price_df["原油"]

    # 6. PE-原油 — PE一体化利润（石脑油路线）
    if "原油" in price_df.columns and "PE" in price_df.columns:
        spreads["PE-原油"] = price_df["PE"] - price_df["原油"]

    # 7. PP-PE — 聚丙烯 vs 聚乙烯
    if "PP" in price_df.columns and "PE" in price_df.columns:
        spreads["PP-PE"] = price_df["PP"] - price_df["PE"]

    # ==================== 🌸 芳烃链 ====================
    # 8. PX-原油 — PX一体化利润（原油→石脑油→PX）
    if "原油" in price_df.columns and "PX" in price_df.columns:
        spreads["PX-原油"] = price_df["PX"] - price_df["原油"]

    # 9. PTA-PX — PTA加工费（PX→PTA的加工利润）
    if "PTA" in price_df.columns and "PX" in price_df.columns:
        spreads["PTA-PX"] = price_df["PTA"] - 0.655 * price_df["PX"]

    # 10. EB-BZ — 苯乙烯加工利润（1吨EB约消耗0.8吨纯苯）
    if "EB" in price_df.columns and "纯苯" in price_df.columns:
        spreads["EB-BZ"] = price_df["EB"] - 0.8 * price_df["纯苯"]

    # 11. EB-原油 — 苯乙烯一体化利润
    if "原油" in price_df.columns and "EB" in price_df.columns:
        spreads["EB-原油"] = price_df["EB"] - price_df["原油"]

    # 12. BZ-原油 — 纯苯一体化利润
    if "原油" in price_df.columns and "纯苯" in price_df.columns:
        spreads["BZ-原油"] = price_df["纯苯"] - price_df["原油"]

    # ==================== 👚 聚酯链 ====================
    # 13. PTA-EG — 聚酯原料价差
    if "PTA" in price_df.columns and "EG" in price_df.columns:
        spreads["PTA-EG"] = price_df["PTA"] - price_df["EG"]

    # 14. EG-原油 — 乙二醇一体化利润
    if "原油" in price_df.columns and "EG" in price_df.columns:
        spreads["EG-原油"] = price_df["EG"] - price_df["原油"]

    # ==================== 🏭 甲醇链 ====================
    # 14. PP-3MA — MTO/MTP 装置利润
    if "PP" in price_df.columns and "甲醇" in price_df.columns:
        spreads["PP-3MA"] = price_df["PP"] - 3.0 * price_df["甲醇"]

    # 15. MA-原油 — 甲醇对原油的相对价值
    if "原油" in price_df.columns and "甲醇" in price_df.columns:
        spreads["MA-原油"] = price_df["甲醇"] - price_df["原油"]

    return spreads.dropna(how="all", axis=1)


def compute_statistics(spreads: pd.DataFrame, lookback_days: int = 252) -> pd.DataFrame:
    """
    计算每组价差的统计特征（基于最近 N 个交易日）
    """
    recent = spreads.tail(lookback_days)
    stats = pd.DataFrame(index=spreads.columns)
    stats["当前值"] = spreads.iloc[-1]
    stats["均值(1年)"] = recent.mean()
    stats["标准差(1年)"] = recent.std()
    stats["Z-Score"] = (stats["当前值"] - stats["均值(1年)"]) / stats["标准差(1年)"]
    stats["历史最低"] = recent.min()
    stats["历史最高"] = recent.max()
    stats["百分位"] = recent.rank(pct=True).iloc[-1] * 100

    # 预警标记
    def alert_label(z):
        if abs(z) < 1.5:
            return "✅ 正常"
        elif abs(z) < 2.0:
            return "⚠️ 关注"
        else:
            return "🔴 偏离"

    stats["预警"] = stats["Z-Score"].apply(alert_label)
    return stats.round(2)


def main():
    print("=" * 50)
    print("能化品种数据获取 + 价差计算")
    print("=" * 50)

    # Step 1: 拉取数据
    print("\n[1/3] 拉取主力合约数据...")
    data = fetch_all()

    if not data:
        print("未获取到任何数据，退出。")
        return

    # Step 2: 构建统一价格表
    print("\n[2/3] 构建统一价格表 & 计算价差...")
    price_df, volume_df = build_price_table(data)
    price_df.to_csv(DATA_DIR / "price_table.csv")
    print(f"  价格表: {price_df.shape[0]} 天 × {price_df.shape[1]} 个品种")
    print(f"  日期范围: {price_df.index[0].date()} ~ {price_df.index[-1].date()}")

    # Step 3: 计算价差
    spreads = calculate_spreads(price_df)
    spreads.to_csv(DATA_DIR / "spreads.csv")
    print(f"  价差表: {spreads.shape[1]} 组价差")

    # 统计
    print("\n[3/3] 价差分析（近1年）...")
    stats = compute_statistics(spreads)
    stats.to_csv(DATA_DIR / "spread_stats.csv")
    print(stats.to_string())

    print(f"\n全部数据已保存到 {DATA_DIR}/")
    print("  - PG0.csv, SC0.csv, BU0.csv, FU0.csv, PP0.csv, L0.csv, TA0.csv (原始数据)")
    print("  - price_table.csv (统一价格表)")
    print("  - spreads.csv (价差数据)")
    print("  - spread_stats.csv (价差统计)")


if __name__ == "__main__":
    main()
