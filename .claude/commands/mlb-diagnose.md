# /mlb-diagnose — Diagnose MLB V2 Pipeline Failures

Systematically find why the pipeline, email, or scheduled tasks didn't run.

## Diagnosis sequence

### 1. Check status file first (fastest)
```powershell
Get-Content "C:\Users\jesse\MLB_V2\data\status.json"
```
- `pipeline_success: false` or missing file → pipeline crashed, check log
- `email_sent: false` → pipeline ran but email script failed
- `date` != today → pipeline didn't run at all today

### 2. Check scheduled task last results
```powershell
$tasks = @("MLB_V2_10AM_Refresh", "MLB_V2_Refresh", "MLB_V2_GradeNightly")
foreach ($t in $tasks) {
    $info = Get-ScheduledTaskInfo -TaskName $t
    $task = Get-ScheduledTask -TaskName $t
    Write-Host "$t | Last: $($info.LastRunTime) | Result: $($info.LastTaskResult) | Next: $($info.NextRunTime)"
    foreach ($a in $task.Actions) { Write-Host "  -> $($a.Execute) $($a.Arguments)" }
}
```
- Result `0` = success
- Result `1` = script exited non-zero (check log)
- Result `2147942403` = file not found (bat file path wrong)

### 3. Check the daily log tail
```powershell
Get-Content "C:\Users\jesse\MLB_V2\data\daily_log.txt" -Tail 80
```
Look for: `Traceback`, `Error`, `Exception`, `timeout`, `403`, `KeyError`
Note: `[run_morning] pipeline failed, retrying in 60s...` means first attempt failed but retry ran — check if second attempt succeeded.

### 4. Check the refresh log
```powershell
Get-Content "C:\Users\jesse\MLB_V2\data\refresh_log.txt" -Tail 40
```

### 5. Verify refresh task schedule
```powershell
$t = Get-ScheduledTask -TaskName "MLB_V2_Refresh"
Write-Host "Interval: $($t.Triggers[0].Repetition.Interval) Duration: $($t.Triggers[0].Repetition.Duration)"
```
- Should be `Interval: PT2H  Duration: PT4H` (runs 12pm, 2pm, 4pm daily)
- If trigger is date-bound (`EndBoundary` set to today), rebuild it — see fix below

### 6. Test pipeline manually
```
cmd /c C:\Users\jesse\MLB_V2\run_morning.bat
```

## Known failure modes

| Symptom | Root cause | Fix |
|---------|-----------|-----|
| `psycopg2.errors.QueryCanceled` in `init_db` | Postgres lock timeout on ALTER TABLE | Savepoints in `db.py` handle this — if recurs, check for blocking queries on `daily_picks` or `daily_game_picks` |
| `status.json` missing or stale date | Pipeline crashed before writing status | Check log tail for traceback; run `run_morning.bat` manually |
| `email_sent: false` in status.json | `send_picks_email.py` crashed after pipeline succeeded | Check log for email error; run `python send_picks_email.py` manually |
| `[run_morning] pipeline failed, retrying` in log | First attempt crashed (transient issue) | Check if retry succeeded — if both failed, look for the root error above the retry message |
| `MLB_V2_Refresh` not firing tomorrow | Task trigger was date-bound (EndBoundary = today) | Rebuild with XML: daily trigger, PT2H interval, PT4H duration, start 12pm |
| FanGraphs 403 | FanGraphs API blocking scraper | Non-fatal — pipeline continues without pitcher FanGraphs signals |
| `streamlit run` launched locally | Old task config had `start "" python -m streamlit run` | Dashboard is Streamlit Cloud — remove local launch from task action |
| Quota warning < 5000 remaining | Too many API calls | Check for duplicate scheduled tasks pulling odds |
| Task result `2147942403` | Bat file not found at path in task action | Verify bat file exists; update task action path |

## Rebuild MLB_V2_Refresh trigger (if date-bound)
Export XML → change `<Duration>PT4H</Duration>` + remove `<EndBoundary>` + ensure `<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>` → re-import with `schtasks /delete` + `schtasks /create /xml`

## Self-update rule

When a new failure mode is found and fixed, invoke `/mlb-learn` to add it to this table.
