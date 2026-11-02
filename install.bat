@echo off
set "D=%~dp0"
reg add "HKCU\Software\Classes\rbx2014" /ve /d "URL:ROBLOX 2014" /f
reg add "HKCU\Software\Classes\rbx2014" /v "URL Protocol" /d "" /f
reg add "HKCU\Software\Classes\rbx2014\shell\open\command" /ve /d "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%D%launch.ps1\" \"%%1\"" /f
echo Done. The Play button on the website can now open this client.
pause
