@echo off
cd /d C:\Users\jesse\MLB_V2
python run_daily.py --refresh >> data\refresh_log.txt 2>&1
