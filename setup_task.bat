schtasks /create /tn "QuantumDailyScrape" /tr "D:\Claude_code\rag_system\daily_scrape.bat" /sc daily /st 13:30 /f
pause
