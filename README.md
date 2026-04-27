# Aru Archive

개인 아트워크 아카이브 관리 도구입니다.  
Pixiv 등에서 수집한 파일을 메타데이터 기반으로 정리하고, 분류 미리보기와 분류 실행, Undo, 중복 점검까지 한 흐름으로 다룹니다.

## 빠른 시작

```bash
pip install -r requirements.txt
python main.py
```

설정 파일을 별도로 쓰려면:

```bash
python main.py --config path/to/config.json
```

## 첫 실행 안내

설치형 exe 또는 `python main.py`를 처음 실행하면 **작업 폴더 설정** 화면이 열립니다.

- 분류 대상 폴더를 하나 선택하면 그 폴더를 이름 변경 없이 그대로 사용합니다.
- 같은 위치에 `Classified`, `Managed` 폴더가 자동 생성됩니다.
- 앱 내부 데이터(DB, 로그, 썸네일, 런타임 파일)는 기본적으로 `C:\Users\<사용자명>\AruArchive` 아래에 저장됩니다.

예:

- 선택 폴더: `D:\PixivInbox`
- 분류 대상 폴더: `D:\PixivInbox`
- 분류 완료 폴더: `D:\Classified`
- 관리 폴더: `D:\Managed`

## 작업 폴더 모델

- `inbox_dir`: 사용자가 고른 분류 대상 폴더
- `classified_dir`: 분류 결과 복사본이 저장되는 폴더
- `managed_dir`: BMP/GIF 변환 등 앱이 관리하는 관리본 폴더
- `data_dir`: 앱 내부 데이터 저장 폴더

즉, `data_dir`는 더 이상 사용자 작업 루트가 아니고, 내부 저장소 역할만 맡습니다.

## 작업 마법사

툴바의 **[작업 마법사]** 버튼으로 9단계 가이드를 열 수 있습니다.

1. 작업 폴더 설정
2. Inbox 스캔
3. 메타데이터 상태 확인
4. 메타데이터 보강
5. 사전 / 태그 정리
6. 태그 재분류
7. 분류 미리보기
8. 분류 실행
9. 결과 / Undo

자세한 설명은 [docs/workflow-wizard.md](docs/workflow-wizard.md) 를 참고하세요.

## 기본 사용 흐름

1. 앱 실행
2. **[📁 작업 폴더 설정]** 으로 분류 대상 폴더 선택
3. **[🔍 Inbox 스캔]** 으로 파일 등록
4. 필요 시 Pixiv 메타데이터 보강
5. **[분류 미리보기]** 로 경로와 위험도 확인
6. **[분류 실행]** 으로 `Classified` 에 복사
7. **[작업 로그 / Undo]** 에서 결과 확인

## 테스트

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q
```

## 관련 문서

- [docs/workflow-wizard.md](docs/workflow-wizard.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/classification-policy.md](docs/classification-policy.md)
- [docs/metadata-policy.md](docs/metadata-policy.md)
- [docs/duplicate-management.md](docs/duplicate-management.md)
- [docs/file-deletion.md](docs/file-deletion.md)
- [docs/troubleshooting.md](docs/troubleshooting.md)
