@echo off
cd /d C:\Users\jesse\MLB_V2
if not exist logs mkdir logs
echo. >> logs\daily.log
echo ===== %DATE% %TIME% ===== >> logs\daily.log
python run_daily.py >> logs\daily.log 2>&1
