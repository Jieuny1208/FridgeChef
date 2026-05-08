---
name: web/ 디자인 토큰
description: web/styles.css :root에 정의된 색상·간격·타이포 토큰 — 신규 UI 추가 시 재사용
type: project
---

**색:**
- `--color-primary: #ff6b35` (오렌지 — 액션, 강조)
- `--color-primary-dark: #e55a2b`
- `--color-secondary: #4ecdc4` (청록 — 인식된 재료, 보조 액션)
- `--color-success: #10b981`, `--color-warning: #f59e0b`, `--color-error: #ef4444`
- 배경: `linear-gradient(135deg, #fffcf2 0%, #ffecd1 100%)` (따뜻한 크림)

**간격:** xs=0.25 / sm=0.5 / md=1 / lg=1.5 / xl=2 / 2xl=3rem.

**타이포:** sm 0.875 / md 1 / lg 1.125 / xl 1.25 / 2xl 1.5 / 3xl 2rem.

**폰트:** `'Segoe UI', 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif`.

**How to apply:** 새 컴포넌트 추가 시 토큰 변수만 사용. 인라인 색·간격 금지. 강조는 primary, 부정/에러는 error 변수, 성공 토스트는 success.
