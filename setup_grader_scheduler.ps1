# setup_grader_scheduler.ps1
# Run once in PowerShell. Re-running is safe — -Force overwrites the existing task.

$scriptDir = "C:\Users\jesse\MLB_V2"
$batPath   = Join-Path $scriptDir "grade_nightly.bat"

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$batPath`"" `
    -WorkingDirectory $scriptDir

$trigger = New-ScheduledTaskTrigger -Daily -At "10:00PM"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit  (New-TimeSpan -Minutes 30) `
    -RestartCount        2 `
    -RestartInterval     (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName    "MLB_V2_GradeNightly" `
    -Action      $action `
    -Trigger     $trigger `
    -Settings    $settings `
    -RunLevel    Limited `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName "MLB_V2_GradeNightly"
$nextRun = ($task | Get-ScheduledTaskInfo).NextRunTime
Write-Host "MLB_V2_GradeNightly registered. Next run: $nextRun"
Write-Host "Logs will appear in: $scriptDir\data\grade_nightly.log"
Write-Host ""
Write-Host "To run manually:   Start-ScheduledTask -TaskName MLB_V2_GradeNightly"
Write-Host "To disable:        Disable-ScheduledTask -TaskName MLB_V2_GradeNightly"
Write-Host "To unregister:     Unregister-ScheduledTask -TaskName MLB_V2_GradeNightly -Confirm:`$false"
