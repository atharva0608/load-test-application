#!/bin/bash
# ─────────────────────────────────────────────────────────────────
# StressForge Port-Forward
#   StressForge UI  → http://localhost:8083
#   Locust dashboard → http://localhost:8084
#
# Auto-restarts each forward if it drops.
# Usage: ./stressforge-portforward.sh
# Stop:  Ctrl+C
# ─────────────────────────────────────────────────────────────────

NAMESPACE="stressforge"
FRONTEND_LOCAL=8083
LOCUST_LOCAL=8084

cleanup() {
  echo ""
  echo "Stopping port-forwards..."
  kill "$PID_FRONTEND" "$PID_LOCUST" 2>/dev/null
  exit 0
}
trap cleanup SIGINT SIGTERM

forward_frontend() {
  while true; do
    kubectl port-forward svc/frontend ${FRONTEND_LOCAL}:80 -n ${NAMESPACE} 2>/dev/null
    echo "[$(date +%T)] frontend port-forward dropped, restarting in 2s..."
    sleep 2
  done
}

forward_locust() {
  while true; do
    kubectl port-forward svc/locust ${LOCUST_LOCAL}:8089 -n ${NAMESPACE} 2>/dev/null
    echo "[$(date +%T)] locust port-forward dropped, restarting in 2s..."
    sleep 2
  done
}

echo "────────────────────────────────────────────"
echo "  StressForge UI   →  http://localhost:${FRONTEND_LOCAL}"
echo "  Locust dashboard →  http://localhost:${LOCUST_LOCAL}"
echo "  Press Ctrl+C to stop"
echo "────────────────────────────────────────────"

forward_frontend &
PID_FRONTEND=$!

forward_locust &
PID_LOCUST=$!

wait
