# windows-watchdog.ps1 — hongyan's keeper on Windows.
#
# Scheduled every 5 minutes with highest privileges. Mirrors the Linux
# watchdog contract: quietly start what is missing, stay silent when healthy,
# log everything. Process death on Windows is otherwise permanent until a
# reboot — this is the piece that makes the bot survivable.
#
# Edit the three paths below, then register:
#   schtasks /create /tn "hongyan watchdog" /sc minute /mo 5 /ru YOU /rl HIGHEST ^
#     /tr "powershell -NoProfile -ExecutionPolicy Bypass -File C:\hongyan\windows-watchdog.ps1"

# --- edit these three lines ----------------------------------------------
$SignalCliJar = "C:\signal-cli\signal-cli.jar"
$BotNumber    = "+1BOTNUMBER"
$ListenerPath = "C:\hongyan\hongyan_listener.py"
$Log          = "C:\hongyan\watchdog.log"
# --------------------------------------------------------------------------

function Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" | Add-Content $Log
    if ((Get-Item $Log).Length -gt 1MB) { Set-Content $Log "" }
}

# --- daemon: is anything listening on the JSON-RPC port? -------------------
$daemonUp = Get-NetTCPConnection -LocalPort 7583 -State Listen -ErrorAction SilentlyContinue
if (-not $daemonUp) {
    Log "daemon down - starting"
    Start-Process java -ArgumentList @(
        "-jar", $SignalCliJar, "-a", $BotNumber, "daemon",
        "--tcp", "127.0.0.1:7583",
        "--receive-mode", "on-connection", "--no-receive-stdout"
    ) -WindowStyle Hidden
    Start-Sleep -Seconds 20   # first upstream connect is slow
} 

# --- listener: is a python process running the listener script? ------------
$listenerUp = Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -like "*hongyan_listener*" }
if (-not $listenerUp) {
    Log "listener down - starting"
    Start-Process python -ArgumentList $ListenerPath -WindowStyle Hidden
    Start-Sleep -Seconds 5
}
