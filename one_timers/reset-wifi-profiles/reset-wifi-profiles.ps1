# reset-wifi-profiles.ps1
# Deletes all saved Windows Wi-Fi profiles.
# Makes a backup export first.

$ErrorActionPreference = "Continue"

Write-Host "🛜 Windows Wi-Fi profile reset goblin starting..." -ForegroundColor Cyan

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $env:USERPROFILE "Desktop\wifi-profile-backup-$timestamp"

New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

Write-Host "`n📦 Backing up existing Wi-Fi profiles to:"
Write-Host $backupDir -ForegroundColor Yellow

netsh wlan export profile key=clear folder="$backupDir" | Out-Host

Write-Host "`n📋 Current profiles:" -ForegroundColor Cyan
$profilesRaw = netsh wlan show profiles

$profiles = $profilesRaw |
    Select-String "All User Profile\s*:\s*(.+)$" |
    ForEach-Object { $_.Matches[0].Groups[1].Value.Trim() }

if (-not $profiles -or $profiles.Count -eq 0) {
    Write-Host "No Wi-Fi profiles found. The pantry is already empty." -ForegroundColor Green
} else {
    foreach ($profile in $profiles) {
        Write-Host "🗑️ Deleting Wi-Fi profile: $profile" -ForegroundColor Yellow
        netsh wlan delete profile name="$profile" | Out-Host
    }
}

Write-Host "`n🔄 Restarting WLAN AutoConfig service..." -ForegroundColor Cyan
Restart-Service WlanSvc -Force

Write-Host "`n🧹 Optional network cache cleanup..." -ForegroundColor Cyan
ipconfig /flushdns | Out-Host
arp -d * | Out-Host

Write-Host "`n✅ Done. All saved Wi-Fi profiles should be gone." -ForegroundColor Green
Write-Host "Backup saved at: $backupDir" -ForegroundColor Yellow

Write-Host "`nRecommended next step:"
Write-Host "1. Turn ELRS Wi-Fi mode on"
Write-Host "2. Wait for SSID"
Write-Host "3. Connect fresh"
Write-Host "4. Open http://10.0.0.1/"
