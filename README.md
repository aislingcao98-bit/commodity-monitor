# 🛢️ 能化品种基本面监控与预警看板

[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Plotly](https://img.shields.io/badge/Plotly-3F4F75?logo=plotly&logoColor=white)](https://plotly.com)

面向**能源化工产业链**的基本面监控与统计预警看板。覆盖 12 个国内期货主力品种、16 组产业链价差指标、5 条核心产业链，基于滚动窗口 Z-Score 模型进行偏离预警。

---

## 📌 业务背景

在能源化工贸易中，产业链价差（Crack Spread / Processing Margin）是判断装置利润、原料替代、供需边际变化的核心信号。传统方式依赖 Excel 手动拉数 + 人工判断，无法做到多品种、多链条的系统化监控。

本看板实现了从**数据采集 → 统计计算 → 可视化 → 预警**的全自动化闭环，将一个纸经纪的日常分析工作系统化。

---

## 🧩 功能模块

### 📊 行情概览
- 12 个能化品种主力合约最新收盘价 + 日涨跌幅
- 原油自动桶→吨换算（7.33 桶/吨）
- 历史走势图（多时间窗口：近 1 月 ~ 近 3 年）

### 📈 产业链价差分析（核心模块）
- **16 组价差指标**，按 5 条产业链分类：

| 产业链 | 价差指标 | 核心逻辑 |
|--------|----------|----------|
| 🛢️ 原油链 | 沥青-原油、燃油-原油、原油-LPG | 裂解利润、原料替代 |
| 🧪 烯烃链 | PP-LPG、PP-原油、PE-原油、PP-PE | PDH 利润、一体化利润 |
| 🌸 芳烃链 | PX-原油、PTA-PX、EB-BZ、EB-原油、BZ-原油 | PTA 加工费、苯乙烯利润 |
| 👚 聚酯链 | PTA-EG、EG-原油 | 原料替代、一体化利润 |
| 🏭 甲醇链 | PP-3MA、MA-原油 | MTO/MTP 利润、能源替代 |

> 公式中的系数（如 PTA-0.655PX、PP-1.2LPG、EB-0.8BZ）基于化工工艺的物料衡算比例。

### 🚨 统计预警引擎
- **Z-Score 模型**：基于 252 日滚动窗口计算偏离度
- **三级预警**：✅ 正常（|Z|<1.5）→ ⚠️ 关注（1.5≤|Z|<2.0）→ 🔴 偏离（|Z|≥2.0）
- 预警卡片点击即达对应图表（FLIP 动画过渡）

### 🗺️ 热力图
- 涨跌幅矩阵热力图：不同时间窗口下品种强弱一目了然

### 📋 数据总览
- 完整价差统计表（当前值、均值、历史极值、Z-Score、百分位）

---

## 🛠 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| 数据获取 | AKShare（新浪财经） | 拉取国内期货主力合约日度数据 |
| 数据处理 | Pandas / NumPy | 多表对齐、价差计算、滚动窗口统计 |
| 可视化 | Plotly Grapth Objects | 走势图、热力图、Z-Score σ 带 |
| Web 看板 | Streamlit | 响应式布局、组件状态管理 |
| 前端交互 | JavaScript / CSS FLIP | DOM 动画、MutationObserver |
| 定时任务 | macOS launchd | 工作日 15:30 自动更新数据 |

---

## 🚀 快速开始

### 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 拉取最新数据
python data_fetcher.py

# 3. 启动看板
streamlit run dashboard.py
```

浏览器打开 [http://localhost:8501](http://localhost:8501) 即可查看。

### 定时数据更新（macOS）

```bash
cp update_data.sh ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.caozhaohui.trading-update.plist
```

Task scheduler 将在每个工作日 15:30（收盘后）自动拉取最新数据。

---

## 📸 界面预览

> 👉 **在线演示：[commodity-monitor.streamlit.app](https://commodity-monitor-8ufimbbdcgydjxesjujkad.streamlit.app)**

- 行情概览：12 品种实时价格卡片 + 日涨跌幅
- 价差分析：预警卡片 + 走势图 + Z-Score 偏离标注
- 热力图：多时间窗口涨跌幅矩阵
- 数据总览：完整统计表格

---

## 📁 项目结构

```
commodity_monitor/
├── dashboard.py          # 主看板（Streamlit）
├── data_fetcher.py       # 数据管线（AKShare → CSV）
├── update_data.sh        # 定时更新脚本
├── requirements.txt      # Python 依赖
├── data/                 # 数据文件（CSV）
│   ├── SC0.csv          #   原油主力
│   ├── PP0.csv          #   PP 主力
│   ├── ...              #   其他品种
│   ├── price_table.csv  #   统一价格表
│   ├── spreads.csv      #   价差数据
│   └── spread_stats.csv #   价差统计
└── logs/                 # 定时任务日志
```

---

## 📝 后续规划

- [ ] 接入交易所实时 API（CTP 接口）
- [ ] 企业微信/钉钉实时预警推送
- [ ] 前端交互：手动设置品种对冲比率
- [ ] 历史回测模块：价差均值回归策略回测
