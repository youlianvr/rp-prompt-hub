@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Собираю RP Prompt Hub...
python build_rp_hub.py
if errorlevel 1 (
  echo.
  echo СБОРКА УПАЛА — глянь ошибку выше.
  pause
  exit /b 1
)
start "" "%~dp0dist\index.html"
