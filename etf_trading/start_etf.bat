@echo off
title Antigravity Cloud - ETF Trading 212
echo ========================================================
echo   Antigravity Cloud - Bot ETF Trading 212
echo ========================================================
echo.
echo Verification des dependances Python...
pip install -r requirements.txt
echo.
echo Lancement du Tableau de Bord Web sur http://localhost:8085...
echo.
python main.py --web
pause
