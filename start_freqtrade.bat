@echo off
title Antigravity Cloud - Crypto Freqtrade FreqAI
echo ========================================================
echo   Antigravity Cloud - Bot Crypto Binance (Freqtrade + FreqAI)
echo ========================================================
echo.
echo Verification et lancement du conteneur Docker...
docker compose up -d
echo.
echo ========================================================
echo   Bot Crypto demarre avec succes !
echo   Interface Web FreqUI : http://localhost:8082
echo   Utilisateur          : freqtrader
echo   Mot de passe         : SuperSecurePassword123!
echo ========================================================
echo.
pause
