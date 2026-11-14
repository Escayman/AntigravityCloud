Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "   Antigravity Cloud - Bot Crypto Binance (Freqtrade + FreqAI)" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Lancement de Freqtrade dans Docker..." -ForegroundColor Yellow
docker compose up -d
Write-Host ""
Write-Host "Interface Web FreqUI : http://localhost:8082" -ForegroundColor Green
Write-Host "Utilisateur          : freqtrader" -ForegroundColor Green
Write-Host "Mot de passe         : SuperSecurePassword123!" -ForegroundColor Green
