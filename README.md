# Aru Archive

<p align="center">
  <img src="docs/icon.png" alt="Aru Archive 배너" width="160">
</p>

<p align="center">
  <strong>Pixiv 중심 이미지 아카이브를 위한 데스크톱 분류 도구</strong>
</p>

<p align="center">
  메타데이터 확인, 태그 보강, 분류 미리보기, 중복 검토, 안전한 결과 정리까지
  <br>
  하나의 작업 흐름으로 이어집니다.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 버전">
  <img src="https://img.shields.io/badge/UI-PyQt6-41CD52?logo=qt&logoColor=white" alt="PyQt6 UI">
  <img src="https://img.shields.io/badge/Focus-Pixiv%20Archive-CC4C7A" alt="Pixiv 아카이브 중심">
  <img src="https://img.shields.io/badge/Workflow-Inbox%20%E2%86%92%20Classified-7A3FF2" alt="분류 작업 흐름">
</p>

## 화면 미리보기

<p align="center">
  <img src="docs/icon_1.png" alt="Aru Archive 화면 미리보기" width="900">
</p>

## 소개

`Aru Archive`는 개인 이미지 아카이브를 정리할 때 반복적으로 생기는 번거로운 작업을 줄이기 위해 만든 데스크톱 앱입니다.  
원본을 `Inbox`에 모아 두고, 메타데이터 상태를 확인하고, 필요한 경우 Pixiv 계열 정보를 보강한 뒤, 태그 기반 규칙으로 분류 결과를 미리 확인하고 `Classified` 폴더로 정리할 수 있습니다.

단순한 파일 복사 도구가 아니라, 실제 아카이브 운영 흐름을 고려한 작업형 정리 도구에 가깝습니다. BMP/GIF처럼 바로 다루기 까다로운 포맷은 `Managed` 영역에서 관리본으로 다룰 수 있고, 분류 전후에는 중복 검토, XMP 재처리, DB 재색인 같은 보조 작업도 이어서 처리할 수 있습니다.

## 이런 흐름에 잘 맞습니다

- Pixiv 계열 이미지나 일러스트 자료를 폴더 단위로 꾸준히 정리하는 경우
- 파일명보다 메타데이터와 태그 기준으로 분류 규칙을 유지하고 싶은 경우
- 분류 실행 전에 결과 경로와 파일명을 먼저 확인하고 싶은 경우
- 중복 이미지를 수동 검토와 함께 관리하고 싶은 경우
- 장기적으로 태그 사전과 분류 기준을 누적하면서 아카이브를 운영하고 싶은 경우

## 핵심 기능

- `Inbox`, `Classified`, `Managed` 구조 기반 작업 폴더 운영
- 파일 메타데이터 읽기와 누락 상태 점검
- Pixiv 메타데이터 보강 및 태그 기반 재분류
- 분류 실행 전 미리보기 제공
- 시각적 중복 탐지와 검토 다이얼로그 지원
- XMP 재처리, 썸네일 재생성, DB 재색인 같은 유지보수 기능 제공

## 작업 구조

앱은 사용자 작업 폴더와 내부 데이터를 분리해서 사용합니다.

- `inbox_dir`: 사용자가 직접 선택한 분류 대상 폴더
- `classified_dir`: 분류 결과가 복사되는 폴더
- `managed_dir`: BMP/GIF 변환본 등 앱이 관리하는 보조 작업 폴더
- `data_dir`: DB, 로그, 썸네일, 런타임 파일을 저장하는 앱 내부 데이터 폴더

첫 실행 시에는 작업 폴더 설정 다이얼로그가 열립니다. 사용자가 선택한 폴더는 이름 변경 없이 그대로 `Inbox` 역할로 사용되고, 같은 위치에 `Classified`, `Managed` 폴더가 자동으로 준비됩니다. 앱 내부 데이터는 기본적으로 `C:\Users\<user>\AruArchive` 아래에 저장됩니다.

예시:

- 선택 폴더: `D:\PixivInbox`
- 분류 대상: `D:\PixivInbox`
- 분류 완료: `D:\Classified`
- 관리 폴더: `D:\Managed`

## 빠른 시작

```bash
pip install -r requirements.txt
python main.py
```

설정 파일을 직접 지정해서 실행하려면:

```bash
python main.py --config path/to/config.json
```

## 기본 사용 흐름

1. 앱을 실행합니다.
2. `작업 폴더 설정`에서 분류 대상 폴더를 선택합니다.
3. `Inbox 스캔`으로 작업 파일을 등록합니다.
4. 필요하면 메타데이터를 보강하고 태그를 정리합니다.
5. `분류 미리보기`로 실제 결과를 확인합니다.
6. `분류 실행`으로 `Classified`에 결과를 정리합니다.
7. 필요 시 중복 검토, XMP 재처리, DB 재색인을 이어서 수행합니다.

## 작업 마법사

상단의 `작업 마법사`는 전체 흐름을 단계별로 따라갈 수 있게 정리한 가이드입니다.

1. 작업 폴더 설정
2. Inbox 스캔
3. 메타데이터 상태 확인
4. 메타데이터 보강
5. 사전 / 태그 정리
6. 태그 재분류
7. 분류 미리보기
8. 분류 실행
9. 결과 확인 / Undo

자세한 단계 설명은 [docs/workflow-wizard.md](docs/workflow-wizard.md)에서 볼 수 있습니다.

## 현재 개발 상태

현재 `Aru Archive`는 핵심 작업 흐름을 실제로 다뤄볼 수 있는 단계에 와 있습니다.  
작업 폴더 설정, Inbox 스캔, 메타데이터 점검, 태그 재분류, 분류 미리보기, 분류 실행, 중복 검토 같은 주요 기능은 이미 연결되어 있고, 내부적으로는 경로 모델과 작업 마법사 흐름도 정리되어 있습니다.

다만 아직은 활발히 다듬는 중인 개발 버전에 가깝습니다. 일부 사전 데이터, 분류 기준, UI 문구, 예외 케이스 대응은 계속 보강 중이며, 실제 사용 중 발견되는 작업 흐름도 순차적으로 반영하고 있습니다.

## 로드맵

- 태그 팩과 외부 사전 데이터를 더 안정적으로 초기 데이터화
- 분류 누락 항목을 빠르게 찾을 수 있는 디버그/리포트 흐름 보강
- 첫 실행 경험과 설정 UI를 더 직관적으로 개선
- 분류 기준과 태그 사전 관리 기능 정리
- 설치형 배포와 사용자용 문서 흐름 정리

## 현재 알려진 제한 사항

- 분류 정확도는 현재 메타데이터 품질과 태그 사전 상태에 직접 영향을 받습니다.
- 일부 캐릭터/시리즈는 alias가 충분하지 않으면 `fallback` 분류가 발생할 수 있습니다.
- 외부 사전 import 후에는 기존 데이터에 바로 반영되지 않고 재분류가 필요할 수 있습니다.
- BMP/GIF처럼 별도 관리본이 필요한 포맷은 `Managed` 폴더 흐름을 이해하고 사용하는 것이 좋습니다.
- UI와 문서는 계속 정리 중이어서, 일부 표현이나 단계 이름은 이후 변경될 수 있습니다.

## 테스트

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q
```

## 문서

- [docs/workflow-wizard.md](docs/workflow-wizard.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/classification-policy.md](docs/classification-policy.md)
- [docs/metadata-policy.md](docs/metadata-policy.md)
- [docs/duplicate-management.md](docs/duplicate-management.md)
- [docs/file-deletion.md](docs/file-deletion.md)
- [docs/troubleshooting.md](docs/troubleshooting.md)
