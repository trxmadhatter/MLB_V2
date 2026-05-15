# setup_scheduler.ps1
# Run once in PowerShell (Admin not required for current user tasks).
# Re-running is safe — -Force overwrites the existing task.

$scriptDir = "C:\Users\jesse\MLB_V2"
$batPath   = Join-Path $scriptDir "run_daily_logged.bat"

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$batPath`"" `
    -WorkingDirectory $scriptDir

$trigger = New-ScheduledTaskTrigger -Daily -At "05:30AM"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit  (New-TimeSpan -Minutes 30) `
    -RestartCount        2 `
    -RestartInterval     (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName    "MLB_V2_Daily" `
    -Action      $action `
    -Trigger     $trigger `
    -Settings    $settings `
    -RunLevel    Limited `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName "MLB_V2_Daily"
$nextRun = ($task | Get-ScheduledTaskInfo).NextRunTime
Write-Host "MLB_V2_Daily registered. Next run: $nextRun"
Write-Host "Logs will appear in: $scriptDir\logs\daily.log"
Write-Host ""
Write-Host "To run manually:   Start-ScheduledTask -TaskName MLB_V2_Daily"
Write-Host "To disable:        Disable-ScheduledTask -TaskName MLB_V2_Daily"
Write-Host "To unregister:     Unregister-ScheduledTask -TaskName MLB_V2_Daily -Confirm:`$false"
