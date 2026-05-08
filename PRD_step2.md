# PRD Step 2: 레시피 생성 시스템
**Phase 2 — 인식 재료 기반 AI 레시피 추천 (Gemma 4 31B)**

## 1. 프로젝트 개요

### 1.1 목표
Step 1에서 얻은 식재료 목록을 바탕으로 `google/gemma-4-31b-it:free` 모델을 활용해 **즉시 조리 가능한 레시피 후보**를 생성·표시한다.

### 1.2 범위
- Step 1의 재료 리스트(JSON) 수신 및 사용자 편집 반영
- 사용자 옵션 입력: 인분 수, 가용 조리 시간, 난이도, 식단 제한(채식/할랄 등)
- `google/gemma-4-31b-it:free` 호출로 레시피 N개 생성 (기본 3개)
- 카드 형태로 레시피 표시 + 단일 레시피 상세 보기
- "다시 생성", "다른 레시피 더 보기" 흐름

### 1.3 개발 기간
5일 (1주)

### 1.4 성공 지표
| 지표 | 목표 |
|---|---|
| 입력 재료 활용률(레시피 내 사용된 재료 비율) | ≥ 60% |
| 레시피 1세트 생성 응답 시간 | ≤ 20초 |
| JSON 스키마 파싱 성공률 | ≥ 95% |
| 사용자 만족도(베타 테스트, 5점 척도) | ≥ 4.0 |

## 2. 기술 스택 (Step 1 위에 추가)

```yaml
신규 추가:
  - jsonschema       # 모델 응답 스키마 검증
  - markdown         # 레시피 본문 렌더링
  - 모델: google/gemma-4-31b-it:free  (text → text, 한국어 강함)
```

## 3. 시스템 아키텍처 변경

```
[Step 1 출력: ingredients]
          │
          ▼
┌────────────────────┐
│  RecipeOptionsForm │  인분/시간/난이도/제한
└──────────┬─────────┘
           │
┌──────────▼─────────┐
│   PromptBuilder    │  system + user prompt 조합
└──────────┬─────────┘
           │
┌──────────▼─────────┐
│ OpenRouterClient   │  google/gemma-4-31b-it:free
└──────────┬─────────┘
           │
┌──────────▼─────────┐
│   RecipeParser     │  JSON 검증 + 정규화
└──────────┬─────────┘
           │
┌──────────▼─────────┐
│   RecipeCardsUI    │  카드 N개 + 상세 모달
└────────────────────┘
```

## 4. 프로젝트 구조 변경

```
backend/
├── recipe_generator.py     # PromptBuilder + 호출 + 파싱
├── recipe_schema.py        # jsonschema 정의
└── prompts/
    └── recipe_system.txt   # 시스템 프롬프트 외부화
ui_components.py            # RecipeCard, RecipeDetail
```

## 5. 핵심 기능 상세

### 5.1 사용자 옵션
| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| servings | int (1~6) | 2 | 인분 수 |
| max_minutes | int (10~120) | 30 | 최대 조리 시간 |
| difficulty | enum | "쉬움" | 쉬움/보통/어려움 |
| diet | list[enum] | [] | 채식/비건/할랄/저염/저당 |
| allergens | list[str] | [] | 갑각류/견과류/유제품 등 |
| num_recipes | int (1~5) | 3 | 추천 개수 |

### 5.2 프롬프트 설계

**System (외부 파일):**
```
너는 한국어로 답하는 요리 어시스턴트다.
주어진 재료, 인분, 시간, 난이도, 식단 제한을 모두 만족하는
서로 다른 레시피 N개를 JSON 객체 하나로만 반환한다.
주어진 재료를 최대한 활용하되, 흔한 양념(소금/후추/식용유 등)은 자유롭게 가정해도 된다.
JSON 외 설명/마크다운/코드펜스를 절대 출력하지 마라.
```

**User (PromptBuilder 동적 생성):**
```
재료: {ingredients_csv}
인분: {servings}, 최대 {max_minutes}분, 난이도: {difficulty}
식단 제한: {diet}, 알레르기: {allergens}
추천 수: {num_recipes}

응답 스키마:
{ "recipes": [
    { "title": "...",
      "summary": "1-2 문장 요약",
      "estimated_minutes": 25,
      "difficulty": "쉬움",
      "servings": 2,
      "ingredients_used": [{"name":"...","amount":"...","from_fridge":true}],
      "extra_ingredients": [{"name":"소금","amount":"적당량"}],
      "steps": ["1) ...", "2) ..."],
      "tips": ["..."]
    }
] }
```

### 5.3 모델 호출
```python
MODEL = "google/gemma-4-31b-it:free"
payload = {
    "model": MODEL,
    "response_format": {"type": "json_object"},
    "temperature": 0.7,    # 다양성 확보
    "messages": [
        {"role": "system", "content": load_system_prompt()},
        {"role": "user",   "content": build_user_prompt(state)},
    ],
}
```
- 재시도/429 대응은 Step 1의 `OpenRouterClient` 재사용
- 비용: 무료 티어 ($0)

### 5.4 응답 검증 (jsonschema)
- 필수 필드 누락/타입 불일치 시 1회 재호출
- 2회 실패 시 원시 텍스트와 함께 "다시 생성" 버튼 노출

### 5.5 UI/UX
- 옵션 입력은 사이드바에 배치, 본문 상단에 "🍳 레시피 생성" 버튼
- 결과는 가로 카드 N개 (제목, 요약, 시간/난이도 뱃지, "상세 보기" 버튼)
- 상세 보기: 단계별 조리법, 재료 표, 팁
- "다시 생성" / "다른 레시피 더 보기"(이전 결과 누적)
- 생성 도중 `st.status` 진행 표시

## 6. 상태 관리

- `st.session_state["ingredients"]` ← Step 1 결과
- `st.session_state["recipe_options"]` ← 옵션 폼 값
- `st.session_state["recipes"]` ← 누적된 레시피 리스트
- "다시 생성"은 `recipes` 초기화 후 새로 호출
- "더 보기"는 동일 옵션으로 1회 더 호출 후 결과 append (중복 제목 제거)

## 7. 에러 처리

| 상황 | 처리 |
|---|---|
| 재료 0개 | 생성 버튼 비활성, "Step 1로 돌아가기" 안내 |
| 모델 응답이 JSON이 아님 | 1회 재호출 → 실패 시 raw 출력 + 재생성 버튼 |
| 식단 제한과 충돌하는 레시피 반환 | 후처리 필터로 제거, 부족하면 추가 호출 |
| 429 / upstream 제한 | Step 1과 동일 백오프, 사용자에게 대기 안내 |
| 응답이 너무 짧음(steps < 3) | 자동 재호출(최대 2회) |

## 8. 테스트 계획

- **골든 입력 셋**: 재료 5세트(예: 김치+두부+계란 / 양파+감자+버섯 …) — 각 입력에 대해 결과의 형식·가용시간·식단준수 자동 검증
- **스키마 검증 단위 테스트**: 정상/이상 응답 픽스처
- **수동 QA**: 한국어 자연스러움, 단계 순서 논리성, 재료 양 합리성

## 9. 다음 단계 연계

- Step 2 산출물: `Recipe` 객체(JSON 직렬화 가능)
- Step 3에서 사용자별로 이 객체를 즐겨찾기/저장하게 됨
- 따라서 `Recipe`에 안정적인 `id`(해시 기반: title+ingredients_used)와 `created_at` 필드를 함께 부여한다.

## 10. 리스크

| 리스크 | 완화 |
|---|---|
| 모델이 영어로 답함 | 시스템 프롬프트 한글 명시 + temperature 낮춤 |
| 가공 식재료(예: 카레가루)를 자의적으로 추가 | `extra_ingredients` 카테고리에 분리 표시 |
| 같은 재료로 비슷한 레시피만 생성 | temperature 0.7~0.9, "서로 다른 조리법" 명시 |
| 429 과다 발생 | 옵션 변경 시 캐시(같은 입력은 재호출 금지) |
