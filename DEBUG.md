# 看板 Debug 手册

## 数据流转全貌

```
新浪财经 API (akshare)
    │
    ▼
data_fetcher.py          ← 数据拉取入口
    │
    ├── data/SC0.csv     ← 12个品种原始数据（收盘价+成交量）
    ├── data/price_table.csv  ← 统一价格表（原油 ×7.33 元/吨）
    ├── data/spreads.csv      ← 16组跨品种价差
    └── data/spread_stats.csv ← 统计摘要
           │
    dashboard.py  ← Streamlit 看板
    alert.py      ← 邮件预警
```

## 常用 Debug 命令

```bash
cd ~/Desktop/cc
source venv/bin/activate

# 1. 手动拉数据
python3 data_fetcher.py

# 2. 测试 API 是否通
python3 -c "import akshare as ak; df=ak.futures_zh_daily_sina('SC0'); print(df.tail())"

# 3. 看 CSV 最后更新时间
ls -la data/price_table.csv

# 4. 看 Cron 执行日志
cat logs/cron.log

# 5. 看 Cron 配置（交易时段 9:00-15:30 每30分钟拉一次数据）
crontab -l

# 6. 测试邮件（不发）
python3 alert.py --dry-run

# 7. 强制清除 Streamlit 缓存
rm -rf ~/.streamlit/cache

# 8. 看 akshare 版本
pip show akshare
```

## 常见问题排查

| 症状 | 可能原因 | 怎么查 |
|------|---------|--------|
| 看板数据好几天没变 | cron 没跑 / 数据拉取失败 | `ls -la data/price_table.csv` 看修改时间 |
| 页面不自动刷新 | JS 被浏览器拦截 | 看右上角有没有倒计时，换 Chrome 试试 |
| 拉数据报错 | API 挂了 / 网络问题 | `python3 -c "import akshare as ak; ak.futures_zh_daily_sina('SC0')"` |
| 某个品种没数据 | 合约退市 / 代码变了 | 看 `data_fetcher.py` 里 `fetch_all()` 的输出 |
| 邮件发不出去 | 授权码过期 | `python3 alert.py --dry-run` 先预览，再去 163 邮箱重新生成授权码 |
| cron 没执行 | Mac 休眠了 / 权限问题 | `cat logs/cron.log` 看有没有今天的时间戳 |
| 安装包报错 | Python 版本太新 (3.14) | 用 `uv pip install -i https://pypi.tuna.tsinghua.edu.cn/simple <包名>` |

## 关键文件速查

| 文件 | 作用 |
|------|------|
| `dashboard.py:22` | `AUTO_REFRESH_MINUTES` — 改这里调刷新频率 |
| `dashboard.py:51` | `@st.cache_data(ttl=300)` — 缓存时间 |
| `dashboard.py:63` | `load_data(version=8)` — 改 version 数字可强制刷新缓存 |
| `data_fetcher.py:19-32` | `SYMBOLS` — 品种列表，增删改这里 |
| `data_fetcher.py:86-161` | `calculate_spreads()` — 价差公式 |
| `config.toml` | 邮箱配置 + 预警阈值 |
| `scripts/update_data.sh` | cron 执行的脚本 |
