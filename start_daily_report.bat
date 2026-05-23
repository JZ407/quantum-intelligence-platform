@echo off
cd /d "D:\Claude_code\rag_system"
echo =========================================
echo   量科每日讯日报生成器
echo =========================================
echo.
echo 启动中，请稍候...
echo.
start /b python -m streamlit run examples\daily_report_app.py --server.address 0.0.0.0 --server.port 8501 > streamlit.log 2>&1
timeout /t 3 /nobreak >nul
echo 已启动，可通过以下地址访问：
echo.
echo   本机：    http://localhost:8501
echo   局域网：  http://192.168.5.113:8501
echo   公网：    http://38.150.71.74:8501
echo.
pause
