@echo off
cd /d "C:\Users\jesse\MLB_V2"
python grade_nightly.py >> "C:\Users\jesse\MLB_V2\data\grade_nightly.log" 2>&1
