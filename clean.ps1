# clean.ps1 — быстрая очистка проекта
$ErrorActionPreference = "SilentlyContinue"

Write-Host "🧹 Очистка артефактов сборки..." -ForegroundColor Cyan

# PyInstaller
Remove-Item -Recurse -Force build, dist
Remove-Item -Force *.spec

# Python кеш
Get-ChildItem -Path . -Include "__pycache__" -Recurse -Directory | Remove-Item -Recurse -Force
Get-ChildItem -Path . -Include "*.pyc" -Recurse -File | Remove-Item -Force

# Логи
Remove-Item -Force *.log -ErrorAction SilentlyContinue

Write-Host "✅ Очистка завершена" -ForegroundColor Green
Get-ChildItem | Select-Object Name, Length