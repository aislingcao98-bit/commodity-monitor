#!/bin/bash
# 能化品种数据自动更新（Cron 调度：每10分钟，跳过午休和周末）
# 用法: bash /Users/caozhaohui/Desktop/cc/scripts/update_data.sh

set -e

PROJECT_DIR="/Users/caozhaohui/Desktop/cc"
LOG_DIR="$PROJECT_DIR/logs"
DATA_FILE="$PROJECT_DIR/data/price_table.csv"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "======== 开始数据更新 ========"

# ---- 周末跳过 ----
DAY_OF_WEEK=$(date +%u)  # 1=Mon ... 6=Sat 7=Sun
if [ "$DAY_OF_WEEK" -ge 6 ]; then
    log "周末休市，跳过"
    exit 0
fi

# ---- 去重：今天已拉过则跳过 ----
if [ -f "$DATA_FILE" ]; then
    LAST_DATE=$(tail -1 "$DATA_FILE" | cut -d',' -f1)
    TODAY=$(date +%Y-%m-%d)
    if [ "$LAST_DATE" = "$TODAY" ]; then
        log "今日数据已存在 ($LAST_DATE)，跳过"
        exit 0
    fi
fi

# ---- 激活虚拟环境 ----
cd "$PROJECT_DIR"
if [ -f venv/bin/activate ]; then
    source venv/bin/activate
else
    log "[错误] 虚拟环境不存在"
    exit 1
fi

# ---- 拉取数据 ----
log "拉取主力合约数据..."
python3 data_fetcher.py 2>&1 || true
FETCH_EXIT=${PIPESTATUS[0]}
if [ $FETCH_EXIT -eq 0 ]; then
    log "✅ 数据更新成功"
else
    log "❌ 数据更新失败 (exit code: $FETCH_EXIT)"
    exit $FETCH_EXIT
fi

# ---- 发送预警邮件 ----
log "发送预警邮件..."
python3 alert.py 2>&1 || log "⚠️ 邮件发送失败（不影响数据更新）"

# ---- 推送到 GitHub（Streamlit Cloud 自动同步） ----
log "推送至 GitHub..."
git add data/ dashboard.py DEBUG.md scripts/ .gitignore 2>&1
git commit -m "auto: data update $(date +%Y-%m-%d %H:%M)" 2>&1 || log "无变更，跳过 commit"
git push 2>&1 || log "⚠️ 推送失败（检查网络）"

# ---- 清理旧日志 ----
find "$LOG_DIR" -name "*.log" -mtime +30 -delete

log "======== 更新完成 ========"
