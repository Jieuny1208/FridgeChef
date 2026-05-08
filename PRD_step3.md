# PRD Step 3: 사용자 프로필 및 레시피 저장 시스템
**Phase 3 — 개인화 및 데이터 영속화**

## 1. 프로젝트 개요

### 1.1 목표
사용자별 프로필을 도입해 Step 2에서 생성된 레시피를 저장·관리하고, 식단 제한·즐겨찾기를 활용한 개인화 추천 기반을 마련한다.

### 1.2 범위
- 간단한 사용자 등록/로그인 (스터디 수준의 로컬 인증)
- 프로필 정보: 표시명, 식단 제한, 알레르기, 선호 조리 시간
- 레시피 저장(즐겨찾기), 메모, 평점(1~5)
- 저장된 레시피 목록 조회 / 검색 / 삭제
- Step 2의 옵션 기본값을 프로필에서 자동 채움(개인화)

### 1.3 개발 기간
5일 (1주)

### 1.4 성공 지표
| 지표 | 목표 |
|---|---|
| 회원가입 → 첫 레시피 저장까지 평균 클릭 수 | ≤ 5 |
| 저장 후 재로그인 시 데이터 유지율 | 100% |
| 프로필 기반 옵션 자동 적용률 | 100% |
| 레시피 검색(제목/재료) 응답 시간 | ≤ 200ms (100건 기준) |

## 2. 기술 스택 (Step 2 위에 추가)

```yaml
신규 추가:
  - bcrypt 또는 passlib   # 비밀번호 해시
  - pydantic              # 사용자/레시피 모델
  - filelock              # users.json/saved_recipes.json 동시쓰기 방지
  - streamlit-authenticator (선택)  # 로그인 UI 보조
```
> 학습용 프로젝트이므로 DB 없이 **JSON 파일**(`users.json`, `saved_recipes.json`)로 영속화한다.

## 3. 시스템 아키텍처 변경

```
                      ┌────────────────┐
                      │  AuthService   │ 회원가입/로그인/세션
                      └────┬───────────┘
                           │
[Streamlit UI] ───────────►│◄────── ProfileService
       │                   │
       │   ┌───────────────▼─────────────┐
       │   │  RecipeStore (JSON + lock)  │
       │   └───────────────┬─────────────┘
       │                   │
       └────► Step 2 결과를 RecipeStore에 저장
```

## 4. 프로젝트 구조 변경

```
backend/
├── auth_service.py      # signup/login/logout, 세션
├── profile_service.py   # 프로필 CRUD, 개인화 옵션
├── recipe_store.py      # 즐겨찾기 저장/검색
└── models.py            # User, Profile, SavedRecipe (pydantic)
data/
├── users.json           # (gitignored)
└── saved_recipes.json   # (gitignored)
```

## 5. 데이터 모델

```python
class User(BaseModel):
    id: str                 # uuid4
    username: str           # 고유, 소문자
    password_hash: str      # bcrypt
    created_at: datetime

class Profile(BaseModel):
    user_id: str
    display_name: str
    diet: list[Literal["vegetarian","vegan","halal","low_salt","low_sugar"]] = []
    allergens: list[str] = []
    default_servings: int = 2
    default_max_minutes: int = 30
    default_difficulty: Literal["쉬움","보통","어려움"] = "쉬움"

class SavedRecipe(BaseModel):
    id: str                 # 해시(title + ingredients_used)
    user_id: str
    recipe: dict            # Step 2의 Recipe 원형
    note: str = ""
    rating: int | None = None  # 1~5
    saved_at: datetime
    tags: list[str] = []
```

## 6. 핵심 기능 상세

### 6.1 회원가입 / 로그인
- username 정규식: `^[a-z0-9_]{3,20}$`
- 비밀번호 정책: 8자 이상, 영문/숫자 조합
- 비밀번호는 bcrypt(`cost=12`)로 해시 후 저장 — 평문 저장 절대 금지
- 로그인 성공 시 `st.session_state["user"]`에 `User` 저장 (페이지 갱신 사이 유지)
- 로그아웃: 세션 초기화

> 보안 한계 명시: 본 시스템은 **로컬 학습용**이며 운영 환경에서는 OAuth/세션 토큰/HTTPS가 필요하다. 메모리에 평문 비밀번호를 보관하지 않고, 입력 직후 해시하여 비교만 수행한다.

### 6.2 프로필 관리
- 첫 로그인 시 프로필 생성 폼 자동 표시
- 프로필 수정 페이지: 식단 제한, 알레르기, 기본 옵션
- 변경 사항은 즉시 `users.json`(또는 별도 `profiles` 섹션)에 반영

### 6.3 Step 2 개인화 적용
- Step 2의 옵션 폼 기본값을 **프로필에서 prefill**
- 알레르기 목록은 Step 2 프롬프트의 `allergens`에 자동 합산
- 사용자가 프로필을 무시하고 일회성 변경하는 것도 허용

### 6.4 레시피 저장
- Step 2 결과 카드 / 상세 화면에 "⭐ 저장" 버튼
- 같은 `id`(해시) 중복 저장 방지: 이미 저장돼 있으면 "저장됨" 표시 + 메모/평점 수정으로 전환
- 저장 시 `saved_recipes.json`에 append (filelock으로 동시쓰기 보호)

### 6.5 저장된 레시피 페이지
- 사용자별 필터링(`user_id == current_user.id`)
- 제목/재료 키워드 검색 (대소문자 무시, 부분 일치)
- 정렬: 최신순(기본) / 평점순 / 제목순
- 카드별 액션: 상세 보기, 메모/평점 수정, 태그 추가, 삭제(확인 다이얼로그)

### 6.6 데이터 파일 잠금 & 백업
- 모든 쓰기는 `filelock.FileLock("data/.lock")` 안에서 수행
- 매 쓰기 직전 `*.json.bak`로 1회 백업(원자적 교체: 임시파일 → `os.replace`)
- 손상된 JSON 감지 시: 백업으로 자동 복구 + 사용자에게 통보

## 7. UI/UX 흐름

1. **첫 방문**: 랜딩 → "회원가입" / "로그인" 선택
2. **로그인 후**: 상단 네비 = 사진 업로드(Step1) / 레시피 생성(Step2) / **내 레시피(Step3)** / 프로필
3. **저장 흐름**: Step 2 결과 카드 → ⭐ 저장 → 토스트 "내 레시피에 저장됨"
4. **내 레시피**: 검색창 + 카드 리스트 + 사이드바 필터(태그/평점)
5. **프로필**: 폼 1페이지로 단순화

## 8. 에러 처리

| 상황 | 처리 |
|---|---|
| username 중복 | 가입 시점에 차단, "다른 아이디 사용" |
| 비밀번호 오답 | 일반 메시지("아이디 또는 비밀번호 오류") — 사용자 존재여부 노출 금지 |
| `saved_recipes.json` 손상 | 백업 복구, 실패 시 빈 리스트로 재초기화 + 경고 |
| 동일 `id` 중복 저장 시도 | 무시 + 기존 항목으로 이동 |
| 로그아웃 직후 이전 페이지 접근 | 자동으로 로그인 페이지로 리디렉션 |

## 9. 보안·개인정보 점검 (학습 수준)

- `.gitignore`에 `users.json`, `saved_recipes.json`, `data/temp/*` 포함 (이미 적용됨)
- 비밀번호 해시 외 평문 저장 금지
- API 키는 `.env`(권한 600)에서만 읽기, 클라이언트로 절대 노출 금지
- 사용자 입력 파일명/검색어는 그대로 파일 경로에 사용하지 않음(경로 트래버설 방지)

## 10. 테스트 계획

- 단위 테스트
  - bcrypt 해시/검증
  - JSON 영속화: 동시 쓰기, 손상 복구
  - 검색 정확도(부분 일치, 대소문자)
- 통합 테스트
  - 회원가입 → 로그인 → Step1/2 → 저장 → 재로그인 → 목록 확인의 E2E
  - 프로필 변경이 Step 2 옵션에 즉시 반영되는지
- 수동 QA
  - 동시 두 탭에서 저장 시 충돌 없음
  - 빈 상태(저장 0건) UI

## 11. 마이그레이션 / 향후 확장

- JSON → SQLite 전환 시 데이터 모델은 그대로 사용 (pydantic → SQLAlchemy)
- 사용자별 추천 가중치(즐겨찾기 통계 기반) 추가 여지
- 멀티 사용자 동시성이 커지면 파일 잠금 → DB 트랜잭션으로 교체

## 12. 완료 기준 (Definition of Done)

- [ ] 회원가입/로그인/로그아웃 정상 동작
- [ ] 프로필 생성/수정 후 Step 2 옵션이 자동 반영
- [ ] Step 2 결과를 ⭐로 저장 → 내 레시피 페이지에서 즉시 확인
- [ ] 저장된 레시피 검색/정렬/삭제/메모/평점 동작
- [ ] 재로그인 후 모든 데이터 유지
- [ ] `users.json`·`saved_recipes.json`이 git에 커밋되지 않음
