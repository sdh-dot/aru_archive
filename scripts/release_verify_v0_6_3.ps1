param(
  [string]$Version = "0.6.3",
  [string]$ReleaseCheckDir = "E:\AruReleaseLatestCheck",
  [switch]$SkipPytest,
  [switch]$SkipBuild,
  [switch]$LaunchApp
)

$ErrorActionPreference = "Stop"

function Section($name) {
  Write-Host ""
  Write-Host "============================================================"
  Write-Host " $name"
  Write-Host "============================================================"
}

function Run($cmd) {
  Write-Host ""
  Write-Host "> $cmd"
  Invoke-Expression $cmd
}

Section "Aru Archive Release Verify v$Version"

$root = Resolve-Path "."
Write-Host "Project root: $root"

Section "Git status"

Run "git branch --show-current"
Run "git status --short"
Run "git log --oneline --decorate -12"

$status = git status --short
if ($status) {
  Write-Warning "Working tree가 clean 상태가 아닙니다."
  Write-Warning "릴리즈 빌드 전 의도된 변경인지 확인하십시오."
  Write-Host $status
  throw "Working tree is not clean."
}

Section "Pytest"

if (-not $SkipPytest) {
  Run "uv run pytest tests/test_metadata_enrichment_phase_split.py -q"
  Run "uv run pytest tests/test_metadata_batch_phase_split.py -q"
  Run "uv run pytest tests/test_metadata_write_status_logging.py -q"
  Run "uv run pytest tests/test_metadata_artwork_url.py -q"
  Run "uv run pytest tests/test_enrich_thread_emit_queue_summary.py -q"
  Run "uv run pytest tests/test_metadata_phase2_db_batching.py -q"
  Run "uv run pytest tests/test_classify_execute_idempotency.py -q"
  Run "uv run pytest tests/test_database_migrations.py -q"
}
else {
  Write-Warning "Pytest skipped."
}

Section "Stop running app"

Get-Process AruArchive -ErrorAction SilentlyContinue | Stop-Process -Force

Section "Clean previous build artifacts"

if (-not $SkipBuild) {
  Remove-Item -Recurse -Force ".\dist", ".\release" -ErrorAction SilentlyContinue
  Remove-Item -Recurse -Force ".\build\aru_archive" -ErrorAction SilentlyContinue
}
else {
  Write-Warning "Build cleanup skipped because -SkipBuild was set."
}

Section "Build release ZIP"

if (-not $SkipBuild) {
  Run ".\scripts\build_windows.ps1 -Version $Version -Clean"
}
else {
  Write-Warning "Build skipped."
}

Section "Verify release artifacts"

$zip = ".\release\AruArchive-v$Version-win-x64.zip"
$sha = ".\release\AruArchive-v$Version-win-x64.zip.sha256"

if (-not (Test-Path $zip)) {
  throw "ZIP not found: $zip"
}

if (-not (Test-Path $sha)) {
  throw "SHA256 file not found: $sha"
}

$actual = (Get-FileHash $zip -Algorithm SHA256).Hash
$expected = ((Get-Content $sha).Trim() -split "\s+")[0]

Write-Host "ZIP:      $zip"
Write-Host "SHA file: $sha"
Write-Host "Actual:   $actual"
Write-Host "Expected: $expected"
Write-Host "Match:    $($actual -eq $expected)"

if ($actual -ne $expected) {
  throw "SHA256 mismatch."
}

Section "Extract to fresh check directory"

Remove-Item -Recurse -Force $ReleaseCheckDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $ReleaseCheckDir | Out-Null

Expand-Archive `
  -LiteralPath $zip `
  -DestinationPath $ReleaseCheckDir `
  -Force

$appCandidates = Get-ChildItem -Path $ReleaseCheckDir -Recurse -File -ErrorAction SilentlyContinue |
Where-Object {
  $_.Name -in @("AruArchive.exe", "aru_archive.exe")
}

if (-not $appCandidates -or $appCandidates.Count -eq 0) {
  Write-Host "Extracted files:"
  Get-ChildItem -Path $ReleaseCheckDir -Recurse |
  Select-Object FullName |
  Format-Table -AutoSize

  throw "Aru Archive executable not found under: $ReleaseCheckDir"
}

if ($appCandidates.Count -gt 1) {
  Write-Warning "실행 파일 후보가 여러 개입니다. 첫 번째 항목을 사용합니다."
  $appCandidates | Select-Object FullName | Format-Table -AutoSize
}

$appPath = $appCandidates[0].FullName

Write-Host "Extracted app: $appPath"

Section "Release metadata"

$commit = git rev-parse --short HEAD
$fullCommit = git rev-parse HEAD
$tagCommit = $null

try {
  $tagCommit = git rev-parse "v$Version^{}"
}
catch {
  $tagCommit = "(tag not found)"
}

Write-Host "HEAD short:  $commit"
Write-Host "HEAD full:   $fullCommit"
Write-Host "Tag commit:  $tagCommit"
Write-Host "ZIP SHA256:  $actual"

Section "Manual smoke-test checklist"

Write-Host @"

수동 확인 항목:

[앱 기본]
- 앱 실행 정상
- 아이콘 / 작업 표시줄 아이콘 정상
- 첫 실행 3폴더 설정 화면 정상

[Step 4 메타데이터 가져오기]
- Phase 1 Pixiv 조회 완료
- Phase 2 UserComment/XMP/XP 기록 완료
- _emit_queue_summary 오류 없음
- artwork_groups recovery 로그 정상
- [ERROR] 없음

[성능 계측]
- ARU_ENRICH_TIMING=1 상태에서 Metadata batch performance report 출력
- db_commit_count가 PR2 이전보다 감소하는지 확인
  기대: 기존 1538 → 약 820~830 근처
- file_write_count / exiftool_spawn_count / ui_progress_emit_count는 큰 변화 없어도 정상

[분류]
- Step 6 분류 미리보기 정상
- Step 7 분류 실행 정상
- 1회차 복사 N / 스킵 0
- 2회차 복사 0 / 스킵 N
- 기존 output orphan이 없을 때 _1 suffix 중복 생성 없음

[Source Captioner]
- Chrome/Whale filename fallback 정상
- Firefox 전용 manifest 정상
- 일반 파일 출처 미삽입

"@

Section "Launch app"

if ($LaunchApp) {
  $env:ARU_ENRICH_TIMING = "1"
  Write-Host "Launching with ARU_ENRICH_TIMING=1"
  & $appPath
}
else {
  Write-Host "앱 실행은 생략했습니다."
  Write-Host "실행하려면:"
  Write-Host "`$env:ARU_ENRICH_TIMING = `"1`""
  Write-Host "& `"$appPath`""
  Write-Host ""
  Write-Host "또는 스크립트를 -LaunchApp 옵션으로 다시 실행하십시오."
}

Section "Done"

Write-Host "Release verify script completed successfully."