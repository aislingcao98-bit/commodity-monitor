"""
能化基本面监控与预警看板
基于国内期货主力合约数据，追踪核心品种价格及产业链价差
"""

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

# ---- 页面配置 ----
st.set_page_config(
    page_title="能化品种监控看板",
    page_icon="🛢️",
    layout="wide",
)

# ---- 数据加载 ----
DATA_DIR = Path(__file__).parent / "data"


@st.cache_data(ttl=3600)
def load_data(version: int = 1):
    price_df = pd.read_csv(DATA_DIR / "price_table.csv", index_col=0, parse_dates=True)
    spreads = pd.read_csv(DATA_DIR / "spreads.csv", index_col=0, parse_dates=True)
    return price_df, spreads


price_df, spreads = load_data(version=7)

# 价差公式映射（按产业链分类）
SPREAD_FORMULAS = {
    # 🛢️ 原油链
    "沥青-原油": "沥青 - 原油",
    "燃油-原油": "燃油 - 原油",
    "原油-LPG": "原油 - LPG",
    # 🧪 烯烃链
    "PP-LPG": "PP - 1.2×LPG",
    "PP-原油": "PP - 原油",
    "PE-原油": "PE - 原油",
    "PP-PE": "PP - PE",
    # 🌸 芳烃链
    "PX-原油": "PX - 原油",
    "PTA-PX": "PTA - 0.655×PX",
    "EB-BZ": "EB - 0.8×纯苯",
    "EB-原油": "EB - 原油",
    "BZ-原油": "纯苯 - 原油",
    # 👚 聚酯链
    "PTA-EG": "PTA - EG",
    "EG-原油": "EG - 原油",
    # 🏭 甲醇链
    "PP-3MA": "PP - 3.0×甲醇",
    "MA-原油": "甲醇 - 原油",
}

SPREAD_MEANINGS = {
    # 🛢️ 原油链
    "沥青-原油": "沥青裂解利润（炼厂加工利润）",
    "燃油-原油": "燃料油裂解利润",
    "原油-LPG": "原油与LPG相对强弱（原料替代逻辑）",
    # 🧪 烯烃链
    "PP-LPG": "PDH装置利润（1吨PP约消耗1.2吨LPG）",
    "PP-原油": "PP一体化利润（石脑油裂解路线）",
    "PE-原油": "PE一体化利润（石脑油裂解路线）",
    "PP-PE": "聚丙烯 vs 聚乙烯相对强弱",
    # 🌸 芳烃链
    "PX-原油": "PX一体化利润（原油→石脑油→PX）",
    "PTA-PX": "PTA加工费（PX→PTA的加工利润，系数0.655）",
    "EB-BZ": "苯乙烯加工利润（纯苯→EB，1吨EB消耗0.8吨纯苯）",
    "EB-原油": "苯乙烯一体化利润（原油→石脑油→纯苯→EB）",
    "BZ-原油": "纯苯一体化利润（原油→石脑油→纯苯）",
    # 👚 聚酯链
    "PTA-EG": "聚酯原料价差（PTA vs 乙二醇）",
    "EG-原油": "乙二醇一体化利润",
    # 🏭 甲醇链
    "PP-3MA": "MTO/MTP装置利润（1吨PP约消耗3吨甲醇）",
    "MA-原油": "甲醇对原油的相对价值（能源替代视角）",
}

# 价差分类（用于看板分组展示）
SPREAD_CATEGORIES = {
    "🛢️ 原油链": ["沥青-原油", "燃油-原油", "原油-LPG"],
    "🧪 烯烃链": ["PP-LPG", "PP-原油", "PE-原油", "PP-PE"],
    "🌸 芳烃链": ["PX-原油", "PTA-PX", "EB-BZ", "EB-原油", "BZ-原油"],
    "👚 聚酯链": ["PTA-EG", "EG-原油"],
    "🏭 甲醇链": ["PP-3MA", "MA-原油"],
}

# 价差 → 产业链 反向映射
SPREAD_TO_CHAIN = {}
for _cat, _spreads in SPREAD_CATEGORIES.items():
    for _s in _spreads:
        SPREAD_TO_CHAIN[_s] = _cat

# ---- 时间范围工具函数 ----
DATE_RANGE_OPTIONS = ["近1月", "近3月", "近6月", "近1年", "近3年", "全部"]
DAYS_MAP = {"近1月": 22, "近3月": 66, "近6月": 126, "近1年": 252, "近3年": 756}


def slice_by_range(df: pd.DataFrame, range_name: str) -> pd.DataFrame:
    """按时间范围截取 DataFrame"""
    n = min(DAYS_MAP.get(range_name, len(df)), len(df))
    return df.tail(n)


def compute_stats_live(spreads: pd.DataFrame, lookback_days: int) -> pd.DataFrame:
    """基于指定时间窗口动态计算价差统计"""
    recent = spreads.tail(lookback_days)
    s = pd.DataFrame(index=spreads.columns)
    s["当前值"] = spreads.iloc[-1]
    s["均值"] = recent.mean()
    s["标准差"] = recent.std()
    s["Z-Score"] = ((s["当前值"] - s["均值"]) / s["标准差"]).round(2)
    s["历史最低"] = recent.min()
    s["历史最高"] = recent.max()
    s["百分位"] = (recent.rank(pct=True).iloc[-1] * 100)

    def alert_label(z):
        if abs(z) < 1.5:
            return "✅ 正常"
        elif abs(z) < 2.0:
            return "⚠️ 关注"
        else:
            return "🔴 偏离"

    s["预警"] = s["Z-Score"].apply(alert_label)
    return s.round(2)


# 全局样式
st.markdown("""
<style>
/* 表格数据居中 - 覆盖 Streamlit 默认对齐 */
[data-testid="stDataFrame"] *,
[data-testid="stDataFrameContainer"] * {
    text-align: center !important;
}
/* 行情概览：品种名称 + 价格 */
[data-testid="stMetricLabel"] {
    font-weight: 700 !important;
    font-size: 1.0rem !important;
    color: #333 !important;
}
[data-testid="stMetricValue"] {
    font-weight: 700 !important;
    font-size: 1.4rem !important;
}
</style>
""", unsafe_allow_html=True)

# 通过同源 iframe 注入 JS，直接操作父页面 DOM 覆写 select 样式 + 预警卡片点击置顶
st.markdown("""
<iframe srcdoc="&lt;script&gt;
(function() {
var p = window.parent.document;
function fix() {
  // 1. 文字居中
  p.querySelectorAll('[data-baseweb=&quot;select&quot;]').forEach(function(s) {
    var t = s.firstElementChild;
    if (t) { t.style.justifyContent = 'center'; t.style.textAlign = 'center'; }
    var sp = s.querySelector('span');
    if (sp) { sp.style.textAlign = 'center'; }
  });
  // 2. 宽度自适应 + 右对齐
  p.querySelectorAll('[data-testid=&quot;stSelectbox&quot;]').forEach(function(b) {
    b.style.width = 'auto';
    b.style.minWidth = 'auto';
    b.style.marginLeft = 'auto';
    b.style.display = 'table';
  });
  // 3. 垂直对齐
  p.querySelectorAll('[data-testid=&quot;stHorizontalBlock&quot;]').forEach(function(row) {
    var h3 = row.querySelector('h3');
    var select = row.querySelector('[data-baseweb=&quot;select&quot;]');
    if (h3 &amp;&amp; select) {
      var h3Rect = h3.getBoundingClientRect();
      var selRect = select.getBoundingClientRect();
      var h3Center = h3Rect.top + h3Rect.height / 2;
      var selCenter = selRect.top + selRect.height / 2;
      var diff = h3Center - selCenter;
      var selectBox = select.closest('[data-testid=&quot;stSelectbox&quot;]');
      if (selectBox &amp;&amp; Math.abs(diff) &gt; 1) {
        var currentMargin = parseFloat(selectBox.style.marginTop) || 0;
        selectBox.style.marginTop = (currentMargin + diff) + 'px';
      }
    }
  });
  // 4. 品种名/价格/涨跌幅 全部加粗放大（暴力找所有叶子文字节点）
  p.querySelectorAll('[data-testid=&quot;stMetric&quot;]').forEach(function(metric) {
    var leaves = [];
    metric.querySelectorAll('*').forEach(function(el) {
      if (el.children.length === 0 &amp;&amp; el.textContent.trim()) leaves.push(el);
    });
    if (leaves.length &gt;= 1) {
      leaves[0].style.fontWeight = '700';
      leaves[0].style.fontSize = '1.0rem';
      leaves[0].style.color = '#333';
    }
    if (leaves.length &gt;= 2) {
      leaves[1].style.fontWeight = '700';
      leaves[1].style.fontSize = '1.4rem';
    }
    if (leaves.length &gt;= 3) {
      leaves[2].style.fontWeight = '600';
      leaves[2].style.fontSize = '0.8rem';
      leaves[2].style.whiteSpace = 'nowrap';
    }
  });
  // 5. 预警卡片：hover 阴影 + 点击将对应图表块移到最前面
  p.querySelectorAll('div').forEach(function(div) {
    if (div.style.cursor === 'pointer' &amp;&amp; div.style.borderLeftWidth === '3px' &amp;&amp; div.style.borderLeftStyle === 'solid') {
      if (div._spreadBound) return;
      div._spreadBound = true;
      div.onmouseenter = function() { div.style.boxShadow = '0 2px 8px rgba(0,0,0,0.12)'; };
      div.onmouseleave = function() { div.style.boxShadow = 'none'; };
      div.onclick = function() {
        // 计算点击的是第几张卡片
        var cards = [];
        p.querySelectorAll('div').forEach(function(d) {
          if (d.style.cursor === 'pointer' &amp;&amp; d.style.borderLeftWidth === '3px' &amp;&amp; d.style.borderLeftStyle === 'solid') cards.push(d);
        });
        var idx = cards.indexOf(div);
        if (idx &lt; 0) return;
        // 找到图表块的起止标记
        var start = p.getElementById('spread-block-' + idx + '-start');
        var end = p.getElementById('spread-block-' + idx + '-end');
        if (!start || !end) return;
        // 向上走到 stVerticalBlock 的直接子级
        function topBlock(el) {
          while (el &amp;&amp; el.parentElement) {
            if (el.parentElement.getAttribute('data-testid') === 'stVerticalBlock') return el;
            el = el.parentElement;
          }
          return null;
        }
        var first = topBlock(start);
        var last = topBlock(end);
        if (!first || !last) return;
        var parent = first.parentElement;
        // 收集整个图表块
        var toMove = [];
        var cur = first;
        while (cur &amp;&amp; cur !== last.nextSibling) {
          toMove.push(cur);
          cur = cur.nextSibling;
        }
        // 找到插入点
        var marker = p.getElementById('spread-charts');
        var after = topBlock(marker);
        if (!after) return;
        if (first === after.nextSibling) return; // 已经在最上面
        // FLIP: 记录所有受影响元素（从插入点到移动块末尾）的旧位置
        var allEls = [];
        var scan = after.nextSibling;
        while (scan &amp;&amp; scan !== last.nextSibling) {
          allEls.push(scan);
          scan = scan.nextSibling;
        }
        var oldRects = allEls.map(function(el) { return el.getBoundingClientRect(); });
        // 移动 DOM
        var frag = document.createDocumentFragment();
        toMove.forEach(function(el) { frag.appendChild(el); });
        parent.insertBefore(frag, after.nextSibling);
        // FLIP: 所有位置变化的元素都播放动画（上移的 + 被挤下去的）
        allEls.forEach(function(el, i) {
          var newRect = el.getBoundingClientRect();
          var oldRect = oldRects[i];
          var dy = oldRect.top - newRect.top;
          if (Math.abs(dy) &gt; 1) {
            el.style.transition = 'none';
            el.style.transform = 'translateY(' + dy + 'px)';
            el.offsetHeight; // force reflow
            el.style.transition = 'transform 0.45s cubic-bezier(0.25, 0.46, 0.45, 0.94)';
            el.style.transform = 'translateY(0)';
            setTimeout(function() { el.style.transition = ''; el.style.transform = ''; }, 500);
          }
        });
      };
    }
  });
}
fix();
// 多次执行确保布局稳定后对齐
setTimeout(fix, 500);
setTimeout(fix, 1500);
new MutationObserver(fix).observe(p.body, {childList:true, subtree:true});
})();
&lt;/script&gt;"
style="display:none;width:0;height:0;border:0">
</iframe>
""", unsafe_allow_html=True)

# ---- 主页面 ----
st.title("🛢️ 能化品种基本面监控与预警看板")
st.caption(f"全量数据：{price_df.index[0].strftime('%Y-%m-%d')} ~ {price_df.index[-1].strftime('%Y-%m-%d')} | 共 {len(price_df)} 个交易日")

# ---- 第一行：关键指标卡片 ----
st.markdown("### 📊 最新行情概览")
latest = price_df.iloc[-1]
prev = price_df.iloc[-2]
changes = ((latest - prev) / prev * 100).round(2)

cols = st.columns(len(latest))
for i, (name, val) in enumerate(latest.items()):
    chg = changes[name]
    color = "#ef5350" if chg > 0 else "#26a69a"
    with cols[i]:
        st.metric(
            label=name,
            value=f"{val:.0f}",
            delta=f"{chg:+.2f}%",
        )

st.caption(f"数据更新至：{price_df.index[-1].strftime('%Y-%m-%d')} | 原油：7.33桶/吨")

# ---- Tab 布局 ----
tab1, tab2, tab3 = st.tabs(["📈 盘面走势", "📊 价差分析", "📋 数据总览"])

# ---- Tab 1: 盘面走势 ----
with tab1:
    # 标题行：标题在左，小时间选择器在右
    col_title, col_range = st.columns([4, 1], vertical_alignment="center")
    with col_title:
        st.markdown("### 主力合约收盘价走势")
    with col_range:
        price_range = st.selectbox(
            "时间", DATE_RANGE_OPTIONS, index=3,
            key="price_timerange", label_visibility="collapsed"
        )
    price_plot_df = slice_by_range(price_df, price_range)

    # 所有品种
    all_products = list(price_plot_df.columns)

    # 品种选择按钮（多选，默认显示前4个）
    selected_products = st.pills(
        "选择品种", all_products,
        default=all_products[:4],
        key="price_products", label_visibility="collapsed",
        selection_mode="multi",
    )

    if not selected_products:
        st.info("👆 请选择要查看的品种")
    else:
        product_colors = {
            "原油": "#1a1a1a", "LPG": "#27ae60", "沥青": "#e67e22",
            "燃油": "#3498db", "PP": "#8e44ad", "PE": "#2980b9",
            "PTA": "#c0392b", "甲醇": "#16a085", "PX": "#d35400",
            "EG": "#2c3e50", "EB": "#7f8c8d", "纯苯": "#f39c12",
        }

        # 单图显示选中品种
        fig = go.Figure()
        for p in selected_products:
            if p in price_plot_df.columns:
                fig.add_trace(go.Scatter(
                    x=price_plot_df.index, y=price_plot_df[p],
                    name=p, line=dict(color=product_colors.get(p), width=1.5),
                ))
        fig.update_layout(
            height=400, margin=dict(l=0, r=0, t=0, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            xaxis_title=None, yaxis_title="元/吨",
            yaxis=dict(tickformat=",.0f"),
        )
        st.plotly_chart(fig, width="stretch")

    # 涨跌幅热力图
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("#### 涨跌幅热力图（日度）")
    returns = price_plot_df.pct_change().dropna()
    z_data = returns.T.values * 100
    fig = go.Figure(data=go.Heatmap(
        z=z_data,
        x=returns.index,
        y=returns.columns,
        colorscale="RdBu_r",
        zmid=0,
        zmin=-5,
        zmax=5,
        colorbar=dict(title="涨跌幅 %", x=1.05),
    ))
    n_products = len(returns.columns)
    fig.update_layout(
        height=max(250, n_products * 38), margin=dict(l=0, r=120, t=0, b=0),
        yaxis=dict(side="right"),
    )
    st.plotly_chart(fig, width="stretch")

# ---- Tab 2: 价差分析 ----
with tab2:
    # 标题行：标题在左，小时间选择器在右
    col_title, col_range = st.columns([4, 1], vertical_alignment="center")
    with col_title:
        st.markdown("### 跨品种价差走势 & Z-Score 偏离预警")
    with col_range:
        spread_range = st.selectbox(
            "时间", DATE_RANGE_OPTIONS, index=3,
            key="spread_timerange", label_visibility="collapsed"
        )
    spread_plot_df = slice_by_range(spreads, spread_range)
    # 动态计算统计量，与所选时间范围一致
    live_spread_stats = compute_stats_live(spreads, DAYS_MAP.get(spread_range, len(spreads)))

    # 偏离预警卡片（仅显示 Z-Score 绝对值 > 1.5 的价差）
    spread_list = []
    for cat_name, cat_spreads in SPREAD_CATEGORIES.items():
        for s in cat_spreads:
            if s in spreads.columns and s in live_spread_stats.index:
                spread_list.append(s)

    # 全部价差卡片：异常卡片在上（完整信息），正常卡片在下（仅名称+产业链）
    alert_list = [s for s in spread_list if abs(live_spread_stats.loc[s, "Z-Score"]) > 1.5]
    normal_list = [s for s in spread_list if abs(live_spread_stats.loc[s, "Z-Score"]) <= 1.5]

    def render_alert_cards(names):
        """渲染异常价差卡片"""
        cards_html = '<div style="display:flex;flex-wrap:wrap;gap:4px">'
        for name in names:
            row = live_spread_stats.loc[name]
            z = row["Z-Score"]
            chain = SPREAD_TO_CHAIN.get(name, "")
            if abs(z) > 2.0:
                bg, border, level = "#fff5f5", "#ef5350", "🔴"
            else:
                bg, border, level = "#fff8e1", "#ff9800", "⚠️"
            cards_html += (
                f"<div style='width:160px;cursor:pointer;background:{bg};"
                f"border-left:3px solid {border};padding:8px 10px;"
                f"border-radius:4px;font-size:0.85rem;line-height:1.7'>"
                f"{level} <b>{name}</b> &nbsp;<span style='color:#888;font-size:0.75rem'>{chain}</span><br>"
                f"<span style='font-size:1.3rem;font-weight:700'>{row['当前值']:.0f}</span><br>"
                f"Z-Score: <b>{z:+.2f}</b><br>"
                f"百分位: {row['百分位']:.0f}%"
                f"</div>"
            )
        cards_html += '</div>'
        st.markdown(cards_html, unsafe_allow_html=True)

    def render_normal_cards(names):
        """渲染正常价差卡片"""
        cards_html = '<div style="display:flex;flex-wrap:wrap;gap:4px">'
        for name in names:
            row = live_spread_stats.loc[name]
            chain = SPREAD_TO_CHAIN.get(name, "")
            cards_html += (
                f"<div style='width:160px;cursor:pointer;"
                f"padding:5px 6px;"
                f"border-radius:4px;font-size:0.8rem;text-align:center;line-height:1.6;"
                f"border-left:3px solid #d0d0d0;border-top:1px solid #e8e8e8;"
                f"border-right:1px solid #e8e8e8;border-bottom:1px solid #e8e8e8;background:#fafafa'>"
                f"<b>{name}</b> <span style='color:#999;font-size:0.7rem'>{chain}</span><br>"
                f"<span style='font-size:0.85rem'><b>{row['当前值']:.0f}</b></span>"
                f"</div>"
            )
        cards_html += '</div>'
        st.markdown(cards_html, unsafe_allow_html=True)

    if alert_list:
        st.markdown("<span style='font-size:0.8rem;color:#888'>🔔 偏离预警</span>", unsafe_allow_html=True)
        render_alert_cards(alert_list)
    else:
        st.success("✅ 所有价差均在正常区间内（|Z-Score| < 1.5）")

    if normal_list:
        if alert_list:
            st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("<span style='font-size:0.8rem;color:#888'>✅ 正常区间</span>", unsafe_allow_html=True)
        render_normal_cards(normal_list)

    # 绘制全部价差
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div id="spread-charts"></div>', unsafe_allow_html=True)

    for idx, spread_name in enumerate(spread_list):
        row = live_spread_stats.loc[spread_name]
        z = row["Z-Score"]
        mean_val = row["均值"]
        std_val = row["标准差"]

        # Z-score 颜色
        if abs(z) > 2.0:
            status = "🔴 显著偏离"
            band_color = "rgba(239, 83, 80, 0.15)"
        elif abs(z) > 1.5:
            status = "⚠️ 值得关注"
            band_color = "rgba(255, 152, 0, 0.15)"
        else:
            status = "✅ 正常区间"
            band_color = "rgba(76, 175, 80, 0.08)"

        fig = go.Figure()

        # 锚点标记：图表块的起点，JS 用这个来定位和移动整个块
        st.markdown(f'<div id="spread-block-{idx}-start"></div>', unsafe_allow_html=True)

        # 均值 ± 1σ 和 ± 2σ 带
        fig.add_trace(go.Scatter(
            x=spread_plot_df.index.tolist() + spread_plot_df.index.tolist()[::-1],
            y=([mean_val + 2 * std_val] * len(spread_plot_df) +
               [mean_val + std_val] * len(spread_plot_df)),
            fill="toself", fillcolor=band_color, mode="none",
            name="±2σ 区间", showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=spread_plot_df.index.tolist() + spread_plot_df.index.tolist()[::-1],
            y=([mean_val + std_val] * len(spread_plot_df) +
               [mean_val - std_val] * len(spread_plot_df)),
            fill="toself", fillcolor="rgba(76, 175, 80, 0.05)", mode="none",
            name="±1σ 区间", showlegend=False,
        ))

        # 均值线
        fig.add_hline(y=mean_val, line_dash="dash", line_color="gray",
                       annotation_text=f"均值 {mean_val:.0f}")

        # 价差走势
        fig.add_trace(go.Scatter(
            x=spread_plot_df.index, y=spread_plot_df[spread_name],
            name=spread_name, line=dict(color="#1a73e8", width=2),
        ))

        chain = SPREAD_TO_CHAIN.get(spread_name, "")
        fig.update_layout(
            title=f"{chain} · {spread_name}  |  Z-Score: {z:.2f}  {status}  |  当前: {row['当前值']:.0f}  |  百分位: {row['百分位']:.0f}%",
            height=350, margin=dict(l=0, r=0, t=40, b=0),
            xaxis_title=None, yaxis_title="元/吨",
            yaxis=dict(tickformat=",.0f"),
        )
        st.plotly_chart(fig, width="stretch")
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(f'<div id="spread-block-{idx}-end"></div>', unsafe_allow_html=True)

# ---- 表格渲染工具 ----
def render_styled_table(styled, max_height: int = None) -> None:
    """把 pandas Styler 渲染为全宽居中表格，内联样式保证绝对生效"""
    html = styled.to_html()
    # 给所有 td/th 强制加内联居中 + 不换行（最高优先级，Streamlit 无法覆盖）
    html = html.replace("<td ", '<td style="text-align:center;white-space:nowrap" ')
    html = html.replace("<th ", '<th style="text-align:center;white-space:nowrap" ')
    html = html.replace("<td>", '<td style="text-align:center;white-space:nowrap">')
    html = html.replace("<th>", '<th style="text-align:center;white-space:nowrap">')
    # 包裹为全宽可滚容器
    scroll = f"max-height:{max_height}px;overflow-y:auto;" if max_height else ""
    wrapped = (
        f'<div style="width:100%;{scroll}">'
        f'<style>table{{width:100%!important;border-collapse:collapse}}'
        f'th,td{{padding:4px 8px;font-size:0.9rem;border-bottom:1px solid #f0f0f0;white-space:nowrap}}'
        f'th{{border-bottom-width:2px}}</style>'
        f'{html}</div>'
    )
    st.markdown(wrapped, unsafe_allow_html=True)


# ---- Tab 3: 数据总览 ----
with tab3:
    # 标题行：标题在左，小时间选择器在右
    col_title, col_range = st.columns([4, 1], vertical_alignment="center")
    with col_title:
        st.markdown("### 价差统计表")
    with col_range:
        stats_range = st.selectbox(
            "时间", DATE_RANGE_OPTIONS, index=3,
            key="stats_timerange", label_visibility="collapsed"
        )
    live_stats = compute_stats_live(spreads, DAYS_MAP.get(stats_range, len(spreads)))

    # 按 SPREAD_FORMULAS 顺序排列，确保包含价差说明表中的全部价差
    all_spread_names = list(SPREAD_FORMULAS.keys())
    live_stats = live_stats.reindex(all_spread_names)

    # 产业链筛选按钮
    chain_options = ["全部"] + list(SPREAD_CATEGORIES.keys())
    selected_chain = st.pills("产业链", chain_options, default="全部", key="stats_chain_filter", label_visibility="collapsed")

    # 给统计表加上产业链列
    stats_to_category = {}
    for cat_name, cat_spreads in SPREAD_CATEGORIES.items():
        for s in cat_spreads:
            stats_to_category[s] = cat_name
    live_stats.insert(0, "产业链", live_stats.index.map(lambda x: stats_to_category.get(x, "")))

    if selected_chain and selected_chain != "全部":
        filtered_stats = live_stats[live_stats["产业链"] == selected_chain]
    else:
        filtered_stats = live_stats

    render_styled_table(
        filtered_stats.style
        .background_gradient(subset=["Z-Score"], cmap="RdBu_r", vmin=-2.5, vmax=2.5)
        .format("{:.2f}", subset=["当前值", "均值", "标准差", "Z-Score", "历史最低", "历史最高"])
        .format("{:.1f}", subset=["百分位"]),
    )

    st.markdown("---")

    # 价差说明表
    st.markdown("#### 价差说明")
    spread_to_category = {}
    for cat_name, cat_spreads in SPREAD_CATEGORIES.items():
        for s in cat_spreads:
            spread_to_category[s] = cat_name
    ref_df = pd.DataFrame([
        {"产业链": spread_to_category.get(name, ""), "价差名称": name, "公式": formula, "含义": SPREAD_MEANINGS.get(name, "")}
        for name, formula in SPREAD_FORMULAS.items()
    ])
    render_styled_table(
        ref_df.style.hide(axis="index"),
    )

    st.markdown("---")

    # 价差历史数据表
    col_title2, col_range2 = st.columns([4, 1], vertical_alignment="center")
    with col_title2:
        st.markdown("### 价差历史数据")
    with col_range2:
        hist_range = st.selectbox(
            "时间", DATE_RANGE_OPTIONS, index=2,
            key="history_timerange", label_visibility="collapsed"
        )

    hist_df = slice_by_range(spreads, hist_range).sort_index(ascending=False)
    hist_df.index = hist_df.index.strftime("%Y-%m-%d")
    hist_df = hist_df.reset_index(names=["时间"])  # 时间变成普通列，只在表头出现一次

    render_styled_table(
        hist_df.style
        .hide(axis="index")
        .format("{:.1f}", subset=hist_df.columns.difference(["时间"]))
        .background_gradient(cmap="RdBu_r", axis=0, subset=hist_df.columns.difference(["时间"])),
        max_height=500,
    )

# ---- Footer ----
st.markdown("---")
st.caption(
    "本项目为个人学习项目，数据来自公开数据源（新浪财经），仅供研究参考，不构成投资建议。"
    " | 使用 Python + Streamlit + Plotly 搭建，全程 AI 辅助开发。"
)
