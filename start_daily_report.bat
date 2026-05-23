@echo off
chcp 65001 >nul
cd /d "D:\Claude_code\rag_system"
echo =========================================
echo    Quantike Daily Report Generator
echo =========================================
echo.
echo Starting Streamlit...
echo.
C:\Python314\python.exe -m streamlit run examples\daily_report_app.py --server.address 0.0.0.0 --server.port 8501
pause
