#!/bin/bash
# FarmTown Multi-Wallet Launcher
# Usage: ./farmtown-launcher.sh [start|stop|status|logs]

LOGDIR="/tmp/farmtown-logs"
mkdir -p "$LOGDIR"

WALLETS="w01 w02 w03 w04 w05 w06 w07 w08 w09 w10 w11"

start_wallet() {
    WALLET=$1
    LOGFILE="$LOGDIR/${WALLET}.log"
    PIDFILE="$LOGDIR/${WALLET}.pid"
    
    # Check if already running
    if [ -f "$PIDFILE" ] && kill -0 $(cat "$PIDFILE") 2>/dev/null; then
        echo "[$WALLET] already running (PID $(cat $PIDFILE))"
        return
    fi
    
    # Check if keypair exists
    if [ ! -f "/root/.farmtown-keypair-${WALLET}.json" ]; then
        echo "[$WALLET] keypair not found, skipping"
        return
    fi
    
    # Start bot
    PYTHONUNBUFFERED=1 python3 /root/farmtown-bot.py "$WALLET" > "$LOGFILE" 2>&1 &
    PID=$!
    echo $PID > "$PIDFILE"
    echo "[$WALLET] started (PID $PID) → $LOGFILE"
}

stop_wallet() {
    WALLET=$1
    PIDFILE="$LOGDIR/${WALLET}.pid"
    
    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill -9 "$PID" 2>/dev/null
            echo "[$WALLET] killed (PID $PID)"
        else
            echo "[$WALLET] not running (stale PID)"
        fi
        rm -f "$PIDFILE"
    else
        # Try to find by process
        PIDS=$(pgrep -f "farmtown-bot.py $WALLET" 2>/dev/null)
        if [ -n "$PIDS" ]; then
            echo "$PIDS" | xargs kill -9 2>/dev/null
            echo "[$WALLET] killed (found by process)"
        else
            echo "[$WALLET] not running"
        fi
    fi
}

status_wallet() {
    WALLET=$1
    PIDFILE="$LOGDIR/${WALLET}.pid"
    LOGFILE="$LOGDIR/${WALLET}.log"
    
    if [ -f "$PIDFILE" ] && kill -0 $(cat "$PIDFILE") 2>/dev/null; then
        PID=$(cat "$PIDFILE")
        LAST=$(tail -1 "$LOGFILE" 2>/dev/null | head -c 120)
        echo "[$WALLET] ✅ PID $PID | $LAST"
    else
        echo "[$WALLET] ❌ not running"
    fi
}

case "${1:-start}" in
    start)
        echo "🌾 Starting all FarmTown bots..."
        for W in $WALLETS; do start_wallet $W; sleep 1; done
        echo ""
        echo "Done! Logs: tail -f $LOGDIR/wXX.log"
        echo "Status: $0 status"
        ;;
    stop)
        echo "🛑 Stopping all FarmTown bots..."
        for W in $WALLETS; do stop_wallet $W; done
        ;;
    status)
        echo "🌾 FarmTown Bot Status:"
        for W in $WALLETS; do status_wallet $W; done
        ;;
    logs)
        WALLET=${2:-w01}
        echo "📋 Logs for $WALLET:"
        tail -20 "$LOGDIR/${WALLET}.log" 2>/dev/null || echo "No log file"
        ;;
    restart)
        $0 stop
        sleep 2
        $0 start
        ;;
    single)
        WALLET=${2:-w01}
        echo "🌾 Starting single wallet: $WALLET"
        start_wallet $WALLET
        ;;
    *)
        echo "Usage: $0 {start|stop|status|restart|logs [wallet]|single [wallet]}"
        echo ""
        echo "Wallets: $WALLETS"
        ;;
esac
