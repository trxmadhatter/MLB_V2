@echo off
cd /d C:\Users\jesse\MLB_V2

python run_daily.py >> data\daily_log.txt 2>&1
if %errorlevel% neq 0 (
    echo [run_morning] pipeline failed, retrying in 60s... >> data\daily_log.txt
    timeout /t 60 /nobreak > nul
    python run_daily.py >> data\daily_log.txt 2>&1
)

python send_picks_email.py >> data\daily_log.txt 2>&1

call push_status.bat >> data\daily_log.txt 2>&1
