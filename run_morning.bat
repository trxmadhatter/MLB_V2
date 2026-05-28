@echo off
cd /d C:\Users\jesse\MLB_V2

python run_daily.py >> data\daily_log.txt 2>&1
if %errorlevel% neq 0 (
    echo [run_morning] pipeline failed, retrying in 60s... >> data\daily_log.txt
    timeout /t 60 /nobreak > nul
    python run_daily.py >> data\daily_log.txt 2>&1
)
set PIPELINE_RESULT=%errorlevel%

if %PIPELINE_RESULT% neq 0 (
    echo [run_morning] both pipeline attempts failed, skipping email >> data\daily_log.txt
    powershell -NoProfile -Command "$status = @{ date = (Get-Date).ToString('yyyy-MM-dd'); ran_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); picks_evaluated = 0; bets_found = 0; email_sent = $false; pipeline_success = $false }; Set-Content -Encoding UTF8 data\status.json -Value (ConvertTo-Json $status)" >> data\daily_log.txt 2>&1
) else (
    python send_picks_email.py >> data\daily_log.txt 2>&1
)

call push_status.bat >> data\daily_log.txt 2>&1
