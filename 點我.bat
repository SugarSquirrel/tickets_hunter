@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

set "PYTHON_URL=https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe"
set "PYTHON_INSTALLER=python-3.10.11-amd64.exe"
set "ZIP_URL=https://github.com/SugarSquirrel/tickets_hunter/archive/refs/heads/0807-version-plus.zip"
set "ZIP_NAME=tickets_hunter_0807-version-plus.zip"
set "EXTRACT_DIR=%USERPROFILE%\0807-version-plus"
set "TARGET_SUBDIR=tickets_hunter-0807-version-plus"
set "PYTHON_DIR=%LOCALAPPDATA%\Programs\Python\Python310"
set "PYTHON_SCRIPTS=%LOCALAPPDATA%\Programs\Python\Python310\Scripts"
set "NEED_SETUP=0"
set "PYTHON_CMD=python"

echo ============================================================
echo  tickets_hunter 安裝與啟動程式 - Windows
echo ============================================================
echo.
set /p "CONDA_ENV=請輸入要使用的 Conda 環境名稱；若沒有 Conda 環境請輸入 0："

if not defined CONDA_ENV (
    echo [錯誤] 未輸入任何內容。
    pause
    exit /b 1
)

if "%CONDA_ENV%"=="0" (
    set "NEED_SETUP=1"
    goto SETUP_PYTHON
)

:: --- 使用現有 Conda 環境，略過步驟 1、2、5 ---
echo.
echo [1/5] 已指定 Conda 環境，略過 Python 安裝。
echo [2/5] 已指定 Conda 環境，略過 PATH 設定。

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
    echo 請確認環境名稱正確，或重新執行並輸入 0。
    pause
    exit /b 1
)

for /f "tokens=2" %%V in ('python --version 2^>^&1') do set "ACTIVE_PYTHON_VERSION=%%V"
if not defined ACTIVE_PYTHON_VERSION (
    echo [錯誤] Conda 環境已啟用，但找不到 Python。
    pause
    exit /b 1
)

echo !ACTIVE_PYTHON_VERSION! | findstr /b "3.10." >nul
if errorlevel 1 (
    echo [錯誤] Conda 環境中的 Python 版本不相容：!ACTIVE_PYTHON_VERSION!
    echo 本專案需要 Python 3.10.x。
    pause
    exit /b 1
)

echo [OK] Conda 環境已啟用：%CONDA_ENV%（Python !ACTIVE_PYTHON_VERSION!）
goto DOWNLOAD_ZIP

:SETUP_PYTHON
:: --- Step 1: 沒有 Conda 環境時檢查或安裝 Python 3.10 ---
echo.
echo [1/5] 檢查 Python 3.10...

py -3.10 --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py -3.10"
    echo [OK] 已透過 py launcher 找到 Python 3.10。
    goto ADD_PATH
)

where python >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=2" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
    echo !PYTHON_VERSION! | findstr /b "3.10." >nul
    if not errorlevel 1 (
        set "PYTHON_CMD=python"
        echo [OK] 已找到 Python !PYTHON_VERSION!。
        goto ADD_PATH
    )
)

:ASK_INSTALL_PYTHON
set "INSTALL_PYTHON="
echo 找不到相容的 Python 3.10。
set /p "INSTALL_PYTHON=是否要安裝 Python 3.10.11？請輸入「是」或「否」："

if "!INSTALL_PYTHON!"=="是" goto INSTALL_PYTHON
if "!INSTALL_PYTHON!"=="否" (
    echo 已取消 Python 安裝，程式即將結束。
    pause
    exit /b 0
)

echo [錯誤] 請輸入「是」或「否」。
goto ASK_INSTALL_PYTHON

:INSTALL_PYTHON
echo 正在下載 Python 安裝程式...
curl -L --fail "%PYTHON_URL%" -o "%TEMP%\%PYTHON_INSTALLER%"
if errorlevel 1 (
    echo [錯誤] Python 安裝程式下載失敗。
    pause
    exit /b 1
)

echo 正在安裝 Python 3.10.11...
"%TEMP%\%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=1
if errorlevel 1 (
    echo [錯誤] Python 安裝失敗。
    pause
    exit /b 1
)

if exist "%PYTHON_DIR%\python.exe" (
    set "PYTHON_CMD=python"
) else (
    py -3.10 --version >nul 2>&1
    if errorlevel 1 (
        echo [錯誤] Python 安裝完成，但找不到 Python 3.10 執行檔。
        pause
        exit /b 1
    )
    set "PYTHON_CMD=py -3.10"
)
echo [OK] Python 3.10.11 已安裝。

:ADD_PATH
:: --- Step 2: 沒有 Conda 環境時加入 Python PATH ---
echo [2/5] 設定 Python PATH...
set "PATH=%PYTHON_DIR%;%PYTHON_SCRIPTS%;%PATH%"

reg query "HKCU\Environment" /v PATH >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v PATH 2^>nul ^| findstr /i " PATH"') do set "CURRENT_PATH=%%B"
) else (
    set "CURRENT_PATH="
)

echo(!CURRENT_PATH!| findstr /i /c:"%PYTHON_DIR%" >nul
if errorlevel 1 (
    if defined CURRENT_PATH (
        setx PATH "%PYTHON_DIR%;%PYTHON_SCRIPTS%;!CURRENT_PATH!" >nul
    ) else (
        setx PATH "%PYTHON_DIR%;%PYTHON_SCRIPTS%" >nul
    )
    if errorlevel 1 (
        echo [錯誤] 無法寫入使用者 PATH。
        pause
        exit /b 1
    )
    echo [OK] Python 已永久加入使用者 PATH。
) else (
    echo [OK] Python 已存在於使用者 PATH，略過寫入。
)

:DOWNLOAD_ZIP
:: --- Step 3: 下載指定分支 ---
echo [3/5] 正在下載 tickets_hunter 的 0807-version-plus 分支...
if not exist "%EXTRACT_DIR%" mkdir "%EXTRACT_DIR%"
if errorlevel 1 (
    echo [錯誤] 無法建立目錄：%EXTRACT_DIR%
    pause
    exit /b 1
)

curl -L --fail "%ZIP_URL%" -o "%EXTRACT_DIR%\%ZIP_NAME%"
if errorlevel 1 (
    echo [錯誤] 專案 ZIP 下載失敗。
    pause
    exit /b 1
)
echo [OK] 專案下載完成。

:: --- Step 4: 解壓縮 ---
echo [4/5] 正在解壓縮...
powershell -NoProfile -Command "Expand-Archive -LiteralPath '%EXTRACT_DIR%\%ZIP_NAME%' -DestinationPath '%EXTRACT_DIR%' -Force"
if errorlevel 1 (
    echo [錯誤] 解壓縮失敗。
    pause
    exit /b 1
)
echo [OK] 解壓縮完成。

set "TARGET_PATH=%EXTRACT_DIR%\%TARGET_SUBDIR%"
if not exist "%TARGET_PATH%\src\settings.py" (
    echo [錯誤] 找不到啟動程式：%TARGET_PATH%\src\settings.py
    pause
    exit /b 1
)
cd /d "%TARGET_PATH%"
echo [OK] 目前工作目錄：%TARGET_PATH%

:: --- Step 5: 只有輸入 0 時才安裝 requirements ---
if "%NEED_SETUP%"=="0" (
    echo [5/5] 使用現有 Conda 環境，略過 requirements 安裝。
    goto RUN_PROGRAM
)

echo [5/5] 正在安裝 requirements...
if not exist "requirement.txt" (
    echo [錯誤] 找不到 requirement.txt。
    pause
    exit /b 1
)

%PYTHON_CMD% -m pip install -r requirement.txt
if errorlevel 1 (
    echo [錯誤] requirements 安裝失敗。
    pause
    exit /b 1
)
echo [OK] Requirements 安裝完成。

:RUN_PROGRAM
echo.
echo ============================================================
echo  正在啟動 tickets_hunter
echo  工作目錄：%TARGET_PATH%
echo ============================================================
%PYTHON_CMD% src\settings.py
set "PROGRAM_EXIT=%ERRORLEVEL%"

echo.
if not "%PROGRAM_EXIT%"=="0" (
    echo [錯誤] 程式結束，錯誤碼：%PROGRAM_EXIT%
) else (
    echo 程式已正常結束。
)
pause
endlocal & exit /b %PROGRAM_EXIT%
