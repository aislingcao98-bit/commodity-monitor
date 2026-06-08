#!/bin/bash
# 能化品种数据每日自动更新（支持错过补跑 + 重复去重）
# 由 launchd 调度：每个工作日 15:30，若休眠则唤醒后补跑

cd /Users/caozhaohui/Desktop/cc
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

LOGFILE="$LOG_DIR/update_$(date +%Y%m%d).log"

# ---------- 去重检查：今天的数据是否已经拉取过 ----------
DATA_FILE="data/price_table.csv"
if [ -f "$DATA_FILE" ]; then
    # 读取 CSV 最后一行的日期
    LAST_DATE=$(tail -1 "$DATA_FILE" | cut -d',' -f1)
    TODAY=$(date +%Y-%m-%d)

    # 判断今天是否是交易日（简单策略：周六日跳过）
    DAY_OF_WEEK=$(date +%u)
    if [ "$DAY_OF_WEEK" -ge 6 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') 周末休市，跳过" >> "$LOGFILE"
        exit 0
    fi

    if [ "$LAST_DATE" = "$TODAY" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') 今日数据已存在 ($LAST_DATE)，跳过" >> "$LOGFILE"
        exit 0
    fi
fi

echo "======== $(date '+%Y-%m-%d %H:%M:%S') 开始更新 ========" >> "$LOGFILE"
/usr/bin/python3 data_fetcher.py >> "$LOGFILE" 2>&1
echo "======== $(date '+%Y-%m-%d %H:%M:%S') 更新完成 ========" >> "$LOGFILE"
echo "" >> "$LOGFILE"

# 只保留最近 30 天的日志
find "$LOG_DIR" -name "update_*.log" -mtime +30 -delete
