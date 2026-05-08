---
name: FridgeChef 프로젝트 개요
description: Study-04 한국어 AI 레시피 추천 앱(냉장고를 부탁해)의 구조와 사용자 흐름
type: project
---

**개요:** 냉장고 사진 → AI(OpenRouter Gemma)로 재료 인식 → 사용자가 재료 확정 → 알레르기·선호도 기반 한식 레시피 추천 → 저장/메모/평점.

**두 프론트엔드 공존:**
1. Streamlit 앱(`app.py` + `backend/`) — 메인 사용처. 인증 게이트 → 4탭(Step 1: 재료 인식 / Step 2: 레시피 / 내 레시피 / 프로필).
2. 정적 웹(`web/index.html`, `web/app.js`, `web/styles.css`) — Vercel 배포. 인증 없이 단일 페이지에서 업로드 → 분석 → 레시피.

**Why:** 학습용 프로젝트(VibeCoding 시리즈). 한국어 사용자가 대상이라 모든 UI 카피는 한국어, 친근하지만 군더더기 없는 톤.

**How to apply:** 사용자 동선의 핵심은 업로드 → 재료 확정 → 레시피 추천 → 저장. 이 4개 핸드오프가 매끄러우면 80% 성공.
