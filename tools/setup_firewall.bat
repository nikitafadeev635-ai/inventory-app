@echo off
chcp 65001 >nul
echo ============================================================
echo 🔥 НАСТРОЙКА FIREWALL ДЛЯ QFACT
echo ============================================================
echo.

REM Проверка прав администратора
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ❌ ОШИБКА: Запустите скрипт от имени АДМИНИСТРАТОРА!
    echo.
    echo Правой кнопкой на файл → "Запуск от имени администратора"
    pause
    exit /b 1
)

echo ✓ Права администратора получены
echo.

REM Путь к .exe (измените если нужно)
set EXE_PATH=C:\QFactInv\inventory_app.exe

if not exist "%EXE_PATH%" (
    echo ❌ Файл не найден: %EXE_PATH%
    echo    Укажите правильный путь в переменной EXE_PATH
    pause
    exit /b 1
)

echo [1/3] Удаление старого правила (если было)...
netsh advfirewall firewall delete rule name="QFact Sync Server" >nul 2>&1
echo     ✓ Старое правило удалено (если существовало)
echo.

echo [2/3] Добавление нового правила...
netsh advfirewall firewall add rule name="QFact Sync Server" dir=in action=allow program="%EXE_PATH%" protocol=TCP localport=8080
if %errorLevel% equ 0 (
    echo     ✓ Правило успешно добавлено
) else (
    echo     ❌ Ошибка добавления правила
    pause
    exit /b 1
)
echo.

echo [3/3] Проверка...
netsh advfirewall firewall show rule name="QFact Sync Server"
echo.

echo ============================================================
echo ✅ НАСТРОЙКА ЗАВЕРШЕНА
echo ============================================================
echo.
echo Что было сделано:
echo   • Разрешены входящие подключения к inventory_app.exe
echo   • Открыт только порт 8080 (TCP)
echo   • Все остальные порты защищены firewall
echo.
echo Теперь телефон сможет подключиться к приложению!
echo.
pause