$ErrorActionPreference = "Stop"
$repo = "Murhaf-Mo/moodlectl"

Write-Host ""
Write-Host "moodlectl installer" -ForegroundColor Cyan
Write-Host "===================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Fetching latest release..."
try {
    $release = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest"
} catch {
    Write-Error "Could not reach GitHub. Check your internet connection and try again."
    exit 1
}

$asset = $release.assets | Where-Object { $_.name -like "moodlectl-setup*.exe" } | Select-Object -First 1

if (-not $asset) {
    Write-Error "No installer found in the latest release. Visit https://github.com/$repo/releases"
    exit 1
}

$tmp = Join-Path $env:TEMP $asset.name
Write-Host "Downloading $($asset.name) (this may take a moment)..."
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $tmp -UseBasicParsing

Write-Host "Installing..."
Start-Process -FilePath $tmp -ArgumentList "/SILENT", "/SP-", "/SUPPRESSMSGBOXES" -Wait

Remove-Item $tmp -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "moodlectl installed successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Open a NEW terminal window (so PATH is refreshed)"
Write-Host "  2. Run: moodlectl auth login"
Write-Host "     Chrome will open — log in with your CCK credentials."
Write-Host "     The window closes automatically when done."
Write-Host ""
Write-Host "Then try: moodlectl --help"
