# GPT Pro 첫 응답 A-F — shorts_pipeline_v2_1 기준

기준 파일: `shorts_pipeline_v2_1_verified_spec.md`  
역할 분리: GPT Pro = 설계/리뷰/다음 프롬프트 생성, Codex = repo 구현/테스트/결과 보고

---

## A. 검증 메모

### A-1. 구현 전 확정된 원칙

1. **A 후보 보드는 세션 임시 데이터다.**
   - `EphemeralCandidate.status`는 `new`, `selected`, `rejected_in_session`까지만 사용한다.
   - DB에는 선택되어 실제 제작을 시작한 프로젝트만 저장한다.
   - `saved`, `rejected`, `used`를 DB 상태처럼 구현하지 않는다.

2. **커뮤니티 자동 크롤링은 v2.1 기본 범위가 아니다.**
   - `collectors.dcinside.enabled = false`
   - `mode = manual_url_only`
   - Playwright, RSS, search adapter는 나중에 붙일 수 있으나 첫 라운드에서는 구현하지 않는다.
   - 로그인 우회, CAPTCHA 우회, IP 회전, 헤더 위장, rate-limit 우회는 금지한다.

3. **C는 렌더러가 아니라 프로젝트 컴파일러다.**
   - 산출물은 `timeline.json`, placeholder/user image slot, text overlay PNG, `project.kdenlive`다.
   - 최종 mp4 렌더링, 자동 업로드, 자동 이미지 삽입, 자동 TTS는 v2.1 범위 밖이다.

4. **Kdenlive는 self-generated project only 정책으로 간다.**
   - 외부에서 받은 `.kdenlive` 파일을 파싱하거나 신뢰하지 않는다.
   - 자체 템플릿과 자체 산출물만 대상으로 XML mutation을 수행한다.
   - 절대경로, `../`, 외부 URL resource, XML escape 누락은 테스트에서 차단한다.

5. **MVP 화면 문구는 Kdenlive title clip이 아니라 PNG overlay로 생성한다.**
   - title clip XML 자동 생성은 v2.2 이후로 미룬다.
   - 첫 라운드에서는 PNG overlay 생성 함수의 인터페이스와 테스트 골격까지만 준비한다.

6. **D 단계의 `d_image_manifest.json`은 E 실행의 필수 입력이다.**
   - 실제 이미지가 placeholder인지 교체됐는지, 권리 확인이 되었는지, 개인정보/얼굴/원본캡처 포함 여부를 기록한다.
   - E는 `timeline.json + d_image_manifest.json + source_reference`만 보고 대본과 제목을 생성한다.

7. **LLM 출력은 앱 레벨 Pydantic 검증을 통과해야만 저장한다.**
   - OpenAI/Claude/Gemini SDK 연동은 첫 라운드에서 하지 않는다.
   - 첫 라운드는 provider 인터페이스, 모델, validator skeleton, fixture 기반 테스트만 만든다.

8. **날짜/시간은 하드코딩하지 않는다.**
   - 프로젝트 ID와 생성 시각은 `now_kst_iso()` 또는 주입 가능한 clock 함수에서 만든다.
   - 예시 날짜 `2026-05-29` 같은 고정값을 코드에 넣지 않는다.

### A-2. 확인 필요 항목

1. **Kdenlive 템플릿 실제 파일은 로컬에서 별도 생성 필요.**
   - Codex가 임의로 완전한 production-ready `.kdenlive` 템플릿을 생성했다고 가정하지 않는다.
   - 첫 라운드에서는 `templates/TEMPLATE_METADATA.json`과 placeholder template stub만 둔다.
   - 실제 Kdenlive open smoke test는 Kdenlive 설치 후 별도 라운드에서 수행한다.

2. **정확한 dependency lock은 개발 환경에서 확정 필요.**
   - `requirements.txt` 또는 `pyproject.toml`에는 합리적 최소 범위를 둔다.
   - 이후 `uv lock` 또는 `pip-compile`로 고정한다.

3. **OpenAI/Claude/Gemini 실제 구조화 출력 API 호출부는 최신 SDK 기준 재확인 필요.**
   - 첫 라운드는 API key, provider-specific 호출, 네트워크 호출을 만들지 않는다.
   - `.env.example`만 제공한다.

4. **콘텐츠 안전 validator는 1차 휴리스틱으로 시작한다.**
   - 실명/닉네임/개인정보/범죄 단정/허위 수치 감지는 완전 자동 판별이 어렵다.
   - 첫 라운드는 명시적 금지어/패턴/테스트 케이스 중심으로 골격화한다.

---

## B. 생성할 파일 목록

| path | purpose | codex_action |
|---|---|---|
| `README.md` | 프로젝트 목적, 로컬 MVP 범위, 금지 범위 요약 | 아래 C의 완성 내용 그대로 생성 |
| `AGENTS.md` | Codex가 매 세션 읽어야 할 repo 운영 규칙 | 아래 C의 완성 내용 그대로 생성 |
| `docs/00_PROJECT_BRIEF.md` | 제품 정의, 성공 기준, 비범위 | 아래 C의 완성 내용 그대로 생성 |
| `docs/01_ARCHITECTURE.md` | 모듈 A~E 구조와 데이터 흐름 | 아래 C의 완성 내용 그대로 생성 |
| `docs/02_DATA_CONTRACTS.md` | Pydantic 모델/JSON artifact 계약 요약 | 아래 C의 완성 내용 그대로 생성 |
| `docs/03_SECURITY_POLICY.md` | 파일/LLM/콘텐츠/수집 안전 정책 | 아래 C의 완성 내용 그대로 생성 |
| `docs/04_CODEX_WORKFLOW.md` | GPT Pro ↔ Codex 반복 운영법 | 아래 C의 완성 내용 그대로 생성 |
| `docs/05_PHASE_PLAN.md` | phase별 구현 순서와 완료 기준 | 아래 C의 완성 내용 그대로 생성 |
| `docs/06_TEST_PLAN.md` | unit/integration/manual/red-team 테스트 계획 | 아래 C의 완성 내용 그대로 생성 |
| `.gitignore` | Python, env, generated project artifact 제외 | 아래 C의 완성 내용 그대로 생성 |
| `.env.example` | API key/env 변수 예시. 실제 key 금지 | 아래 C의 완성 내용 그대로 생성 |
| `pyproject.toml` | Python package/test 설정 | Codex가 생성. 아래 C의 정책 반영 |
| `src/shorts_pipeline/__init__.py` | package marker | Codex가 생성 |
| `src/shorts_pipeline/config.py` | settings, paths, KST time helper | Codex가 생성 |
| `src/shorts_pipeline/models.py` | Candidate/B/Timeline/D/E Pydantic models | Codex가 v2.1 명세 기준 생성 |
| `src/shorts_pipeline/state_machine.py` | Project status transitions | Codex가 생성 |
| `src/shorts_pipeline/db.py` | SQLite schema init, foreign keys, WAL | Codex가 생성 |
| `src/shorts_pipeline/security.py` | safe path/resource/XML helper skeleton | Codex가 생성 |
| `src/shorts_pipeline/projectgen/timeline.py` | start_sec assignment skeleton | Codex가 생성 |
| `src/shorts_pipeline/projectgen/placeholder.py` | placeholder PNG interface skeleton | Codex가 생성 |
| `src/shorts_pipeline/projectgen/text_overlay.py` | text overlay PNG interface skeleton | Codex가 생성 |
| `src/shorts_pipeline/llm/validators.py` | B/E validation helper skeleton | Codex가 생성 |
| `schemas/README.md` | JSON schema generation policy | Codex가 생성 |
| `templates/TEMPLATE_METADATA.json` | Kdenlive template metadata placeholder | Codex가 생성 with warning |
| `templates/kdenlive_vertical_1080x1920_30fps.kdenlive` | dev-only stub or placeholder template | Codex가 생성하되 production-ready로 주장 금지 |
| `tests/fixtures/sample_source.json` | minimal selected source fixture | Codex가 생성 |
| `tests/fixtures/sample_b_scene_plan.json` | valid B fixture | Codex가 생성 |
| `tests/test_models.py` | Pydantic validation tests | Codex가 생성 |
| `tests/test_state_machine.py` | status transition tests | Codex가 생성 |
| `tests/test_timeline.py` | start time/duration tests | Codex가 생성 |
| `tests/test_security.py` | path traversal/external URL/XML escape tests | Codex가 생성 |
| `tests/test_db.py` | SQLite schema init smoke tests | Codex가 생성 |

---

## C. 파일별 완성 내용

[FILE: README.md]
# Shorts Pipeline v2.1

로컬에서 운영하는 반자동 쇼츠 제작 파이프라인 MVP입니다.

사용자가 커뮤니티 소재 URL과 직접 작성한 요약을 입력하면, LLM이 쇼츠 구성안을 만들고, Python 프로젝트 컴파일러가 `timeline.json`, 이미지 슬롯, 텍스트 오버레이 PNG, Kdenlive 프로젝트 파일을 생성합니다. 사용자는 Kdenlive에서 이미지를 직접 교체/삽입하고, 이후 LLM이 녹음용 내레이션 대본과 제목 후보를 생성합니다.

## v2.1 핵심 범위

- Streamlit 기반 로컬 UI
- SQLite 기반 프로젝트 저장
- 수동 URL 입력 기반 후보 카드
- B: 구조화된 쇼츠 구성안 생성
- C: canonical `timeline.json` 생성
- C: placeholder/user image slot 생성
- C: text overlay PNG 생성
- C: Kdenlive template-based `.kdenlive` 생성
- D: 사용자가 직접 이미지 교체 후 `d_image_manifest.json` 작성
- E: 녹음용 내레이션 대본과 제목 후보 생성

## v2.1 비범위

- 커뮤니티 자동 크롤링 기본 활성화
- 로그인/차단/CAPTCHA/rate-limit 우회
- 원문/댓글 전체 저장
- 자동 이미지 삽입
- 자동 TTS
- 자동 업로드
- 외부 `.kdenlive` 파일 신뢰 또는 파싱
- 최종 mp4 렌더링 자동화

## 첫 구현 범위

현재 첫 라운드의 목표는 다음으로 제한합니다.

1. repo scaffold
2. 문서 정리
3. SQLite schema
4. Pydantic data models
5. state machine
6. security helper skeleton
7. pytest skeleton

실제 LLM API 호출, Kdenlive 완성 XML mutation, Streamlit 전체 UI는 후속 라운드에서 구현합니다.

## 안전 원칙

- API key는 `.env`에만 둡니다.
- DB/log에 API key, 원문 전체, 댓글 전체, 개인정보를 저장하지 않습니다.
- 커뮤니티 자동 수집은 기본 비활성화합니다.
- 프로젝트 파일 경로는 `/projects` 하위로 제한합니다.
- 절대경로, `../`, 외부 URL resource를 거부합니다.
- Kdenlive 프로젝트 파일은 자체 생성한 것만 사용합니다.
[/FILE]

[FILE: AGENTS.md]
# Codex Operating Rules

이 repo에서 Codex는 구현 담당자입니다. GPT Pro는 설계, 리뷰, 다음 프롬프트 생성 담당자입니다.

## 기준 문서

Codex는 작업 전 반드시 다음 문서를 읽고 기준으로 삼습니다.

1. `README.md`
2. `docs/00_PROJECT_BRIEF.md`
3. `docs/01_ARCHITECTURE.md`
4. `docs/02_DATA_CONTRACTS.md`
5. `docs/03_SECURITY_POLICY.md`
6. `docs/05_PHASE_PLAN.md`
7. `docs/06_TEST_PLAN.md`

## 절대 금지

- 자동 커뮤니티 크롤러를 기본 활성화하지 않는다.
- 디시/커뮤니티 글 원문 전체 또는 댓글 전체를 저장하지 않는다.
- API key나 secret을 파일, DB, 로그에 저장하지 않는다.
- 외부 `.kdenlive` 파일을 신뢰하거나 파싱하지 않는다.
- 절대경로, `../`, 외부 URL resource를 프로젝트 산출물에 넣지 않는다.
- 자동 TTS, 자동 업로드, 자동 이미지 삽입을 구현하지 않는다.
- CAPTCHA 우회, 로그인 우회, IP 회전, 헤더 위장, rate-limit 우회를 구현하지 않는다.

## 구현 원칙

- 작은 단위로 구현한다.
- 테스트를 먼저 또는 함께 작성한다.
- 네트워크 호출이 필요한 기능은 첫 라운드에서 mock/skeleton으로 둔다.
- 모든 JSON artifact는 Pydantic model 또는 schema validation을 통과해야 한다.
- 날짜/시간은 런타임 helper를 사용하고 하드코딩하지 않는다.
- 모호한 결정은 `docs/04_CODEX_WORKFLOW.md`의 Result Report에 assumptions로 남긴다.

## 라운드 종료 보고

작업이 끝나면 반드시 다음을 보고한다.

- 생성/수정 파일
- 실행한 명령
- 테스트 결과
- 결정사항
- 가정
- known issue/blocker
- security/policy checklist
- 다음 추천 작업
[/FILE]

[FILE: docs/00_PROJECT_BRIEF.md]
# 00. Project Brief

## 제품 정의

Shorts Pipeline v2.1은 로컬에서 실행되는 반자동 쇼츠 제작 MVP입니다.

사용자는 커뮤니티 소재의 URL, 제목, 짧은 요약, 후킹 포인트, 쇼츠화 이유를 직접 입력합니다. 앱은 선택된 소재만 프로젝트로 저장하고, LLM은 이를 바탕으로 원문 직접 인용 없이 쇼츠 구성안을 생성합니다. 이후 Python 프로젝트 컴파일러가 편집 가능한 Kdenlive 프로젝트와 canonical `timeline.json`을 생성합니다.

## 핵심 사용자 흐름

1. A: 사용자가 수동으로 후보 카드 생성
2. A: 사용자가 특정 후보를 선택해 제작 시작
3. B: LLM이 구조화된 `b_scene_plan.json` 생성
4. C: 앱이 `timeline.json`, 이미지 슬롯, 텍스트 오버레이 PNG, `project.kdenlive` 생성
5. D: 사용자가 Kdenlive 또는 파일 교체 방식으로 이미지 직접 삽입
6. D: 사용자가 `d_image_manifest.json`으로 이미지 권리/내용 확인
7. E: LLM이 녹음용 내레이션과 제목 후보 생성
8. 사용자가 직접 녹음하고 최종 편집

## MVP 성공 기준

1. 수동 입력 후보 1개로 프로젝트 폴더와 DB row가 생성된다.
2. B 출력이 Pydantic validation과 콘텐츠 안전 규칙을 통과한다.
3. C가 만든 `timeline.json`이 schema validation을 통과한다.
4. 모든 이미지 슬롯과 텍스트 오버레이 파일이 존재한다.
5. 생성된 `.kdenlive` 파일은 XML parse와 path validation을 통과한다.
6. D 이후 `d_image_manifest.json`이 validation을 통과한다.
7. E 출력은 모든 scene에 대본을 제공하고, 추천 제목은 후보 목록 중 하나다.

## 명시적 비범위

- 커뮤니티 자동 크롤링 기본 활성화
- 원문/댓글 전체 저장
- 자동 TTS
- 자동 업로드
- 자동 이미지 삽입
- 외부 `.kdenlive` 파일 처리
- Kdenlive title clip 직접 생성
- 상업 운영용 약관/법률 검토 자동화

## 첫 라운드 목표

첫 Codex 라운드는 구현 범위를 작게 유지합니다.

- repo scaffold
- docs
- SQLite schema
- Pydantic models
- state machine
- safe path/XML helper skeleton
- tests skeleton

Streamlit 전체 UI, 실제 LLM API, 실제 Kdenlive XML mutation은 다음 라운드로 미룹니다.
[/FILE]

[FILE: docs/01_ARCHITECTURE.md]
# 01. Architecture

## 전체 구조

```text
[Streamlit UI]
  ├─ A. Manual candidate board
  ├─ B. Scene plan generator
  ├─ C. Project compiler
  ├─ D. Human image insertion
  ├─ E. Narration/title generator
  └─ SQLite + local project folder
```

## A. 후보 입력/보드

v2.1의 기본값은 `manual_url_only`입니다.

사용자가 직접 입력합니다.

- source_url
- community
- source_title
- summary
- hook
- why_shortable
- risk_flags_for_user

후보 카드는 session memory에만 존재합니다. 사용자가 “제작 시작”을 누르면 최소 메타데이터만 DB와 `source.json`에 저장합니다.

## B. 구성안 생성

입력:

- 선택된 소재의 최소 메타데이터
- 사용자 요약
- hook
- risk flags

출력:

- `b_scene_plan.json`

원칙:

- 원문 직접 인용 금지
- 댓글 직접 인용 금지
- 실명/닉네임/개인정보 추정 금지
- 범죄 단정 금지
- 원본에 없는 숫자/순위/사실 추가 금지
- Pydantic validation 통과 전 저장 금지

## C. 프로젝트 컴파일러

C는 렌더러가 아니라 compiler입니다.

입력:

- `source.json`
- `b_scene_plan.json`

출력:

- `timeline.json`
- `assets/placeholders/slot_XXX_placeholder.png`
- `assets/user_images/slot_XXX.png`
- `assets/text_overlays/sXX_text.png`
- `project.kdenlive`
- `notes/replace_images.md`

원칙:

- LLM은 `start_sec`를 정하지 않는다.
- C가 scene duration을 누적해 `start_sec`를 계산한다.
- 초기 `slot_XXX.png`는 placeholder 복사본이다.
- 사용자는 동일 파일명으로 이미지를 교체할 수 있다.
- text overlay는 PNG로 생성한다.

## D. 이미지 삽입 단계

사용자는 다음 중 하나로 이미지를 삽입합니다.

- A안: `assets/user_images/slot_001.png`를 같은 파일명으로 교체
- B안: Kdenlive에서 slot clip을 직접 교체

D 완료 후 `d_image_manifest.json`을 작성합니다.

필수 확인:

- image_insert_completed
- user_confirmed
- actual_image_note
- rights_confirmed_by_user
- contains_face
- contains_personal_info
- contains_original_capture

## E. 내레이션/제목 생성

입력:

- `timeline.json`
- `d_image_manifest.json`
- source_reference

출력:

- `e_script.json`

원칙:

- 사용자가 직접 녹음한다.
- 자동 TTS는 없다.
- 대본은 말하기 쉬워야 한다.
- 제목은 강하게 만들되 사실을 조작하지 않는다.
- 추천 제목은 title candidates 중 하나여야 한다.

## 저장소 구조

```text
projects/
  PRJ_YYYYMMDD_NNNN/
    source.json
    b_scene_plan.json
    timeline.json
    d_image_manifest.json
    e_script.json
    project.kdenlive
    assets/
      placeholders/
      user_images/
      text_overlays/
    notes/
    exports/
    logs/
```
[/FILE]

[FILE: docs/02_DATA_CONTRACTS.md]
# 02. Data Contracts

모든 artifact는 명시적 schema version을 갖고, Pydantic validation을 통과해야 저장할 수 있습니다.

## CandidateCard

세션 임시 후보 카드입니다. DB에 자동 저장하지 않습니다.

```python
EphemeralCandidate.status = "new" | "selected" | "rejected_in_session"
```

필수 필드:

- candidate_id
- title
- source_url
- community
- collected_at
- summary
- hook
- why_shortable
- risk_flags_for_user
- status

## Project.status

DB에 저장되는 프로젝트 상태입니다.

```text
candidate_selected
planned
project_generated
waiting_for_user_images
images_inserted
script_generated
recording_done
final_editing
completed
archived
failed
```

상태 전이는 `src/shorts_pipeline/state_machine.py` 한 곳에서만 관리합니다.

## BScenePlan

schema version:

```text
b_scene_plan.v2.1
```

핵심 필드:

- selected_style
- style_reason
- target_duration_sec
- scene_plan
- risk_flags

ScenePlanItem 필수 필드:

- scene_id: `s01`, `s02` 형식
- duration_sec: 1초 초과, 12초 이하
- purpose
- screen_text: 40자 이하
- visual_direction
- image_slot_description
- narration_intent
- source_basis
- do_not_say

Validation rules:

- scene_id는 연속이어야 한다.
- duration 합은 target_duration_sec ± 5초 안에 있어야 한다.
- source_basis는 비어 있으면 안 된다.
- screen_text는 원문 직접 인용처럼 보이면 reject한다.
- do_not_say에는 최소한 하나 이상의 안전 관련 금지 항목이 있어야 한다.

## TimelineJson

schema version:

```text
timeline.v2.1
```

원칙:

- `start_sec`는 C가 계산한다.
- 모든 scene은 image path와 text overlay path를 갖는다.
- total duration은 30~60초 범위에 있어야 한다.

## DImageManifest

schema version:

```text
d_image_manifest.v2.1
```

E 실행 전 필수 입력입니다.

slot별 필수 확인:

- slot_id
- scene_id
- status: `placeholder` 또는 `replaced`
- actual_image_note
- source_type
- rights_confirmed_by_user
- contains_face
- contains_personal_info
- contains_original_capture

## EScript

schema version:

```text
e_script.v2.1
```

Validation rules:

- 모든 scene_id가 timeline에 존재해야 한다.
- recommended_title은 title_candidates 중 하나여야 한다.
- title은 fact_basis를 넘는 사실 단정을 하면 안 된다.
- narration script는 원문 직접 인용처럼 보이면 reject한다.

## SQLite tables

첫 구현에서 필요한 table:

- projects
- llm_runs
- plans
- timelines
- artifacts
- image_manifests
- scripts
- events

DB 원칙:

- `PRAGMA foreign_keys=ON`
- `PRAGMA journal_mode=WAL`
- artifact path는 프로젝트 루트 하위 상대경로만 저장한다.
- 원문 전체, 댓글 전체, API key, secret은 저장하지 않는다.
[/FILE]

[FILE: docs/03_SECURITY_POLICY.md]
# 03. Security and Policy

## 파일 보안

프로젝트 파일은 지정된 project root 하위에서만 생성합니다.

금지:

- 절대경로 resource
- `../` path traversal
- 외부 URL resource
- 외부 `.kdenlive` input 신뢰
- XML escape 없이 텍스트 삽입

허용 확장자:

- `.png`
- `.jpg`
- `.jpeg`
- `.webp`

Kdenlive 정책:

- 자체 생성 템플릿만 사용한다.
- 자체 생성 산출물만 open 대상으로 안내한다.
- 실제 template 생성 버전과 사용자 Kdenlive 버전은 metadata에 기록하고 경고한다.

## LLM 보안

금지:

- API key를 DB/log/repo에 저장
- 원문 전체를 LLM에 전송
- 댓글 전체를 LLM에 전송
- 개인정보 추정 데이터를 LLM 입력에 포함
- validation 전 LLM 출력을 artifact로 저장

허용:

- 사용자 입력 요약
- 최소 source metadata
- risk flags
- timeline fact_basis
- d_image_manifest note

## 콘텐츠 안전

금지:

- 실명 추정
- 닉네임 추정 또는 노출
- 얼굴/학교/직장/IP 등 개인정보성 추정
- 범죄 단정
- 원본에 없는 숫자/순위/사실 추가
- 댓글/원문 직접 인용
- 원본 캡처 재사용 권장
- 특정 개인 조롱 강화
- 혐오 표현 강화

## 커뮤니티 수집 안전

v2.1 기본값:

```toml
[collectors.dcinside]
enabled = false
mode = "manual_url_only"
requires_terms_review = true
store_raw_body = false
store_comments = false
```

금지:

- 자동 크롤러 기본 활성화
- 로그인 우회
- CAPTCHA 우회
- 봇 탐지 우회
- IP 회전
- 헤더 위장
- rate-limit 우회
- 약관/robots 검토 없는 수집

## 로그 정책

로그에는 다음을 저장하지 않습니다.

- API key
- secret
- 원문 전체
- 댓글 전체
- 개인정보
- 원본 캡처

로그에는 redacted summary와 error code 중심으로 저장합니다.
[/FILE]

[FILE: docs/04_CODEX_WORKFLOW.md]
# 04. GPT Pro ↔ Codex Workflow

## 역할

GPT Pro:

- 제품/기술 설계
- 명세 검증
- Codex 작업 단위 분해
- Codex 결과 리뷰
- 다음 Codex prompt 생성

Codex:

- repo 파일 생성/수정
- 테스트 작성
- 명령 실행
- 결과 보고

## 세션 간 상태 저장소

채팅 기억을 신뢰하지 않습니다. 상태는 repo 파일과 Codex Result Report에 저장합니다.

필수 상태 저장 위치:

- `docs/`
- `AGENTS.md`
- test files
- Codex Result Report

## 라운드 규칙

1. GPT Pro가 작고 명확한 `CODEX_PROMPT_00X`를 만든다.
2. Codex는 prompt와 repo 문서를 읽고 구현한다.
3. Codex는 테스트를 실행한다.
4. Codex는 Result Report를 반환한다.
5. GPT Pro가 report와 diff를 검토한다.
6. GPT Pro가 다음 prompt를 만든다.

## Codex Result Report 필수 항목

- Task ID
- Summary
- Files Created
- Files Modified
- Commands Run
- Test Results
- Decisions Made
- Assumptions
- Known Issues / Blockers
- Security/Policy Check
- Recommended Next Task

## 첫 라운드 제한

첫 라운드에서는 다음만 수행합니다.

- repo scaffold
- docs
- DB schema
- Pydantic models
- state machine
- security helper skeleton
- pytest skeleton

첫 라운드에서 하지 않습니다.

- 실제 OpenAI/Claude/Gemini API 호출
- 실제 커뮤니티 자동 수집
- Streamlit 전체 UI
- 실제 production-ready Kdenlive XML mutation
- 자동 TTS
- 자동 업로드
[/FILE]

[FILE: docs/05_PHASE_PLAN.md]
# 05. Phase Plan

## Phase 0. Repo baseline

목표:

- 문서와 데이터 계약을 repo 안에 고정
- Python package scaffold 생성
- 테스트 실행 환경 생성

완료 기준:

- `pytest`가 실행된다.
- docs가 존재한다.
- Pydantic models가 import된다.
- SQLite schema init smoke test가 통과한다.

## Phase 1. Local project core

목표:

- SQLite 초기화
- project directory generator
- manual candidate to project 생성
- state transition 구현

완료 기준:

- 수동 후보 fixture 1개로 project row와 project folder가 생성된다.
- `source.json`이 생성된다.
- 불법 상태 전이는 reject된다.

## Phase 2. B generation skeleton

목표:

- B Pydantic model
- mock LLM client
- validation/retry structure

완료 기준:

- valid fixture는 통과한다.
- scene_id 불연속, duration 초과, source_basis 누락은 reject된다.

## Phase 3. C compiler prototype

목표:

- `timeline.json` 생성
- start time assignment
- placeholder PNG 생성
- text overlay PNG 생성
- Kdenlive XML/path validation skeleton

완료 기준:

- timeline validation 통과
- slot files 존재
- overlay files 존재
- path traversal/external URL reject

## Phase 4. D image manifest

목표:

- slot별 actual image note와 rights confirmation 기록
- D manifest validation

완료 기준:

- 모든 slot에 status가 기록된다.
- replaced slot은 actual_image_note가 있어야 한다.
- rights confirmation 없으면 E로 못 넘어간다.

## Phase 5. E script/title skeleton

목표:

- E Pydantic model
- mock LLM client
- title/narration validation

완료 기준:

- 모든 timeline scene에 대본이 있다.
- recommended title은 candidates 중 하나다.
- forbidden claims가 비어 있으면 reject된다.

## Phase 6. Integration and smoke tests

목표:

- manual source -> B -> C -> D -> E happy path
- Kdenlive manual open smoke test

완료 기준:

- generated project has no missing media
- vertical 1080x1920 30fps metadata 확인
- sample 10개 이상에서 artifact 생성 성공
[/FILE]

[FILE: docs/06_TEST_PLAN.md]
# 06. Test Plan

## Unit tests

필수:

- CandidateCard validation
- BScenePlan validation
- TimelineJson validation
- DImageManifest validation
- EScript validation
- state transition validation
- safe path validation
- external URL resource rejection
- XML escaping helper

## DB tests

필수:

- schema init succeeds
- foreign keys enabled
- WAL mode attempted
- projects table exists
- artifacts table exists
- invalid project status rejected by CHECK constraint

## Timeline tests

필수:

- start_sec is assigned by duration accumulation
- total duration is computed correctly
- scene_id order is preserved
- duration out of range fails validation

## Security tests

필수:

- `../evil.png` is rejected
- `/absolute/path.png` is rejected
- `https://example.com/a.png` is rejected as media resource
- XML special characters are escaped
- `.env` is not read into logs

## Integration tests

후속 라운드:

- manual source -> project folder
- B fixture -> timeline
- timeline -> placeholder files
- timeline -> Kdenlive XML parse
- D manifest -> E input

## Manual smoke tests

후속 라운드:

- Kdenlive에서 `project.kdenlive` 열기
- missing media 없음 확인
- slot image 표시 확인
- text overlay 표시 확인
- `slot_001.png` 교체 후 반영 확인

## Red-team tests

후속 라운드:

- 실명 추정 유도
- 범죄 단정 제목 유도
- 허위 수치 추가 유도
- 댓글 직접 인용 유도
- 원본 캡처 사용 유도
- 특정 개인 조롱 유도
[/FILE]

[FILE: .gitignore]
# Python
__pycache__/
*.py[cod]
*.pyo
*.pyd
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/

# Virtual environments
.venv/
venv/
env/

# Secrets
.env
*.env
!.env.example

# Local generated projects and exports
projects/
exports/

# OS / editor
.DS_Store
.idea/
.vscode/

# Build artifacts
build/
dist/
*.egg-info/
[/FILE]

[FILE: .env.example]
# Copy to .env locally. Never commit real secrets.

OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=

SHORTS_PIPELINE_PROJECT_ROOT=projects
SHORTS_PIPELINE_DB_PATH=projects/shorts_pipeline.sqlite3
SHORTS_PIPELINE_KDENLIVE_MIN_VERSION=26.04.1
[/FILE]

[FILE: pyproject.toml]
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "shorts-pipeline"
version = "0.1.0"
description = "Local semi-automated Shorts production pipeline MVP"
requires-python = ">=3.11"
dependencies = [
  "pydantic>=2.0",
  "python-dotenv>=1.0",
  "pillow>=10.0",
  "lxml>=5.0",
  "python-dateutil>=2.9",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "ruff>=0.4",
]
ui = [
  "streamlit>=1.0",
]
llm = [
  "openai>=1.0",
  "anthropic>=0.0",
  "google-genai>=1.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"
[/FILE]

---

## D. CODEX_PROMPT_001

```text
너는 이 repo의 구현 담당 Codex다.

기준 명세는 사용자가 제공한 `shorts_pipeline_v2_1_verified_spec.md`와 이 프롬프트의 지시다. 현재 작업은 첫 번째 라운드이며, 목표는 “repo scaffold + docs + DB schema + Pydantic models + tests skeleton”까지만 구현하는 것이다.

중요 역할 분리:
- GPT Pro는 설계/리뷰/다음 프롬프트 생성 담당이다.
- Codex는 repo 파일 생성/수정/테스트/보고 담당이다.
- 채팅 기억을 믿지 말고 repo 문서와 결과 보고서를 상태 저장소로 삼아라.

절대 금지:
- 커뮤니티 자동 크롤러를 기본 활성화하지 마라.
- 디시/커뮤니티 원문 전체 또는 댓글 전체를 저장하는 코드를 만들지 마라.
- API key/secret을 저장하거나 로그에 남기지 마라.
- 외부 `.kdenlive` 파일을 신뢰하거나 파싱하지 마라.
- 자동 TTS, 자동 업로드, 자동 이미지 삽입을 구현하지 마라.
- 로그인 우회, CAPTCHA 우회, IP 회전, 헤더 위장, rate-limit 우회 코드를 만들지 마라.
- 실제 OpenAI/Claude/Gemini API 호출을 이번 라운드에서 구현하지 마라.

이번 라운드에서 해야 할 일:

1. 다음 문서/설정 파일을 생성하라. 내용은 GPT Pro가 제공한 [FILE: ...] 블록을 그대로 사용하라.
   - README.md
   - AGENTS.md
   - docs/00_PROJECT_BRIEF.md
   - docs/01_ARCHITECTURE.md
   - docs/02_DATA_CONTRACTS.md
   - docs/03_SECURITY_POLICY.md
   - docs/04_CODEX_WORKFLOW.md
   - docs/05_PHASE_PLAN.md
   - docs/06_TEST_PLAN.md
   - .gitignore
   - .env.example
   - pyproject.toml

2. Python package scaffold를 생성하라.
   - src/shorts_pipeline/__init__.py
   - src/shorts_pipeline/config.py
   - src/shorts_pipeline/models.py
   - src/shorts_pipeline/state_machine.py
   - src/shorts_pipeline/db.py
   - src/shorts_pipeline/security.py
   - src/shorts_pipeline/projectgen/__init__.py
   - src/shorts_pipeline/projectgen/timeline.py
   - src/shorts_pipeline/projectgen/placeholder.py
   - src/shorts_pipeline/projectgen/text_overlay.py
   - src/shorts_pipeline/llm/__init__.py
   - src/shorts_pipeline/llm/validators.py

3. `models.py`에 v2.1 기준 Pydantic 모델을 구현하라.
   최소 포함 모델:
   - CandidateCard
   - ScenePlanItem
   - BScenePlan
   - CanvasSpec
   - TimelineScene
   - TimelineJson
   - DImageSlotManifest
   - DImageManifest
   - NarrationLine
   - TitleCandidate
   - EScript

   모델 규칙:
   - 모든 모델은 `ConfigDict(extra="forbid")`를 사용한다.
   - scene_id는 `s01`, `s02` 패턴을 사용한다.
   - B scene duration은 `gt=1.0`, `le=12.0`이다.
   - B target duration은 30~60초다.
   - screen_text는 40자 이하로 제한한다.
   - E recommended_title은 title_candidates 중 하나여야 한다.
   - D replaced slot은 actual_image_note가 비어 있으면 안 된다.
   - D rights_confirmed_by_user가 false면 validation 또는 helper에서 E 진행 불가로 판단할 수 있게 하라.

4. `state_machine.py`에 Project.status 전이 규칙을 구현하라.
   상태:
   - candidate_selected
   - planned
   - project_generated
   - waiting_for_user_images
   - images_inserted
   - script_generated
   - recording_done
   - final_editing
   - completed
   - archived
   - failed

   함수 예시:
   - `can_transition(current: str, target: str) -> bool`
   - `assert_transition_allowed(current: str, target: str) -> None`

5. `db.py`에 SQLite schema init을 구현하라.
   필수:
   - `PRAGMA foreign_keys=ON`
   - `PRAGMA journal_mode=WAL`
   - tables: projects, llm_runs, plans, timelines, artifacts, image_manifests, scripts, events
   - projects.status에는 CHECK constraint를 둔다.
   - helper 함수: `connect_db(path: Path | str)`, `init_db(conn)`

6. `config.py`에 최소 설정과 시간 helper를 구현하라.
   필수:
   - `now_kst_iso()`
   - project root env var: `SHORTS_PIPELINE_PROJECT_ROOT`, default `projects`
   - db path env var: `SHORTS_PIPELINE_DB_PATH`, default `projects/shorts_pipeline.sqlite3`
   - API key 값을 로그하거나 반환하는 helper는 만들지 마라.

7. `security.py`에 파일 보안 helper skeleton을 구현하라.
   필수:
   - `ensure_relative_project_path(path: str | Path) -> Path`
   - `reject_external_resource(resource: str) -> None`
   - `xml_escape_text(text: str) -> str`
   - `validate_media_extension(path: str | Path) -> None`
   - 절대경로, `../`, `http://`, `https://`, 허용 외 확장자 reject 테스트가 통과해야 한다.

8. `projectgen/timeline.py`에 start time assignment를 구현하라.
   필수:
   - `assign_start_times(scenes)` 또는 동등 함수
   - duration 누적으로 start_sec 계산
   - 소수점 3자리 round

9. placeholder/text_overlay 파일은 production 구현이 아니라 인터페이스 skeleton만 둬라.
   - 함수 정의와 docstring을 둔다.
   - 실제 이미지 생성은 간단한 Pillow 기반 최소 구현까지는 허용한다.
   - 단, Kdenlive XML production mutation은 이번 라운드에서 구현하지 않는다.

10. templates와 schemas 폴더를 생성하라.
   - templates/TEMPLATE_METADATA.json 생성
   - templates/kdenlive_vertical_1080x1920_30fps.kdenlive는 dev-only placeholder임을 주석/내용으로 명확히 표시하라.
   - schemas/README.md에 “Pydantic model에서 생성, 수동 편집 금지” 정책을 적어라.

11. tests를 작성하라.
   필수 파일:
   - tests/fixtures/sample_source.json
   - tests/fixtures/sample_b_scene_plan.json
   - tests/test_models.py
   - tests/test_state_machine.py
   - tests/test_timeline.py
   - tests/test_security.py
   - tests/test_db.py

   필수 테스트:
   - CandidateCard valid fixture 통과
   - BScenePlan valid fixture 통과
   - scene_id 불연속 reject 또는 validator helper에서 fail
   - TimelineJson valid 생성 통과
   - EScript recommended_title이 candidates 밖이면 fail
   - D replaced slot에 actual_image_note 없으면 fail
   - valid/invalid state transition
   - `../evil.png`, `/absolute/path.png`, `https://example.com/a.png` reject
   - XML escape helper가 `<`, `>`, `&`, quote를 escape
   - SQLite schema init smoke test

12. 가능한 명령을 실행하라.
   우선순위:
   - `python -m pytest`
   - 가능하면 `python -m ruff check .`

13. 작업 종료 후 아래 `CODEX_RESULT_REPORT_TEMPLATE` 형식으로 결과를 보고하라.
   특히 “실제 API 호출 없음”, “자동 크롤러 없음”, “외부 .kdenlive 신뢰 없음”, “원문/댓글 전체 저장 없음”을 Security/Policy Check에 명확히 표시하라.
```

---

## E. CODEX_RESULT_REPORT_TEMPLATE

```markdown
# Codex Result Report

## Task ID
CODEX_PROMPT_001

## Summary
- ...

## Files Created
- `path`: purpose

## Files Modified
- `path`: summary of changes

## Commands Run
```bash
...
```

## Test Results
```text
...
```

## Decisions Made
- ...

## Assumptions
- ...

## Known Issues / Blockers
- ...

## Security/Policy Check
- [ ] No external API calls added
- [ ] No scraping/crawling enabled by default
- [ ] No storage of full source posts/comments
- [ ] No API keys or secrets committed
- [ ] No external `.kdenlive` input trusted
- [ ] No TTS/upload/image-auto-insert added
- [ ] Path traversal rejected
- [ ] External URL media resources rejected
- [ ] XML escaping helper exists and is tested

## Recommended Next Task
- ...
```

---

## F. GPT_REVIEW_PROMPT_TEMPLATE

```text
너는 이 프로젝트의 GPT Pro 기술 리드이자 코드 리뷰어다.

기준 명세:
- `shorts_pipeline_v2_1_verified_spec.md`
- repo 안의 `README.md`, `AGENTS.md`, `docs/` 문서
- 이전 GPT Pro가 작성한 `CODEX_PROMPT_001`

검토 목표:
1. Codex 결과가 v2.1 명세와 충돌하는지 확인한다.
2. 첫 라운드 범위를 넘겨 과도 구현한 부분이 있는지 확인한다.
3. 특히 다음 금지사항 위반이 있는지 확인한다.
   - 전체 A 후보 히스토리 저장
   - 디시/커뮤니티 자동 크롤링 기본 활성화
   - 외부 `.kdenlive` 파일 신뢰
   - API key/secret 저장
   - 원문/댓글 전체 저장
   - 자동 TTS 구현
   - 자동 업로드 구현
   - 자동 이미지 삽입 구현
   - CAPTCHA/로그인/rate-limit 우회 구현
4. Pydantic 모델이 명세의 데이터 계약을 충분히 반영했는지 확인한다.
5. SQLite schema가 v2.1 저장 정책과 맞는지 확인한다.
6. state machine과 security helper 테스트가 충분한지 확인한다.
7. 다음 Codex 라운드로 넘어가기 위한 수정사항을 우선순위별로 정리한다.
8. 다음 Codex 라운드에 붙여넣을 `CODEX_PROMPT_002`를 작성한다.

출력 형식:

A. Verdict
- ACCEPT / ACCEPT_WITH_FIXES / REJECT

B. Critical issues
- v2.1과 충돌하거나 보안/정책 위반인 항목

C. Non-critical improvements
- 구조 개선, 이름 개선, 후속 phase에서 처리할 항목

D. Missing tests
- 지금 반드시 추가할 테스트
- 다음 phase에서 추가할 테스트

E. Scope control
- Codex가 너무 많이 구현한 부분
- 아직 구현하지 않아야 하는 부분

F. Exact next Codex prompt
- `CODEX_PROMPT_002` 전체를 코드블록으로 작성

아래가 Codex 결과 보고서와 diff 요약이다.

[PASTE_CODEX_RESULT_REPORT_HERE]

[PASTE_DIFF_SUMMARY_OR_RELEVANT_FILES_HERE]
```
