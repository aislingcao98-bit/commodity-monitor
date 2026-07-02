# 🛢️ 能化品种基本面监控与预警看板

[![Streamlit](https://img.shields.io/badge/Streamlit-1.58-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io)
[![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](https://python.org)
[![Plotly](https://img.shields.io/badge/Plotly-6.8-3F4F75?logo=plotly&logoColor=white)](https://plotly.com)

面向**能源化工产业链**的全自动基本面监控与统计预警系统。覆盖 12 个国内期货主力品种、16 组跨品种价差、5 条核心产业链，基于滚动窗口 Z-Score 模型进行偏离预警，支持盘中自动更新、邮件推送、一键部署。

---

## 🎯 一句话介绍（面试版）

> 我为能源化工大宗商品交易场景，用 Python 从零搭建了一套**从数据采集→统计计算→可视化→预警推送**的全自动监控系统。它解决了传统 Excel 手工分析效率低、无法多品种多链条同时监控的痛点，目前在本地和 Streamlit Cloud 上运行，每天盘中自动更新、自动发日报。

---

## 📌 业务背景 & 解决的问题

**场景**：能源化工贸易中，产业链价差（裂解利润、加工利润、原料替代价差）是判断装置开工率、供需边际变化的先行指标。

**痛点**：
- 手工从新浪财经/万得拉数据 → 贴到 Excel → 画图 → 人工判断，每天重复劳动
- 12 个品种 × 16 组价差，人眼无法同时跟踪
- 缺少统计意义上的偏离预警（什么是"贵"、什么是"便宜"没有量化标准）

**我的解法**：用 Python 把整个流程自动化——API 自动拉数、Pandas 算价差、Z-Score 模型量化偏离度、Streamlit 做看板、Cron 定时调度，从数据到决策全链路打通。

---

## 🧩 核心功能

### 📊 行情总览
- 12 个能化品种主力合约最新价 + 日涨跌幅（涨绿跌红）
- 原油自动桶→吨换算（1 吨 ≈ 7.33 桶）
- 多时间窗口走势图（1 月 ~ 3 年）+ 涨跌幅热力图

### 📈 产业链价差分析（核心模块）
- **16 组价差**，按 5 条产业链组织，含工艺物料衡算系数：

| 产业链 | 价差指标 | 交易逻辑 |
|--------|----------|----------|
| 🛢️ 原油链 | 沥青-原油、燃油-原油、原油-LPG | 裂解利润、原料替代 |
| 🧪 烯烃链 | PP-LPG (×1.2)、PP-原油、PE-原油、PP-PE | PDH 利润、石脑油路线利润 |
| 🌸 芳烃链 | PX-原油、PTA-PX (×0.655)、EB-BZ (×0.8)、EB-原油、BZ-原油 | PTA 加工费、苯乙烯利润 |
| 👚 聚酯链 | PTA-EG、EG-原油 | 聚酯原料替代、一体化利润 |
| 🏭 甲醇链 | PP-3MA (×3.0)、MA-原油 | MTO/MTP 利润、能源替代 |

### 🚨 Z-Score 预警引擎
- 基于**滚动窗口**动态计算均值和标准差（与所选时间范围联动）
- **三级预警**：✅ 正常（|Z|<1.5）→ ⚠️ 关注（1.5≤|Z|<2.0）→ 🔴 偏离（|Z|≥2.0）
- 异常价差卡片置顶 + 点击跳转到对应图表（FLIP 动画过渡）
- 每日自动发送 HTML 邮件日报

### 🔄 自动更新体系
- **Cron 调度**：盘中每 10 分钟拉取一次数据（夜盘 21:00-23:00 + 日盘 9:00-15:00，跳过午休和周末）
- **智能去重**：当日已拉取则跳过，避免重复 API 调用
- **页面自动刷新**：浏览器每 5 分钟自动 reload，无需手动 F5
- **自动推送**：数据更新后自动 git commit + push，Streamlit Cloud 同步更新

---

## 🏗 架构设计

```
                    ┌──────────────────────────┐
                    │   新浪财经 API (akshare)    │
                    │   12 个主力合约 × 全量历史   │
                    └───────────┬──────────────┘
                                │
                    ┌───────────▼──────────────┐
                    │     data_fetcher.py       │
                    │  · 拉取原始数据 → {sym}.csv │
                    │  · 构建统一价格表           │
                    │  · 计算 16 组价差           │
                    │  · 滚动窗口统计             │
                    └───────────┬──────────────┘
                                │
                    ┌───────────▼──────────────┐
                    │      data/*.csv           │
                    │  本地 CSV 作为轻量数据库    │
                    └───────┬──────────────────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
    ┌─────────▼──┐  ┌──────▼──────┐  ┌──▼──────────┐
    │ dashboard  │  │  alert.py   │  │  cron 调度    │
    │ Streamlit  │  │  HTML 邮件   │  │  每10分钟     │
    │ 看板       │  │  日报推送    │  │  全自动运行    │
    └────────────┘  └─────────────┘  └──────────────┘
```

**设计决策**：

| 决策 | 选择 | 原因 |
|------|------|------|
| 数据存储 | CSV 文件而非数据库 | 数据量小（5000 行 × 12 列），CSV 零依赖、易调试、Git 可追溯 |
| 价差计算 | Pandas 向量化运算 | 比逐行循环快 100×，代码可读性高 |
| 统计方法 | Z-Score 而非固定阈值 | 不同品种价格量级差异大，Z-Score 归一化后可比 |
| 看板框架 | Streamlit 而非 Flask/Django | 数据看板场景，Streamlit 开发效率极高（纯 Python，零前端） |
| 定时调度 | Cron 而非 APScheduler | 系统级调度更可靠，与 Python 进程解耦 |
| 包管理 | uv + 清华镜像 | 比 pip 快 10×，国内网络友好 |

---

## 🛠 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| 数据获取 | AKShare / akshare | 新浪财经期货主力合约日线数据 |
| 数据处理 | Pandas / NumPy | 多表对齐、价差公式、滚动窗口统计 |
| 可视化 | Plotly Graph Objects | 走势图、σ 带、热力图 |
| Web 框架 | Streamlit | 响应式看板、组件状态管理 |
| 前端交互 | JavaScript / CSS | FLIP 动画、DOM 监听、自动刷新 |
| 任务调度 | Cron (macOS) | 盘中多时段定时拉取 + 去重 |
| 邮件推送 | SMTP (smtplib) | HTML 日报、三级预警分类 |
| 部署 | Streamlit Cloud | 与 GitHub 联动，push 即部署 |
| 包管理 | uv | 比 pip 快 10× 的 Python 包管理器 |

---

## 🚀 快速开始

```bash
# 1. 克隆
git clone git@github.com:aislingcao98-bit/commodity-monitor.git
cd commodity-monitor

# 2. 创建虚拟环境 & 安装依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# 国内用户推荐：
# uv pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 3. 拉取最新数据
python3 data_fetcher.py

# 4. 启动看板
streamlit run dashboard.py
```

浏览器打开 [http://localhost:8501](http://localhost:8501)。

---

## ⏰ 定时更新

Cron 配置（盘中每 10 分钟，跳过午休和周末）：

```
# 夜盘 21:00-23:00（周日至周五）
*/10 21-22 * * 0-5  bash scripts/update_data.sh
0 23 * * 0-5        bash scripts/update_data.sh
# 日盘 9:00-11:30 + 13:30-15:00（周一至周五）
*/10 9-10 * * 1-5   bash scripts/update_data.sh
0,10,20,30 11 * * 1-5  bash scripts/update_data.sh
30,40,50 13 * * 1-5     bash scripts/update_data.sh
*/10 14 * * 1-5         bash scripts/update_data.sh
0 15 * * 1-5            bash scripts/update_data.sh
```

脚本内置智能去重——当日已拉取则跳过，避免非交易时段无效请求。

---

## 📁 项目结构

```
commodity-monitor/
├── dashboard.py           # Streamlit 主看板（含 JS 自动刷新 + FLIP 动画）
├── data_fetcher.py        # 数据管线（API → CSV → 价差计算）
├── alert.py               # 邮件预警（HTML 日报 + 三级分类）
├── backtest.py            # 价差均值回归回测
├── scripts/
│   └── update_data.sh     # Cron 调度脚本（去重 + Git 推送 + 邮件）
├── data/                  # CSV 数据文件（本地轻量数据库）
│   ├── {SYM}.csv          #  各品种原始数据
│   ├── price_table.csv    #  统一价格表
│   └── spreads.csv        #  价差数据
├── logs/                  # 定时任务日志
├── DEBUG.md               # 排错手册
└── requirements.txt       # Python 依赖
```

---

## 🎤 面试讲述要点

**如果你只有 30 秒**：
> "我为大宗商品交易场景用 Python 搭了一套全自动监控系统，从数据采集到预警推送全部自动化，覆盖 12 个品种、16 组产业链价差，用 Z-Score 模型做量化偏离预警。"

**如果你有 2 分钟**：
1. **场景与痛点**（30s）：能化贸易中价差分析很重要，但靠手工 Excel 每天重复劳动，12 个品种 × 16 组价差人眼看不过来。
2. **我的方案**（30s）：用 Python 全链路自动化——akshare 拉数据 → Pandas 算价差 → Z-Score 量化偏离 → Streamlit 可视化 → 邮件推送日报。
3. **技术亮点**（30s）：滚动窗口统计让预警随市场动态调整；Cron 每 10 分钟盘中更新；FLIP 动画让交互更流畅；git push 自动触发 Streamlit Cloud 部署。
4. **成果**（30s）：每天自动运行，盘后收到日报邮件，异常价差自动标记，不用再手动拉数据画图。

**可能被追问的点**：
- **为什么用 Z-Score 而不是固定阈值？** → 不同品种价格量级差异大（原油 3000 vs 甲醇 2000），Z-Score 归一化后可比。滚动窗口动态计算均值和标准差，预警阈值随市场环境自适应。
- **为什么存 CSV 而不用数据库？** → 数据量小（5000 行），CSV 零依赖、Git 可追溯、Excel 可以直接打开检查。是真·"够用就好"的工程判断。
- **为什么用 Streamlit？** → 数据看板场景，Streamlit 纯 Python 开发效率极高。我不需要写 HTML/JS（除了少量交互优化），重心放在数据和业务逻辑上。
- **如果数据源挂了怎么办？** → data_fetcher.py 有 try/except 容错，单个品种失败不影响其他。Cron 脚本记录了每次运行的日志到 logs/，出问题可以快速定位。
- **怎么部署的？** → 本地 Mac 上 streamlit run 直接跑，同时连了 Streamlit Cloud，每次 git push 自动部署更新。

---

## 📝 后续规划

- [ ] 接入 CTP 实时行情接口（替代日线级别的延迟数据）
- [ ] 企业微信/钉钉 Bot 实时推送
- [ ] 前端交互：自定义品种对冲比率
- [ ] 历史回测模块增强：价差均值回归策略 + 夏普比率评估
- [ ] 支持移动端适配
