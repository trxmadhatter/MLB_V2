@echo off
cd /d "C:\Users\jesse\MLB_V2"
python run_daily.py >> "C:\Users\jesse\MLB_V2\data\daily_log.txt" 2>&1
python send_picks_email.py >> "C:\Users\jesse\MLB_V2\data\daily_log.txt" 2>&1
start "" python -m streamlit run "C:\Users\jesse\MLB_V2\dashboard.py"
