$gitCmd = Get-Command git -ErrorAction SilentlyContinue
if (-not $gitCmd) {
    Write-Error "Git not found on PATH. Install Git for Windows to use dxrk-guardian from PowerShell."
    exit 1
}
$bash = Join-Path (Split-Path (Split-Path $gitCmd.Source)) "bin\bash.exe"
if (-not (Test-Path $bash)) {
    Write-Error "Git Bash not found at '$bash'. Reinstall Git for Windows."
    exit 1
}
& $bash -c "dxrk-guardian $args"
exit $LASTEXITCODE
