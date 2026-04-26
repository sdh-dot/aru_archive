@echo off
:: Aru Archive Native Messaging Host 제거 스크립트

setlocal

set "HOST_MANIFEST_DIR=%APPDATA%\AruArchive\NativeHost"
set "REG_KEY=HKCU\Software\Google\Chrome\NativeMessagingHosts\net.aru_archive.host"
set "WHALE_REG_KEY=HKCU\Software\Naver\Whale\NativeMessagingHosts\net.aru_archive.host"

echo [1/3] Chrome 레지스트리 제거 중...
reg delete "%REG_KEY%" /f >nul 2>&1
echo    완료

echo [2/3] Whale 레지스트리 제거 중...
reg delete "%WHALE_REG_KEY%" /f >nul 2>&1
echo    완료

echo [3/3] 설치 파일 제거 중...
if exist "%HOST_MANIFEST_DIR%" (
    rmdir /s /q "%HOST_MANIFEST_DIR%"
    echo    %HOST_MANIFEST_DIR% 삭제됨
) else (
    echo    설치 디렉토리 없음, 건너뜀
)

echo.
echo 제거 완료. 브라우저를 재시작하세요.
endlocal
