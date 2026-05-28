# /mlb-run — Run Today's MLB V2 Pipeline

Run the full daily pipeline: pull odds, compute picks, send email, verify scheduled tasks are healthy.

## Steps

1. **Check if already ran today**
   - Query `daily_picks` for today's date — if rows exist, skip `run_daily.py` and go to step 3
   - If no rows, run `python run_daily.py`

2. **Send picks email**
   - Run `python send_picks_email.py`
   - Confirm "Email sent" in output

3. **Verify scheduled tasks are healthy**
   - Check `MLB_V2_10AM_Refresh` last result (should be 0)
   - Check `MLB_V2_Refresh` next run time is today or tomorrow at 12pm
   - If last result is non-zero on either task, invoke `/mlb-diagnose`

4. **Report summary**
   - Today's date, picks evaluated, bets/leans/watches found
   - Email status
   - Next refresh time
   - Any warnings (FanGraphs 403, quota remaining, etc.)

## Known issues and fixes

- **`init_db` statement timeout** (`psycopg2.errors.QueryCanceled`): Fixed in db.py with savepoints — if this recurs, check for long-running Postgres queries holding locks
- **FanGraphs 403**: Transient — signal scoring runs without pitcher FanGraphs data, not fatal
- **`&&` chain breaks if run_daily.py exits non-zero**: The 10AM task uses `&&` so email won't send if pipeline crashes — check `data/daily_log.txt` tail for the error
- **Streamlit dashboard**: Deployed at Streamlit Cloud, not run locally — do NOT launch `streamlit run dashboard.py` locally

## Self-update rule

After fixing any new failure mode, invoke `/mlb-learn` to record it.
