@echo off
:: This file must use CRLF line endings for Windows CMD.
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

set "PROJECT_DIR=%~dp0"

echo ============================================================
echo  tickets_hunter 啟動程式 - Windows
echo ============================================================
echo.

if not exist "%PROJECT_DIR%src\settings.py" (
    echo [錯誤] 找不到：%PROJECT_DIR%src\settings.py
    echo 請把這個批次檔放在 tickets_hunter 專案根目錄。
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"
set /p "CONDA_ENV=請輸入要使用的 Conda 環境名稱；使用本機 Python 請輸入 0："

if not defined CONDA_ENV (
    echo [錯誤] 未輸入任何內容。
    pause
    exit /b 1
)

if "%CONDA_ENV%"=="0" goto RUN_PROGRAM

set "CONDA_BAT="
for /f "delims=" %%I in ('where conda.bat 2^>nul') do if not defined CONDA_BAT set "CONDA_BAT=%%I"

if not defined CONDA_BAT if exist "%USERPROFILE%\anaconda3\condabin\conda.bat" set "CONDA_BAT=%USERPROFILE%\anaconda3\condabin\conda.bat"
if not defined CONDA_BAT if exist "%USERPROFILE%\miniconda3\condabin\conda.bat" set "CONDA_BAT=%USERPROFILE%\miniconda3\condabin\conda.bat"
if not defined CONDA_BAT if exist "%LOCALAPPDATA%\anaconda3\condabin\conda.bat" set "CONDA_BAT=%LOCALAPPDATA%\anaconda3\condabin\conda.bat"
if not defined CONDA_BAT if exist "%LOCALAPPDATA%\miniconda3\condabin\conda.bat" set "CONDA_BAT=%LOCALAPPDATA%\miniconda3\condabin\conda.bat"
if not defined CONDA_BAT if exist "%ProgramData%\anaconda3\condabin\conda.bat" set "CONDA_BAT=%ProgramData%\anaconda3\condabin\conda.bat"
if not defined CONDA_BAT if exist "%ProgramData%\miniconda3\condabin\conda.bat" set "CONDA_BAT=%ProgramData%\miniconda3\condabin\conda.bat"

if not defined CONDA_BAT (
    echo [錯誤] 找不到 conda.bat。請確認 Conda 已安裝，或重新執行並輸入 0。
    pause
    exit /b 1
)

echo 正在啟用 Conda 環境：%CONDA_ENV%
call "!CONDA_BAT!" activate "%CONDA_ENV%"
if errorlevel 1 (
    echo [錯誤] 無法啟用 Conda 環境：%CONDA_ENV%
    pause
    exit /b 1
)

:RUN_PROGRAM
python --version >nul 2>&1
if errorlevel 1 (
    echo [錯誤] 目前環境找不到 Python。
    echo 請選擇可用的 Conda 環境，或先執行「點我初始化.bat」。
    pause
    exit /b 1
)

echo [OK] 專案目錄：%PROJECT_DIR%
echo 正在啟動 tickets_hunter...
python src\settings.py
set "PROGRAM_EXIT=%ERRORLEVEL%"

echo.
if not "%PROGRAM_EXIT%"=="0" (
    echo [錯誤] 程式結束，錯誤碼：%PROGRAM_EXIT%
) else (
    echo 程式已正常結束。
)
pause
endlocal & exit /b %PROGRAM_EXIT%
