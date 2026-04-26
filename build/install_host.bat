@echo off
:: Aru Archive Native Messaging Host 설치 스크립트 (Windows)
:: 관리자 권한 없이 HKCU에 등록 (사용자별 설치)
::
:: 사용법:
::   install_host.bat                         -- 기존 방식 (PLACEHOLDER 포함, Chrome+Whale 모두 등록)
::   install_host.bat chrome <extension_id>   -- Chrome 전용 (실제 ID로 manifest 생성)
::   install_host.bat whale  <extension_id>   -- Whale 전용  (실제 ID로 manifest 생성)
::   install_host.bat both   <extension_id>   -- Chrome + Whale 모두 (실제 ID로 manifest 생성)
::
:: 확장 프로그램 ID 확인 방법:
::   Chrome: chrome://extensions → 개발자 모드 ON → 확장 ID 복사
::   Whale:  whale://extensions  → 개발자 모드 ON → 확장 ID 복사

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "HOST_DIR=%APPDATA%\AruArchive\NativeHost"
set "CHROME_KEY=HKCU\Software\Google\Chrome\NativeMessagingHosts\net.aru_archive.host"
set "WHALE_KEY=HKCU\Software\Naver\Whale\NativeMessagingHosts\net.aru_archive.host"
set "LOG=%HOST_DIR%\install.log"

set "BROWSER=%~1"
set "EXT_ID=%~2"

:: ── Python 확인 ──────────────────────────────────────────────
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python을 찾을 수 없습니다. PATH에 Python이 있는지 확인하세요.
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"

echo === Aru Archive Native Host 설치 ===
echo 프로젝트 경로: %PROJECT_DIR%
echo 설치 경로:     %HOST_DIR%
echo Python:        %PY_VER%
if defined BROWSER echo 브라우저:       %BROWSER%
if defined EXT_ID  echo 확장 ID:        %EXT_ID%
echo.

:: 설치 디렉터리 생성
mkdir "%HOST_DIR%" 2>nul

:: 로그 초기화
echo [%date% %time%] 설치 시작 > "%LOG%"
echo Python: %PY_VER% >> "%LOG%"
if defined BROWSER echo Browser: %BROWSER% >> "%LOG%"
if defined EXT_ID  echo ExtID:   %EXT_ID%  >> "%LOG%"

:: ── 1. host.bat 생성 ──────────────────────────────────────────
echo [1/4] host.bat 생성 중...
(
    echo @echo off
    echo cd /d "%PROJECT_DIR%"
    echo python -m native_host.host
) > "%HOST_DIR%\host.bat"
echo [OK] host.bat 생성 완료 >> "%LOG%"

:: ── 2. manifest 생성 ──────────────────────────────────────────
echo [2/4] Native Messaging manifest 생성 중...
set "HOST_BAT=%HOST_DIR%\host.bat"

if not defined EXT_ID (
    :: 확장 ID 미지정 → 템플릿에서 path만 교체, allowed_origins는 PLACEHOLDER 유지
    echo    [WARN] 확장 ID를 지정하지 않았습니다. manifest의 allowed_origins에 PLACEHOLDER가 남습니다.
    echo    브라우저 확장 설치 후 다음 명령으로 재실행하세요:
    echo      install_host.bat chrome ^<extension_id^>
    echo      install_host.bat whale  ^<extension_id^>
    echo.
    set "HOST_BAT_ESC=%HOST_BAT:\=\\%"
    copy /y "%PROJECT_DIR%\native_host\manifest_chrome.json" "%HOST_DIR%\manifest_chrome.json" >nul
    copy /y "%PROJECT_DIR%\native_host\manifest_whale.json"  "%HOST_DIR%\manifest_whale.json"  >nul
    powershell -Command "(Get-Content '%HOST_DIR%\manifest_chrome.json') -replace 'host\\.bat', '!HOST_BAT_ESC!' | Set-Content '%HOST_DIR%\manifest_chrome.json'"
    powershell -Command "(Get-Content '%HOST_DIR%\manifest_whale.json')  -replace 'host\\.bat', '!HOST_BAT_ESC!' | Set-Content '%HOST_DIR%\manifest_whale.json'"
    echo [WARN] manifest PLACEHOLDER (no ext_id) >> "%LOG%"
    goto register_both
)

:: 확장 ID 지정 → gen_manifest.py로 실제 manifest 생성
if "%BROWSER%"=="chrome" (
    python "%SCRIPT_DIR%gen_manifest.py" "%HOST_BAT%" chrome "%EXT_ID%" "%HOST_DIR%\manifest_chrome.json"
    if !errorlevel! neq 0 ( echo [ERROR] Chrome manifest 생성 실패. & exit /b 1 )
    echo [OK] Chrome manifest 생성 완료 >> "%LOG%"
    goto register_chrome
)
if "%BROWSER%"=="whale" (
    python "%SCRIPT_DIR%gen_manifest.py" "%HOST_BAT%" whale "%EXT_ID%" "%HOST_DIR%\manifest_whale.json"
    if !errorlevel! neq 0 ( echo [ERROR] Whale manifest 생성 실패. & exit /b 1 )
    echo [OK] Whale manifest 생성 완료 >> "%LOG%"
    goto register_whale
)
if "%BROWSER%"=="both" (
    python "%SCRIPT_DIR%gen_manifest.py" "%HOST_BAT%" chrome "%EXT_ID%" "%HOST_DIR%\manifest_chrome.json"
    if !errorlevel! neq 0 ( echo [ERROR] Chrome manifest 생성 실패. & exit /b 1 )
    python "%SCRIPT_DIR%gen_manifest.py" "%HOST_BAT%" whale  "%EXT_ID%" "%HOST_DIR%\manifest_whale.json"
    if !errorlevel! neq 0 ( echo [ERROR] Whale manifest 생성 실패. & exit /b 1 )
    echo [OK] Chrome+Whale manifest 생성 완료 >> "%LOG%"
    goto register_both
)
echo [ERROR] 브라우저는 chrome, whale, both 중 하나여야 합니다.
exit /b 1

:: ── 3. 레지스트리 등록 ───────────────────────────────────────

:register_chrome
echo [3/4] Chrome 레지스트리 등록 중...
reg add "%CHROME_KEY%" /ve /t REG_SZ /d "%HOST_DIR%\manifest_chrome.json" /f >nul 2>&1
if %errorlevel% neq 0 (
    echo    [SKIP] Chrome이 설치되어 있지 않거나 등록 실패
    echo [SKIP] Chrome 등록 실패 >> "%LOG%"
) else (
    echo    Chrome 등록 완료
    echo [OK] Chrome 등록 완료 >> "%LOG%"
)
echo [4/4] Whale 등록 건너뜀 (chrome 전용 설치)
goto done

:register_whale
echo [3/4] Chrome 등록 건너뜀 (whale 전용 설치)
echo [4/4] Whale 레지스트리 등록 중...
reg add "%WHALE_KEY%" /ve /t REG_SZ /d "%HOST_DIR%\manifest_whale.json" /f >nul 2>&1
if %errorlevel% neq 0 (
    echo    [SKIP] Whale이 설치되어 있지 않거나 등록 실패
    echo [SKIP] Whale 등록 실패 >> "%LOG%"
) else (
    echo    Whale 등록 완료
    echo [OK] Whale 등록 완료 >> "%LOG%"
)
goto done

:register_both
echo [3/4] Chrome 레지스트리 등록 중...
reg add "%CHROME_KEY%" /ve /t REG_SZ /d "%HOST_DIR%\manifest_chrome.json" /f >nul 2>&1
if %errorlevel% neq 0 (
    echo    [SKIP] Chrome이 설치되어 있지 않거나 등록 실패
    echo [SKIP] Chrome 등록 실패 >> "%LOG%"
) else (
    echo    Chrome 등록 완료
    echo [OK] Chrome 등록 완료 >> "%LOG%"
)
echo [4/4] Whale 레지스트리 등록 중...
reg add "%WHALE_KEY%" /ve /t REG_SZ /d "%HOST_DIR%\manifest_whale.json" /f >nul 2>&1
if %errorlevel% neq 0 (
    echo    [SKIP] Whale이 설치되어 있지 않거나 등록 실패
    echo [SKIP] Whale 등록 실패 >> "%LOG%"
) else (
    echo    Whale 등록 완료
    echo [OK] Whale 등록 완료 >> "%LOG%"
)

:done
echo.
echo 설치 완료: %HOST_DIR%
echo 로그: %LOG%
echo 브라우저를 재시작하면 확장 프로그램이 Native Host를 사용할 수 있습니다.
echo [%date% %time%] 설치 완료 >> "%LOG%"
endlocal
