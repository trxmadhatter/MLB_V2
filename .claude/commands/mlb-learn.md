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
   - File name should reflect the topic (e.g. `pipeline-failures.md`, `scheduled-tasks.md`)
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

## Session learnings so far (2026-05-28)

- **`init_db` Postgres timeout crashes 10AM pipeline**: `ALTER TABLE ADD COLUMN` held by a lock at peak time → fixed with savepoints in `db.py` so each migration is independent
- **`MLB_V2_Refresh` trigger was date-bound**: Task created with `EndBoundary` = today, so it expired nightly → rebuilt as daily trigger with PT2H/PT4H repetition (12pm, 2pm, 4pm)
- **Streamlit dashboard is Streamlit Cloud, not local**: 10AM task was launching `streamlit run` locally → removed; cloud app reads DB directly and needs no local process
- **`&&` in 10AM task means one crash silences email**: If `run_daily.py` exits non-zero, email never runs — monitor `daily_log.txt` tail for crash traces
