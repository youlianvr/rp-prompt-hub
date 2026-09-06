@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "dist\index.html" (
  echo Сначала собери: python build_rp_hub.py
  pause
  exit /b 1
)
echo Раздаю сайт на http://0.0.0.0:8765
echo Друзья в той же сети открывают http://ТВОЙ_ЛОКАЛЬНЫЙ_IP:8765
echo (узнать IP: ipconfig  -  IPv4-адрес)
python -m http.server 8765 --directory dist --bind 0.0.0.0
