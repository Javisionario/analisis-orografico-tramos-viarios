@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
set "DEVELOPMENT_DIR=%ROOT%Desarrollo"
set "APP_DIR=%DEVELOPMENT_DIR%\app"
set "VENV_DIR=%ROOT%.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "REQUIREMENTS=%DEVELOPMENT_DIR%\requirements.txt"
set "REQUIREMENTS_HASH_FILE=%VENV_DIR%\.requirements.sha256"

cd /d "%ROOT%"

if not exist "%REQUIREMENTS%" (
  echo ERROR: No se ha encontrado requirements.txt en "%DEVELOPMENT_DIR%".
  pause
  exit /b 1
)

if not exist "%VENV_PYTHON%" (
  echo Creando el entorno virtual local .venv...
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv "%VENV_DIR%"
  ) else (
    where python >nul 2>nul
    if errorlevel 1 (
      echo ERROR: Python no esta instalado o no esta disponible mediante "py" ni "python".
      pause
      exit /b 1
    )
    python -m venv "%VENV_DIR%"
  )

  if errorlevel 1 (
    echo ERROR: No se ha podido crear el entorno virtual local .venv.
    pause
    exit /b 1
  )

  if not exist "%VENV_PYTHON%" (
    echo ERROR: El entorno virtual se creo de forma incompleta: falta su ejecutable Python.
    pause
    exit /b 1
  )

)

set "REQUIREMENTS_HASH="
for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath '%REQUIREMENTS%').Hash"`) do set "REQUIREMENTS_HASH=%%H"

if not defined REQUIREMENTS_HASH (
  echo ERROR: No se ha podido calcular el hash de requirements.txt.
  pause
  exit /b 1
)

set "INSTALLED_REQUIREMENTS_HASH="
if exist "%REQUIREMENTS_HASH_FILE%" set /p "INSTALLED_REQUIREMENTS_HASH=" < "%REQUIREMENTS_HASH_FILE%"

if not "%REQUIREMENTS_HASH%"=="%INSTALLED_REQUIREMENTS_HASH%" (
  echo Instalando o actualizando dependencias...
  "%VENV_PYTHON%" -m pip install -r "%REQUIREMENTS%"
  if errorlevel 1 (
    echo ERROR: Ha fallado la instalacion de dependencias. Revise la conexion y el detalle anterior.
    pause
    exit /b 1
  )
  > "%REQUIREMENTS_HASH_FILE%" echo %REQUIREMENTS_HASH%
)

echo Orografia y Localizacion de Tramos Viarios
echo URL local: http://127.0.0.1:8025
echo Iniciando la aplicacion...
start "" "http://127.0.0.1:8025"
cd /d "%APP_DIR%"
"%VENV_PYTHON%" app.py
if errorlevel 1 (
  echo ERROR: La aplicacion se ha detenido con un error. Revise el detalle anterior.
  pause
  exit /b 1
)

endlocal
