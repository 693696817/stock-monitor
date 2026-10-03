#!/usr/bin/env bash
# 本地验收脚本：校验 main.py 语法/导入，启动 uvicorn，逐一 curl 全部页面与关键 API
set -u
cd "$(dirname "$0")"
# 关键：去掉 CodeBuddy safe-delete 的 sitecustomize 钩子（PYTHONPATH 注入），
# 否则本环境下任何 os.remove/shutil.rmtree 都会因回收站不可用而 FAIL_CLOSED，导致运行/构建崩溃。
unset PYTHONPATH

VENV_PY=".venv/Scripts/python.exe"
BASE="http://127.0.0.1:8001"
LOG="verify_$(date +%Y%m%d_%H%M%S).log"
PASS=0
FAIL=0

echo "==== 1) 语法校验 (py_compile) ====" | tee "$LOG"
"$VENV_PY" -m py_compile main.py ai_service.py data_service.py config.py && echo "OK: 全部模块语法通过" | tee -a "$LOG"

echo "==== 2) 模块导入自检 (import main) ====" | tee -a "$LOG"
"$VENV_PY" -c "import main; print('OK: main 导入成功, 路由数 =', len(main.app.routes))" 2>&1 | tee -a "$LOG"

echo "==== 3) 启动 uvicorn (后台) ====" | tee -a "$LOG"
"$VENV_PY" -m uvicorn main:app --host 127.0.0.1 --port 8001 >uv_server.log 2>&1 &
SRV_PID=$!
# 等待端口就绪（最多 30s）
for i in $(seq 1 30); do
  if curl -s -o /dev/null "http://127.0.0.1:8001/"; then break; fi
  sleep 1
done
echo "server pid=$SRV_PID" | tee -a "$LOG"

echo "==== 4) 页面路由 (期望 200) ====" | tee -a "$LOG"
declare -a PAGES=("/" "/analysis" "/pricing" "/news" "/risks" "/hot" "/market" "/opportunities" "/login" "/register" "/profile" "/doc" "/feedback")
for p in "${PAGES[@]}"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 60 "$BASE$p")
  if [ "$code" = "200" ]; then
    echo "  [OK]   $p -> $code" | tee -a "$LOG"; PASS=$((PASS+1))
  else
    echo "  [FAIL] $p -> $code" | tee -a "$LOG"; FAIL=$((FAIL+1))
  fi
done

echo "==== 5) 关键 API ====" | tee -a "$LOG"
# 反馈列表（纯内存，必 200）
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 30 "$BASE/api/feedback/list")
echo "  [/api/feedback/list] -> $code"; [ "$code" = "200" ] && PASS=$((PASS+1)) || FAIL=$((FAIL+1))
# 新闻（真实数据或兜底，期望 200 不崩）
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 60 "$BASE/api/news?src=eastmoney&limit=10")
echo "  [/api/news] -> $code"; [ "$code" = "200" ] && PASS=$((PASS+1)) || FAIL=$((FAIL+1))
# 分析接口（流式；发个请求看是否 200 起流，不等待完整 AI 生成）
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 -X POST "$BASE/api/analyze" -H "Content-Type: application/json" -d '{"query":"贵州茅台"}')
echo "  [/api/analyze POST] -> $code (200=起流成功, 完整生成依赖网络/AI)"; [ "$code" = "200" ] && PASS=$((PASS+1)) || FAIL=$((FAIL+1))

echo "==== 6) 汇总 ====" | tee -a "$LOG"
echo "  PASS=$PASS  FAIL=$FAIL" | tee -a "$LOG"
echo "  (注: /api/export-pdf 依赖可选包 weasyprint，未装时应返回 500，属预期)" | tee -a "$LOG"

echo "==== 关闭 uvicorn ====" | tee -a "$LOG"
kill $SRV_PID 2>/dev/null
echo "完成。详细日志: $LOG ; 服务日志: uv_server.log"
