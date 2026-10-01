@echo off
taskkill /fi "WINDOWTITLE eq Meterbot - dorm web*" /t /f >nul 2>nul
taskkill /fi "WINDOWTITLE eq Meterbot - robot*" /t /f >nul 2>nul
echo Stopped.
timeout /t 2 >nul
