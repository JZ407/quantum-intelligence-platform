@echo off
chcp 65001 >nul
cd /d "D:\Claude_code\rag_system"
C:\Python314\python.exe examples/run_daily_pipeline.py
echo [%date% %time%] Daily scrape completed >> daily_scrape.log
