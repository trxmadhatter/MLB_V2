@echo off
cd /d C:\Users\jesse\MLB_V2
git add data/status.json
git diff --cached --quiet && exit /b 0
git commit -m "status: %date:~10,4%-%date:~4,2%-%date:~7,2% pipeline run"
git push origin master
