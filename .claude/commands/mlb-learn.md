# /mlb-learn — Capture Session Learnings

After fixing a bug, diagnosing a failure, or making a structural change — run this to update the skill system and memory so the fix is never re-discovered.

## Steps

1. **Identify what was learned this session**
   - What broke and why
   - What the fix was (code change, task config change, etc.)
   - Whether it's a recurring risk or one-time

2. **Update `/mlb-diagnose` known failure modes table**
   - Add new row: Symptom | Root cause | Fix
   - If an existing row was incomplete or wrong, correct it

3. **Update `/mlb-run` known issues section**
   - Add any new gotcha that affects the daily run flow

4. **Update project memory**
   - Write or update a memory file in `C:\Users\jesse\.claude\projects\C--Users-jesse-MLB-V2\memory\`
   - Use the standard frontmatter format with type: `project` or `feedback`

5. **Commit the skill changes**
   - `git add .claude/commands/`
   - Commit with message: `docs: update mlb skills with session learnings — <one-line summary>`

## What NOT to capture
- Things already in code (the fix is in the diff)
- Git history (use `git log` for that)
- Ephemeral state (today's picks, quota used, etc.)

## Capture format for failure modes
```
| <symptom visible in log/output> | <root cause — why it happens> | <fix — what to do> |
```

## Session learnings (2026-05-28)

- **`init_db` Postgres timeout crashes pipeline**: `ALTER TABLE ADD COLUMN` held by a lock → fixed with savepoints in `db.py`
- **`MLB_V2_Refresh` trigger was date-bound**: Task had `EndBoundary` = today → rebuilt as daily with PT2H/PT4H repetition (12pm, 2pm, 4pm)
- **Streamlit dashboard is Streamlit Cloud**: Old 10AM task launched it locally → removed; cloud app reads DB directly
- **`&&` chain silenced email on crash**: Replaced with `run_morning.bat` — retries pipeline once on failure, always runs email and status push
- **Status file for remote health checks**: `data/status.json` written by `run_daily.py`, `email_sent` flipped by `send_picks_email.py`, pushed to GitHub by `push_status.bat` after every run
- **Remote health check routine**: Scheduled at 10:15am PT daily via Claude routines (trig_01FQVsj5m8WLquEzVsPuDo2D) — reads `data/status.json` from GitHub repo
