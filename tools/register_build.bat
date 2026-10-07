@echo off
chcp 65001 >nul
echo ============================================================
echo 📦 РЕГИСТРАЦИЯ БИЛДА НА СЕРВЕРЕ
echo ============================================================
echo.

cd /d "%~dp0"

REM === Проверка переменных окружения ===
if "%API_SECRET_KEY%"=="" (
    echo ❌ Переменная API_SECRET_KEY не установлена!
    echo.
    echo Установите её командой:
    echo   set API_SECRET_KEY=ваш_api_key
    echo.
    pause
    exit /b 1
)

if "%MASTER_API_KEY%"=="" (
    echo ❌ Переменная MASTER_API_KEY не установлена!
    echo.
    echo Установите её командой:
    echo   set MASTER_API_KEY=ваш_мастер_ключ
    echo.
    pause
    exit /b 1
)

REM === Проверка существования .exe ===
if not exist "dist\inventory_app.exe" (
    echo ❌ Файл dist\inventory_app.exe не найден!
    echo    Сначала соберите проект:
    echo    python -m PyInstaller --clean --noconfirm inventory_app.spec
    pause
    exit /b 1
)

REM === [1/3] Вычисление хеша через Python ===
echo [1/3] Вычисление SHA-256 хеша inventory_app.exe...

for /f "usebackq delims=" %%a in (`python -c "import hashlib; h=hashlib.sha256(); f=open(r'dist\inventory_app.exe','rb'); [h.update(c) for c in iter(lambda: f.read(8192), b'')]; f.close(); print(h.hexdigest())"`) do set HASH=%%a

if "%HASH%"=="" (
    echo ❌ Не удалось вычислить хеш!
    echo    Проверьте что Python установлен
    pause
    exit /b 1
)

echo ✅ Хеш: %HASH%
echo.

REM === [2/3] Запрос версии ===
set /p VERSION="Введите версию (например, 1.8.1): "

if "%VERSION%"=="" (
    echo ❌ Версия не указана!
    pause
    exit /b 1
)

echo.
echo [3/3] Регистрация на сервере...
echo.
echo   URL:     https://78.17.47.74:8443/api/admin/register-build
echo   Версия:  %VERSION%
echo   Хеш:     %HASH:~0,16%...
echo.

REM === Отправка запроса на сервер ===
curl -s -w "\nHTTP_CODE:%%{http_code}\n" -X POST "https://78.17.47.74:8443/api/admin/register-build" ^
  -H "X-API-Key: %API_SECRET_KEY%" ^
  -H "X-Master-Key: %MASTER_API_KEY%" ^
  -H "Content-Type: application/json" ^
  -k ^
  -d "{\"exe_hash\": \"%HASH%\", \"version\": \"%VERSION%\"}"

echo.
echo ============================================================
if %errorlevel% == 0 (
    echo ✅ РЕГИСТРАЦИЯ ЗАВЕРШЕНА
) else (
    echo ❌ ОШИБКА РЕГИСТРАЦИИ
)
echo ============================================================
echo.
echo Хеш:    %HASH%
echo Версия: %VERSION%
echo.

REM === Проверка списка билдов ===
echo [Проверка] Получаем список билдов с сервера...
echo.
curl -s -k -H "X-API-Key: %API_SECRET_KEY%" -H "X-Master-Key: %MASTER_API_KEY%" "https://78.17.47.74:8443/api/admin/builds"
echo.
echo.

pause