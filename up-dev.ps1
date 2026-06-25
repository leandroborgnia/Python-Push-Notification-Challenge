# up-dev.ps1 — thin Windows wrapper around scripts/up-dev.sh (US3).
#
# ALL orchestration lives in the bash script, run via WSL, so the behavior Windows developers
# run is identical to CI / Linux / prod (FR-004/005/006, SC-004). This wrapper does nothing but
# guard for WSL, forward args verbatim, and propagate the bash exit code. Do NOT add logic here
# — if you find yourself needing logic, it belongs in scripts/up-dev.sh.

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    Write-Error "WSL is required to run this wrapper. Install WSL (https://learn.microsoft.com/windows/wsl/install) or run scripts/up-dev.sh directly on Linux/CI."
    exit 1
}

wsl.exe bash "./scripts/up-dev.sh" @args
exit $LASTEXITCODE
