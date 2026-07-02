"""
能化品种预警邮件模块

读取价差数据 → 计算 Z-Score 偏离 → 发送 HTML 邮件通知
支持每天收盘后自动推送日报，支持三级预警分类

用法:
    python3 alert.py                            # 发送预警邮件
    python3 alert.py --dry-run                  # 只打印邮件内容，不发送
"""

import smtplib
import ssl
import argparse
import tomllib
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime
import warnings

warnings.filterwarnings("ignore")

# ── 路径 ──
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = BASE_DIR / "config.toml"

# ── 价差元信息（与 dashboard.py 保持同步） ──
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
    "沥青-原油": "沥青裂解利润（炼厂加工利润）",
    "燃油-原油": "燃料油裂解利润",
    "原油-LPG": "原油与LPG相对强弱（原料替代逻辑）",
    "PP-LPG": "PDH装置利润（1吨PP约消耗1.2吨LPG）",
    "PP-原油": "PP一体化利润（石脑油裂解路线）",
    "PE-原油": "PE一体化利润（石脑油裂解路线）",
    "PP-PE": "聚丙烯 vs 聚乙烯相对强弱",
    "PX-原油": "PX一体化利润（原油→石脑油→PX）",
    "PTA-PX": "PTA加工费（PX→PTA的加工利润，系数0.655）",
    "EB-BZ": "苯乙烯加工利润（纯苯→EB，1吨EB消耗0.8吨纯苯）",
    "EB-原油": "苯乙烯一体化利润（原油→石脑油→纯苯→EB）",
    "BZ-原油": "纯苯一体化利润（原油→石脑油→纯苯）",
    "PTA-EG": "聚酯原料价差（PTA vs 乙二醇）",
    "EG-原油": "乙二醇一体化利润",
    "PP-3MA": "MTO/MTP装置利润（1吨PP约消耗3吨甲醇）",
    "MA-原油": "甲醇对原油的相对价值（能源替代视角）",
}

SPREAD_CATEGORIES = {
    "🛢️ 原油链": ["沥青-原油", "燃油-原油", "原油-LPG"],
    "🧪 烯烃链": ["PP-LPG", "PP-原油", "PE-原油", "PP-PE"],
    "🌸 芳烃链": ["PX-原油", "PTA-PX", "EB-BZ", "EB-原油", "BZ-原油"],
    "👚 聚酯链": ["PTA-EG", "EG-原油"],
    "🏭 甲醇链": ["PP-3MA", "MA-原油"],
}


# ════════════════════════════
#  1. 配置加载
# ════════════════════════════

def load_config() -> dict:
    """读取 config.toml"""
    if not CONFIG_PATH.exists():
        print(f"[错误] 配置文件不存在: {CONFIG_PATH}")
        print("请复制 config.toml.example 为 config.toml 并填写邮箱配置")
        raise FileNotFoundError(f"config.toml not found at {CONFIG_PATH}")
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


# ════════════════════════════
#  2. 统计计算
# ════════════════════════════

def compute_stats(spreads_df: pd.DataFrame, lookback: int = 252) -> pd.DataFrame:
    """计算价差统计特征（与 dashboard.py 逻辑一致）"""
    lookback = min(lookback, len(spreads_df))
    recent = spreads_df.tail(lookback)
    s = pd.DataFrame(index=spreads_df.columns)
    s["当前值"] = spreads_df.iloc[-1]
    s["均值"] = recent.mean()
    s["标准差"] = recent.std().replace(0, pd.NA)
    s["Z-Score"] = ((s["当前值"] - s["均值"]) / s["标准差"]).round(2)
    s["Z-Score"] = s["Z-Score"].fillna(0)
    s["百分位"] = (recent.rank(pct=True).iloc[-1] * 100).fillna(50).round(1)
    return s


def classify_alerts(stats: pd.DataFrame, z_warn: float, z_alert: float) -> dict:
    """按 Z-Score 将价差分为三组"""
    high = []   # 🔴 |Z| >= z_alert
    mid = []    # ⚠️  z_warn <= |Z| < z_alert
    low = []    # ✅  |Z| < z_warn

    for name in stats.index:
        z = abs(stats.loc[name, "Z-Score"])
        if pd.isna(z):
            low.append(name)
        elif z >= z_alert:
            high.append(name)
        elif z >= z_warn:
            mid.append(name)
        else:
            low.append(name)

    return {"high": high, "mid": mid, "low": low}


# ════════════════════════════
#  3. HTML 邮件正文构建
# ════════════════════════════

def _risk_icon(z: float) -> str:
    if pd.isna(z):
        return "⬜"
    if abs(z) >= 2.0:
        return "🔴"
    if abs(z) >= 1.5:
        return "⚠️"
    return "✅"


def _chain_of(spread_name: str) -> str:
    """查找价差所属产业链"""
    for cat, spreads in SPREAD_CATEGORIES.items():
        if spread_name in spreads:
            return cat
    return ""


def _spread_row_html(name: str, row: pd.Series, highlight: bool = False) -> str:
    """生成单行价差 HTML"""
    bg = "#fff5f5" if highlight else "transparent"
    z = row["Z-Score"]
    icon = _risk_icon(z)
    chain = _chain_of(name)
    meaning = SPREAD_MEANINGS.get(name, "")
    formula = SPREAD_FORMULAS.get(name, "")

    if highlight:
        return (
            f'<tr style="background:{bg}">'
            f'  <td style="padding:10px 12px;font-weight:700;white-space:nowrap">{icon} {name}</td>'
            f'  <td style="padding:10px 12px;color:#666;font-size:0.85em">{chain}</td>'
            f'  <td style="padding:10px 12px;text-align:right;font-weight:600">{row["当前值"]:.0f}</td>'
            f'  <td style="padding:10px 12px;text-align:right;color:{"#d32f2f" if abs(z)>=2 else "#e65100"};font-weight:700">{z:+.2f}</td>'
            f'  <td style="padding:10px 12px;text-align:right">{row["百分位"]:.0f}%</td>'
            f'  <td style="padding:10px 12px;color:#888;font-size:0.85em">{meaning}</td>'
            f'</tr>'
        )
    return (
        f'<tr>'
        f'  <td style="padding:6px 12px;white-space:nowrap">{name}</td>'
        f'  <td style="padding:6px 12px;color:#666;font-size:0.85em">{chain}</td>'
        f'  <td style="padding:6px 12px;text-align:right">{row["当前值"]:.0f}</td>'
        f'  <td style="padding:6px 12px;text-align:right;color:{"#d32f2f" if abs(z)>=2 else ("#e65100" if abs(z)>=1.5 else "#333")}">{z:+.2f}</td>'
        f'  <td style="padding:6px 12px;text-align:right">{row["百分位"]:.0f}%</td>'
        f'  <td style="padding:6px 12px;color:#888;font-size:0.85em">{meaning}</td>'
        f'</tr>'
    )


def build_html_body(stats: pd.DataFrame, categories: dict, today: str) -> str:
    """构建完整的 HTML 邮件正文"""
    n_high = len(categories["high"])
    n_mid = len(categories["mid"])
    n_low = len(categories["low"])
    total = n_high + n_mid + n_low

    summary_color = "#d32f2f" if n_high > 0 else "#e65100" if n_mid > 0 else "#2e7d32"

    # ── 偏离卡片（红色 + 橙色） ──
    alert_cards = ""
    for name in categories["high"] + categories["mid"]:
        row = stats.loc[name]
        z = row["Z-Score"]
        icon = _risk_icon(z)
        chain = _chain_of(name)
        border = "#d32f2f" if abs(z) >= 2 else "#e65100"
        alert_cards += (
            f'<div style="display:inline-block;min-width:180px;margin:4px;padding:10px 14px;'
            f'border-left:4px solid {border};background:#fff5f5;border-radius:4px;'
            f'vertical-align:top;line-height:1.6">'
            f'{icon} <b>{name}</b><br>'
            f'<span style="color:#888;font-size:0.8em">{chain}</span><br>'
            f'<span style="font-size:1.4em;font-weight:700">{row["当前值"]:.0f}</span><br>'
            f'Z-Score: <b style="color:{border}">{z:+.2f}</b> · 百分位: {row["百分位"]:.0f}%'
            f'</div>'
        )

    # ── 完整统计表 ──
    table_rows = ""
    for name in stats.index:
        row = stats.loc[name]
        z = row["Z-Score"]
        highlight = (abs(z) >= 1.5)
        table_rows += _spread_row_html(name, row, highlight=highlight)

    # ── 正常价差列表 ──
    normal_list = "、".join(categories["low"]) if categories["low"] else "无"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;margin:0;padding:0;background:#f5f5f5">
<div style="max-width:680px;margin:0 auto;padding:20px">

  <!-- 头部 -->
  <div style="background:linear-gradient(135deg,#1a1a2e,#16213e);color:white;padding:28px 24px;border-radius:8px 8px 0 0">
    <div style="font-size:1.6em;font-weight:700;margin-bottom:4px">🛢️ 能化品种监控日报</div>
    <div style="font-size:0.9em;opacity:0.8">{today}</div>
  </div>

  <!-- 概览 -->
  <div style="background:white;padding:20px 24px">
    <p style="font-size:1.2em;color:{summary_color};font-weight:600">
      {n_high} 组显著偏离 · {n_mid} 组值得关注 · {n_low} 组正常
    </p>
  </div>

  <!-- 偏离卡片 -->
"""

    if alert_cards:
        html += (
            '  <div style="background:white;padding:0 24px 20px">\n'
            '    <div style="margin:0">\n'
            + alert_cards +
            '\n    </div>\n'
            '  </div>\n'
        )

    # 正常价差（一行文字）
    if n_low > 0 and (n_high > 0 or n_mid > 0):
        html += (
            f'  <div style="background:white;padding:0 24px 20px">\n'
            f'    <details>\n'
            f'      <summary style="cursor:pointer;font-size:0.9em;color:#666">✅ 正常价差 ({n_low}组)</summary>\n'
            f'      <p style="font-size:0.85em;color:#888;margin-top:8px">{normal_list}</p>\n'
            f'    </details>\n'
            f'  </div>\n'
        )

    # 完整统计表
    html += """
  <div style="background:white;padding:20px 24px;border-top:1px solid #eee">
    <div style="font-size:1.1em;font-weight:600;margin-bottom:12px">📋 全部价差统计</div>
    <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:0.9em">
      <thead>
        <tr style="background:#fafafa;border-bottom:2px solid #ddd">
          <th style="padding:10px 12px;text-align:left;white-space:nowrap">价差</th>
          <th style="padding:10px 12px;text-align:left;white-space:nowrap">产业链</th>
          <th style="padding:10px 12px;text-align:right;white-space:nowrap">当前值</th>
          <th style="padding:10px 12px;text-align:right;white-space:nowrap">Z-Score</th>
          <th style="padding:10px 12px;text-align:right;white-space:nowrap">百分位</th>
          <th style="padding:10px 12px;text-align:left;white-space:nowrap">含义</th>
        </tr>
      </thead>
      <tbody>
"""
    html += table_rows
    html += """
      </tbody>
    </table>
    </div>
  </div>

  <!-- 页脚 -->
  <div style="background:#f0f0f0;padding:16px 24px;border-radius:0 0 8px 8px;font-size:0.8em;color:#999;text-align:center">
    本邮件由能化品种监控系统自动发送<br>
    数据来源：新浪财经 · 仅供研究参考，不构成投资建议
  </div>

</div>
</body>
</html>"""
    return html


# ════════════════════════════
#  4. 发送邮件
# ════════════════════════════

def send_email(cfg: dict, html_body: str, today: str) -> None:
    """通过 SMTP 发送 HTML 邮件"""
    email_cfg = cfg["email"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🛢️ 能化品种监控日报 · {today}"
    msg["From"] = email_cfg["sender"]
    msg["To"] = ", ".join(email_cfg["recipients"])
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if email_cfg.get("use_ssl", True):
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(email_cfg["smtp_server"], email_cfg["smtp_port"], context=ctx) as s:
            s.login(email_cfg["sender"], email_cfg["password"])
            s.sendmail(email_cfg["sender"], email_cfg["recipients"], msg.as_string())
    else:
        with smtplib.SMTP(email_cfg["smtp_server"], email_cfg["smtp_port"]) as s:
            s.starttls()
            s.login(email_cfg["sender"], email_cfg["password"])
            s.sendmail(email_cfg["sender"], email_cfg["recipients"], msg.as_string())

    print(f"  ✅ 邮件已发送 → {', '.join(email_cfg['recipients'])}")


# ════════════════════════════
#  5. 主入口
# ════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="能化品种预警邮件")
    parser.add_argument("--dry-run", action="store_true", help="仅打印邮件内容，不发送")
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    print(f"🛢️  能化品种预警 · {today}")
    print("=" * 40)

    # 加载配置
    try:
        cfg = load_config()
    except FileNotFoundError:
        return

    # 读取价差数据
    csv_path = DATA_DIR / "spreads.csv"
    if not csv_path.exists():
        print(f"[错误] 价差数据不存在: {csv_path}")
        print("请先运行 python3 data_fetcher.py")
        return
    spreads = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    print(f"  📊 加载价差数据: {spreads.shape[1]} 组 × {len(spreads)} 天")

    # 计算统计
    stats = compute_stats(spreads)
    z_warn = cfg["alert"]["z_warn"]
    z_alert = cfg["alert"]["z_alert"]
    categories = classify_alerts(stats, z_warn, z_alert)

    n_high, n_mid = len(categories["high"]), len(categories["mid"])
    print(f"  🔴 显著偏离: {n_high} 组")
    print(f"  ⚠️  值得关注: {n_mid} 组")

    # 判断是否发送
    send_mode = cfg["alert"].get("send_mode", "always")
    if send_mode == "on_deviation" and n_high == 0 and n_mid == 0:
        print("  ⏭️  无偏离，跳过发送（send_mode = on_deviation）")
        return

    # 构建邮件
    html = build_html_body(stats, categories, today)

    if args.dry_run:
        print("\n" + "=" * 40)
        print("📄 邮件预览 (--dry-run):")
        print("=" * 40)
        print(f"  收件人: {', '.join(cfg['email']['recipients'])}")
        print(f"  主题: 🛢️ 能化品种监控日报 · {today}")
        print(f"  HTML 长度: {len(html)} 字符")
        print("\n  前 500 字符预览:")
        print(html[:500])
        return

    # 发送
    print("  📧 正在发送邮件...")
    try:
        send_email(cfg, html, today)
    except smtplib.SMTPAuthenticationError:
        print("  ❌ SMTP 登录失败，请检查 config.toml 中的邮箱/授权码")
    except smtplib.SMTPException as e:
        print(f"  ❌ 邮件发送失败: {e}")
    except Exception as e:
        print(f"  ❌ 未知错误: {e}")


if __name__ == "__main__":
    main()
