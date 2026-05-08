---
name: 운영 중인 파일 vs 레거시
description: UX 작업 시 어떤 파일을 수정/유지해야 하는지 명확화
type: project
---

**운영 중(수정 OK):**
- `app.py` (Streamlit 메인 진입점)
- `web/index.html`, `web/app.js`, `web/styles.css`
- `backend/auth_service.py`, `backend/profile_service.py`, `backend/recipe_store.py`, `backend/image_service.py`, `backend/recipe_generator.py`, `backend/openrouter_client.py` — 사용자 노출 카피만 수정 OK, 비즈니스 로직은 건드리지 말 것

**건드리지 말 것 (.bak/legacy/optimized 사본):**
- `app_enhanced.py`, `app_optimized.py`, `app_step2.py`, `app_step3.py`, `ui_components.py`
- `backend/auth.py`, `backend/auth.legacy.bak.py`, `backend/auth_optimized.py`
- `backend/database.py`, `backend/database_optimized.py`
- `backend/image_service_optimized.py`, `backend/recipe_generator.deepseek.bak.py`
- `backend/user_profile.py`, `backend/user_profile.legacy.bak.py`
- `web/backend.js`(API 호출 로직 — 사용자 노출 에러 메시지만 OK)

**Why:** 단계별 학습 진행으로 옛 사본이 다수 존재. 잘못된 파일 수정 시 작업이 반영되지 않고 혼선 유발.

**How to apply:** Streamlit 변경 시 항상 `app.py` (suffix 없음). web 변경 시 `web/index.html`/`app.js`/`styles.css`. 백엔드는 `_service.py` / `_generator.py` / `_store.py`처럼 service 네이밍이 최신.
