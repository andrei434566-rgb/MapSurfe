@echo off
set "APP_DIR=%~dp0"
set "PYTHON=%APP_DIR%..\.venv\Scripts\pythonw.exe"
if not exist "%PYTHON%" (
    echo Ne naiden Python v okruzhenii proekta.
    echo Ozhidaetsya: %PYTHON%
    pause
    exit /b 1
)
start "" "%PYTHON%" "%APP_DIR%paleoatlas_qt.pyw"
