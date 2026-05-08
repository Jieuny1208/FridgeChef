# PRD Step 1: 이미지 인식 핵심 기능
**Phase 1 — 냉장고 재료 인식 시스템 구축 (Gemma 4 비전)**

## 1. 프로젝트 개요

### 1.1 목표
사용자가 업로드한 냉장고 사진에서 식재료를 자동 인식해 구조화된 목록으로 반환하는 웹 애플리케이션의 핵심 기능을 구현한다.

### 1.2 범위
- 이미지 업로드 인터페이스 (브라우저)
- OpenRouter 경유 `google/gemma-4-26b-a4b-it:free` 비전 모델 연동
- 이미지 전처리(리사이즈, 인코딩) 및 API 호출
- 인식된 재료 목록 표시 + 사용자 편집(추가/삭제) 기능
- 무료 티어 upstream 429 대응(재시도/백오프)

### 1.3 개발 기간
5일 (1주)

### 1.4 성공 지표
| 지표 | 목표 |
|---|---|
| 이미지 업로드 성공률 | ≥ 95% |
| 재료 인식 정확도(주요 품목 기준) | ≥ 70% |
| 평균 응답 시간(429 제외) | ≤ 15초 |
| 429 발생 시 자동 복구율 | ≥ 80% (5회 재시도 내) |

## 2. 기술 스택

```yaml
Backend:
  - Python 3.10+
  - FastAPI (선택)  또는  Streamlit 단일 앱
  - Pillow            # 이미지 리사이즈/포맷 변환
  - python-dotenv     # .env 로드
  - requests          # OpenRouter HTTP 호출
  - tenacity          # 재시도 백오프

Frontend:
  - Streamlit         # 빠른 프로토타이핑
  - st.file_uploader, st.image, st.data_editor

AI/ML:
  - OpenRouter API
  - 모델: google/gemma-4-26b-a4b-it:free  (text+image → text)
  - 엔드포인트: https://openrouter.ai/api/v1/chat/completions

Secrets:
  - .env 의 OPENROUTER_API_KEY (권한 600, .gitignore 등록 완료)
```

## 3. 시스템 아키텍처

```
┌──────────────────┐
│   Web Browser    │
└────────┬─────────┘
         │ 이미지 업로드
┌────────▼─────────┐
│   Streamlit UI   │
│  - 업로드 위젯    │
│  - 미리보기/편집  │
└────────┬─────────┘
         │
┌────────▼─────────┐
│  ImageProcessor  │  PIL: 리사이즈(≤1024px), JPEG 재인코딩, base64
└────────┬─────────┘
         │
┌────────▼─────────┐
│ OpenRouterClient │  Bearer 인증, 재시도, 응답 파싱
└────────┬─────────┘
         │
┌────────▼─────────┐
│ OpenRouter API   │  google/gemma-4-26b-a4b-it:free
└──────────────────┘
```

## 4. 프로젝트 구조 (Step 1 종료 시점)

```
Study-04/
├── app.py                       # Streamlit 진입점
├── backend/
│   ├── __init__.py
│   ├── config.py                # 환경변수, 모델 ID 상수
│   ├── image_service.py         # 검증·리사이즈·base64
│   ├── openrouter_client.py     # API 호출 + 재시도
│   └── ingredient_recognizer.py # 프롬프트 + JSON 파싱
├── data/
│   └── temp/                    # 임시 업로드 저장
├── tests/
│   └── test_images/             # 골든 이미지 (sample_fridge.jpg 등)
├── .env                         # OPENROUTER_API_KEY
├── .env.example
├── .gitignore
└── requirements_step1.txt
```

## 5. 핵심 기능 상세

### 5.1 이미지 업로드 & 검증
- 허용 확장자: `jpg`, `jpeg`, `png`, `webp`
- 최대 파일 크기: 10MB (초과 시 거절 메시지)
- 깨진 이미지/EXIF 회전 보정: `PIL.ImageOps.exif_transpose`
- 긴 변 1024px 이내로 리사이즈 후 JPEG quality=85로 재인코딩

```python
from PIL import Image, ImageOps
import io, base64

def to_data_url(file_bytes: bytes) -> str:
    img = Image.open(io.BytesIO(file_bytes))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((1024, 1024))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/jpeg;base64,{b64}"
```

### 5.2 재료 인식 (Gemma 4 26B 비전)
- **모델 ID**: `google/gemma-4-26b-a4b-it:free`
- **요청 본문**: OpenAI 호환 chat-completions 포맷, multimodal `content` 배열

```python
MODEL = "google/gemma-4-26b-a4b-it:free"
SYSTEM = (
    "너는 한국어로 응답하는 식재료 인식 어시스턴트다. "
    "입력 이미지에서 식별 가능한 식재료만 JSON으로 반환한다. "
    "포맷: {\"ingredients\":[{\"name\":\"...\",\"category\":\"채소|과일|육류|...\","
    "\"confidence\":0.0~1.0}]}. JSON 외 설명은 절대 출력하지 않는다."
)

payload = {
    "model": MODEL,
    "response_format": {"type": "json_object"},
    "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": [
            {"type": "text", "text": "이 냉장고 사진에서 식재료 목록을 뽑아줘."},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]},
    ],
}
```

### 5.3 응답 파싱
- `choices[0].message.content` 가 JSON 문자열로 반환됨 → `json.loads`
- 스키마 검증 실패 시 한 번 더 호출(시스템 프롬프트 강화)
- 결과 정규화: 동의어 통합(예: "양파"/"적양파"는 별도 유지, 공백/대소문자 정리)

### 5.4 429 대응 (필수)
무료 티어 특성상 upstream 레이트리밋이 빈번하다. 다음을 구현한다:
- 지수 백오프(2초, 5초, 10초, 25초, 60초) 최대 5회 재시도
- 429 응답의 `metadata.raw` 메시지를 사용자에게 그대로 노출 (대기 시간 안내)
- Streamlit 진행 상태 표시: `st.status("이미지 인식 중…")`

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_result

@retry(stop=stop_after_attempt(5),
       wait=wait_exponential(multiplier=2, min=2, max=60),
       retry=retry_if_result(lambda r: r.status_code in (429, 502, 503)))
def call_openrouter(payload):
    return requests.post(ENDPOINT, headers=HEADERS, json=payload, timeout=60)
```

## 6. API 명세 (내부)

| 함수 | 입력 | 출력 |
|---|---|---|
| `recognize_ingredients(file_bytes)` | bytes | `list[Ingredient]` |
| `Ingredient` | — | `{name:str, category:str, confidence:float}` |

## 7. UI/UX 흐름

1. 첫 화면: 업로드 영역 + 안내 문구 ("냉장고 내부가 보이도록 촬영하세요")
2. 업로드 시 좌측에 미리보기(리사이즈 후 이미지), 우측에 진행 상태
3. 인식 완료 → 재료 표를 `st.data_editor`로 표시 (체크박스로 제외, 행 추가 가능)
4. 하단 "다음 단계로 진행" 버튼 (Step 2 이후 활성화) — 1단계에서는 비활성/임시 표시

## 8. 에러 처리

| 상황 | 처리 |
|---|---|
| 파일 형식 불일치 | 업로드 시점에 차단, 메시지 표시 |
| 10MB 초과 | 차단, 압축 권장 안내 |
| API 401/403 | `.env` 점검 안내 |
| API 404 (모델 없음) | 모델 ID 변경 가능성 안내 + 폴백 모델 제안 |
| API 429 (재시도 5회 초과) | "잠시 후 다시 시도" + 직접 재시도 버튼 |
| JSON 파싱 실패 | 1회 재호출, 그래도 실패 시 원시 텍스트 노출 |

## 9. 테스트 계획

- **골든 셋**: `sample_fridge.jpg` 등 5장 — 각 이미지에 정답 재료 라벨 사전 작성
- **단위 테스트**: 이미지 리사이즈, base64 인코딩, JSON 파서
- **통합 테스트**: 실제 API 1회 호출(429 시 스킵), 응답 스키마 검증
- **수동 QA**: 어두운 사진, 흐릿한 사진, 빈 냉장고 사진 (오탐 확인)

## 10. 다음 단계 연계

- Step 1 산출물: `list[Ingredient]` 객체 + 이미지 메타데이터
- Step 2에 이 목록과 **사용자가 편집한 결과**가 입력으로 넘어감 (세션 상태 또는 캐시 파일에 보관)

## 11. 리스크

| 리스크 | 영향 | 완화 |
|---|---|---|
| Gemma 4 free 풀 포화 | 대기 시간 ↑ | 재시도 + BYOK 안내 |
| 모델이 한글 라벨 대신 영문 출력 | UX 저하 | 시스템 프롬프트로 한글 강제, 후처리 매핑 |
| 비식재료(주방용품) 오탐 | 결과 품질 저하 | 카테고리 화이트리스트 필터 |
