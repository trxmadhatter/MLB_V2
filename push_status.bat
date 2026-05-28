@echo off
cd /d C:\Users\jesse\MLB_V2
git add data/status.json
git diff --cached --quiet && exit /b 0
git commit -m "status: %date:~10,4%-%date:~4,2%-%date:~7,2% pipeline run"
git pull --rebase origin master
if %errorlevel% neq 0 exit /b %errorlevel%
git push origin master
