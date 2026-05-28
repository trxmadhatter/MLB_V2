# /mlb-run — Run Today's MLB V2 Pipeline

Run the full daily pipeline: pull odds, compute picks, send email, verify scheduled tasks are healthy.

## How the morning run works

The 10AM task runs `run_morning.bat` which:
1. Runs `python run_daily.py` — if it fails, waits 60s and retries once
2. Always runs `python send_picks_email.py` regardless of pipeline result
3. Always runs `push_status.bat` to commit and push `data/status.json` to GitHub

Do NOT run steps individually unless debugging. Use `run_morning.bat` to match what the scheduler does.

## Manual run steps (if needed)

1. **Check if already ran today**
   - Query `daily_picks` for today's date — if rows exist, skip `run_daily.py`
   - Or just run `run_morning.bat` — it handles everything

2. **Run manually**
   ```
   cmd /c C:\Users\jesse\MLB_V2\run_morning.bat
   ```

3. **Verify scheduled tasks are healthy**
   ```powershell
   $tasks = @("MLB_V2_10AM_Refresh", "MLB_V2_Refresh")
   foreach ($t in $tasks) {
       $i = Get-ScheduledTaskInfo -TaskName $t
       Write-Host "$t | Last result: $($i.LastTaskResult) | Next: $($i.NextRunTime)"
   }
   ```
   - Result `0` = success. Non-zero = check `data/daily_log.txt` tail, then invoke `/mlb-diagnose`

4. **Check status file**
   - `data/status.json` is pushed to GitHub after every run
   - Should show today's date, `pipeline_success: true`, `email_sent: true`

## Known issues and fixes

- **`init_db` statement timeout** (`psycopg2.errors.QueryCanceled`): Fixed in `db.py` with savepoints — each `ALTER TABLE` migration is independent; transient lock timeouts no longer crash the pipeline
- **FanGraphs 403**: Transient — signal scoring continues without pitcher FanGraphs data, not fatal
- **Email didn't send**: `run_morning.bat` now runs email unconditionally — if this happens, check `data/daily_log.txt` tail for a crash in `send_picks_email.py` itself
- **Streamlit dashboard**: Deployed at Streamlit Cloud, reads DB directly — do NOT launch `streamlit run dashboard.py` locally
- **Remote health check**: Scheduled at 10:15am PT via Claude routines — reads `data/status.json` from GitHub and reports STATUS: OK or STATUS: FAILED

## Self-update rule

After fixing any new failure mode, invoke `/mlb-learn` to record it.
