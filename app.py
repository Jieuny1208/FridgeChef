"""FridgeChef — Steps 1+2+3: image recognition, recipe generation, user profile + saved recipes.

PRDs: PRD_step1.md, PRD_step2.md, PRD_step3.md
"""
import json
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

from backend.config import Config
from backend.image_service import ImageProcessor
from backend.openrouter_client import OpenRouterClient
from backend.recipe_generator import RecipeGenerator, cache_key
from backend.auth_service import AuthError, AuthService
from backend.profile_service import ProfileService
from backend.recipe_store import RecipeStore
from backend.models import Profile, User


# ============================================================================
# Singletons (M-1)
# ============================================================================
# Without caching, every Streamlit re-render constructed brand-new service
# objects. They're cheap individually but the file-IO they trigger via
# ``_load_all`` adds up across the recipe loop in Step 2 / My Recipes.
# ``@st.cache_resource`` keeps a single instance per Streamlit session.
@st.cache_resource(show_spinner=False)
def get_auth_service() -> AuthService:
    return AuthService()


@st.cache_resource(show_spinner=False)
def get_profile_service() -> ProfileService:
    return ProfileService()


@st.cache_resource(show_spinner=False)
def get_recipe_store() -> RecipeStore:
    return RecipeStore()


@st.cache_resource(show_spinner=False)
def get_openrouter_client() -> OpenRouterClient:
    return OpenRouterClient()


@st.cache_resource(show_spinner=False)
def get_recipe_generator() -> RecipeGenerator:
    # Reuses the cached client so we don't open a second requests session.
    return RecipeGenerator(client=get_openrouter_client())


st.set_page_config(
    page_title="FridgeChef",
    page_icon="🍳",
    layout="wide",
    initial_sidebar_state="expanded",
)


DIET_OPTIONS = ["채식", "비건", "할랄", "저염", "저당"]
DIFFICULTY_OPTIONS = ["쉬움", "보통", "어려움"]
CATEGORY_OPTIONS = [
    "채소", "과일", "육류", "해산물", "유제품",
    "계란", "곡류", "소스/양념", "음료", "기타",
]


# ============================================================================
# Friendly error message helper
# ============================================================================
def _friendly_error(raw: str) -> str:
    """Translate backend/HTTP error strings into a user-facing Korean message.

    Backend error payloads like ``HTTP 429: ...`` or ``JSON 스키마 검증 실패: ...``
    are useful for logs but not for users. Convert known patterns into plain
    next-action Korean and keep the original under an expander for debugging.
    """
    if not raw:
        return "알 수 없는 오류가 발생했어요. 잠시 후 다시 시도해 주세요."
    s = str(raw)
    low = s.lower()
    if "http 429" in low or "rate" in low and "limit" in low:
        return "지금 요청이 많아 잠시만 기다려 주세요. 30초~1분 뒤에 다시 시도하면 보통 풀려요."
    if "http 401" in low or "http 403" in low or "unauthorized" in low:
        return "AI 서비스 인증에 실패했어요. 관리자에게 알려 주세요. (API 키 확인 필요)"
    if "http 5" in low or "timeout" in low or "timed out" in low:
        return "AI 서버 응답이 늦어지고 있어요. 잠시 후 다시 시도해 주세요."
    if "network" in low or "connection" in low:
        return "네트워크 연결을 확인하고 다시 시도해 주세요."
    if "json" in low and ("parse" in low or "스키마" in s):
        return "AI 응답 형식이 올바르지 않아요. 한 번 더 시도해 보시겠어요?"
    if "empty model response" in low or "empty response" in low:
        return "AI가 응답을 만들지 못했어요. 사진을 바꾸거나 잠시 후 다시 시도해 주세요."
    return "요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요."


def init_state() -> None:
    st.session_state.setdefault("user", None)            # User | None
    st.session_state.setdefault("profile", None)         # Profile | None
    st.session_state.setdefault("recognition", None)
    st.session_state.setdefault("edited_df", None)
    st.session_state.setdefault("history", [])
    st.session_state.setdefault("recipes", [])
    st.session_state.setdefault("recipe_cache", {})


# ============================================================================
# AUTH GATE
# ============================================================================
def render_auth_gate() -> None:
    st.title("🍳 FridgeChef")
    st.caption("냉장고 사진 한 장으로 지금 먹을 수 있는 한식 레시피를 추천해 드려요.")

    # First-impression onboarding: 5초 안에 "이게 뭐 하는 앱인지" 파악
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        c1.markdown("### 📷\n**1. 사진 업로드**\n냉장고 안을 찍어 올려 주세요.")
        c2.markdown("### 🤖\n**2. AI 재료 인식**\n식재료를 자동으로 골라내요.")
        c3.markdown("### 🍳\n**3. 레시피 추천**\n알레르기·취향에 맞춰 한식을 제안해요.")

    st.write("")  # spacing
    tab_login, tab_signup = st.tabs(["🔓 로그인", "🆕 회원가입"])

    with tab_login:
        # H-7: ``clear_on_submit=True`` blanks the inputs on every submit so a
        # failed login doesn't leave the password readable in the DOM, and
        # we proactively drop the password key from session_state.
        with st.form("login_form", clear_on_submit=True):
            u = st.text_input(
                "아이디",
                key="login_u",
                placeholder="가입한 아이디를 입력하세요",
                autocomplete="username",
            )
            p = st.text_input(
                "비밀번호",
                type="password",
                key="login_p",
                autocomplete="current-password",
            )
            submitted = st.form_submit_button("로그인", type="primary", use_container_width=True)
            st.caption("처음 오셨나요? 위의 ‘🆕 회원가입’ 탭에서 30초면 가입할 수 있어요.")
        if submitted:
            if not u.strip() or not p:
                st.error("아이디와 비밀번호를 모두 입력해 주세요.")
                _purge_password_state()
            else:
                try:
                    user = get_auth_service().login(u, p)
                    profile = get_profile_service().get(user.id)
                    st.session_state["user"] = user
                    st.session_state["profile"] = profile
                    st.success(f"환영해요, {profile.display_name if profile else user.username}님!")
                    _purge_password_state()
                    st.rerun()
                except AuthError as e:
                    st.error(str(e))
                finally:
                    # Always drop password material — even on success/failure paths.
                    _purge_password_state()

    with tab_signup:
        with st.form("signup_form", clear_on_submit=True):
            u = st.text_input(
                "아이디",
                key="signup_u",
                placeholder="예: jieun_kim (영문 소문자·숫자·_, 3~20자)",
                help="로그인할 때 사용해요. 가입 후에는 변경할 수 없어요.",
                autocomplete="username",
            )
            n = st.text_input(
                "표시 이름",
                key="signup_n",
                placeholder="앱에서 보일 이름 (예: 지은)",
                help="언제든 프로필에서 바꿀 수 있어요.",
            )
            p1 = st.text_input(
                "비밀번호",
                type="password",
                key="signup_p1",
                placeholder="8자 이상, 영문과 숫자를 모두 포함",
                help="비밀번호는 안전하게 암호화되어 저장돼요.",
                autocomplete="new-password",
            )
            p2 = st.text_input(
                "비밀번호 확인",
                type="password",
                key="signup_p2",
                placeholder="위와 동일하게 한 번 더",
                autocomplete="new-password",
            )
            submitted = st.form_submit_button("가입하고 시작하기", type="primary", use_container_width=True)
        if submitted:
            # Inline, friendly validation — show the first thing to fix
            if not u.strip():
                st.error("아이디를 입력해 주세요.")
            elif not n.strip():
                st.error("표시 이름을 입력해 주세요. (예: 지은)")
            elif not p1:
                st.error("비밀번호를 입력해 주세요.")
            elif p1 != p2:
                st.error("두 비밀번호가 달라요. 다시 한 번 확인해 주세요.")
            else:
                try:
                    user, profile = get_auth_service().signup(u, p1, n)
                    st.session_state["user"] = user
                    st.session_state["profile"] = profile
                    st.success("가입이 완료됐어요! 바로 시작할 수 있어요.")
                    _purge_password_state()
                    st.rerun()
                except AuthError as e:
                    st.error(str(e))
                finally:
                    _purge_password_state()


def _purge_password_state() -> None:
    """H-7: scrub any stored password values from st.session_state."""
    for key in ("login_p", "signup_p1", "signup_p2"):
        if key in st.session_state:
            try:
                del st.session_state[key]
            except Exception:
                pass


# ============================================================================
# SIDEBAR
# ============================================================================
def render_sidebar() -> None:
    user: User = st.session_state["user"]
    profile: Profile = st.session_state["profile"]
    with st.sidebar:
        st.subheader(f"👤 {profile.display_name if profile else user.username}")
        st.caption(f"@{user.username}")

        # Two-step logout confirmation — destructive action shouldn't be a
        # single click, and we want to make explicit what gets cleared.
        if st.session_state.get("_confirm_logout"):
            st.warning("로그아웃하면 이번 세션의 인식 결과와 추천 레시피가 사라져요. 저장한 ‘내 레시피’는 그대로 남아요.")
            cols = st.columns(2)
            if cols[0].button("로그아웃", type="primary", use_container_width=True, key="logout_yes"):
                # H-7 / M-2: scrub all session state on logout so the next user
                # never sees the previous user's recognition or recipes.
                for k in ("user", "profile", "recipes", "recipe_cache",
                          "recognition", "edited_df", "history",
                          "_confirm_logout"):
                    if k in st.session_state:
                        st.session_state[k] = None if k in ("user", "profile") else (
                            [] if k in ("recipes", "history") else (
                                {} if k == "recipe_cache" else (
                                    False if k == "_confirm_logout" else None
                                )
                            )
                        )
                st.rerun()
            if cols[1].button("취소", use_container_width=True, key="logout_no"):
                st.session_state["_confirm_logout"] = False
                st.rerun()
        else:
            if st.button("로그아웃", use_container_width=True):
                st.session_state["_confirm_logout"] = True
                st.rerun()

        st.divider()
        with st.expander("🔧 시스템 정보", expanded=False):
            st.caption(
                f"인식 모델: `{Config.IMAGE_RECOGNITION_MODEL}`\n\n"
                f"레시피 모델: `{Config.RECIPE_GENERATION_MODEL}`"
            )
            if st.button("AI 서비스 연결 확인", use_container_width=True):
                with st.spinner("연결을 확인하고 있어요…"):
                    ok = get_openrouter_client().test_connection()
                if ok:
                    st.success("AI 서비스에 정상적으로 연결돼요.")
                else:
                    st.error(
                        "AI 서비스에 연결할 수 없어요. 잠시 후 다시 시도해 주세요. "
                        "계속 실패하면 관리자에게 알려 주세요."
                    )

        st.divider()
        st.markdown("##### 📜 최근 인식")
        if st.session_state["history"]:
            for h in st.session_state["history"][-5:][::-1]:
                st.caption(f"• {h['time']} — {h['count']}개 재료")
        else:
            st.caption("아직 인식 기록이 없어요. ‘Step 1’에서 사진을 올려 보세요.")


# ============================================================================
# STEP 1
# ============================================================================
def _render_stepper(active: int) -> None:
    """Top-of-page progress indicator for the 3-step flow.

    Streamlit's tabs already show step names but don't communicate "where am I"
    once the user is inside a step. A simple stepper reduces the cognitive load
    of "wait, did Step 1 finish?".
    """
    labels = ["① 재료 인식", "② 레시피 생성", "③ 저장·관리"]
    parts = []
    for i, label in enumerate(labels, 1):
        if i < active:
            parts.append(f"<span style='color:#10b981'>✓ {label}</span>")
        elif i == active:
            parts.append(f"<b style='color:#ff6b35'>{label}</b>")
        else:
            parts.append(f"<span style='color:#bbb'>{label}</span>")
    st.markdown(
        "<div style='font-size:0.95rem; margin-bottom:8px'>"
        + "  ›  ".join(parts)
        + "</div>",
        unsafe_allow_html=True,
    )


def render_step1() -> None:
    _render_stepper(1)
    left, right = st.columns([1, 1])
    with left:
        st.header("📷 냉장고 사진 올리기")
        st.caption("냉장고 안이 잘 보이도록 정면에서 찍은 사진이 인식이 잘 돼요. (JPG · PNG · WEBP)")
        f = st.file_uploader(
            "사진 파일 선택",
            type=sorted(Config.ALLOWED_EXTENSIONS),
            accept_multiple_files=False,
            key="uploader_step1",
            label_visibility="collapsed",
        )
        uploaded = None
        if f is not None:
            ok, err = ImageProcessor.validate_image(f)
            if not ok:
                st.error(err)
                st.caption("💡 다른 사진을 선택하거나, 파일 형식·크기를 확인해 주세요.")
            else:
                st.image(f, caption="업로드한 사진", use_container_width=True)
                uploaded = f

        if uploaded is None:
            with st.expander("📚 사진을 잘 찍는 팁", expanded=False):
                st.markdown(
                    "- 냉장고 문을 활짝 열고 **정면**에서 찍어 주세요.\n"
                    "- 조명을 켜서 **재료가 또렷하게** 보이게 해 주세요.\n"
                    "- 한 번에 너무 많은 칸을 담기보다 **칸별로 찍는 편**이 인식이 더 정확해요.\n"
                    "- 포장지가 보이면 글자가 인식에 도움이 돼요."
                )

        if uploaded is not None and st.button(
            "재료 인식 시작하기", type="primary", use_container_width=True,
            help="AI가 사진 속 식재료를 찾아 목록으로 만들어요. (보통 5~15초)"
        ):
            run_recognition(uploaded)

    with right:
        result = st.session_state["recognition"]
        if result is None:
            # Empty state — make next action obvious
            with st.container(border=True):
                st.markdown("#### 👋 시작해 볼까요?")
                st.write(
                    "왼쪽에서 냉장고 사진을 업로드한 뒤 **‘재료 인식 시작하기’** 버튼을 누르면, "
                    "AI가 사진 속 재료를 자동으로 골라 줘요."
                )
                st.caption("인식이 끝난 뒤 재료를 자유롭게 추가·삭제할 수 있으니 부담 없이 시작해 보세요.")
            return
        edited = render_editor(result)
        if result.get("status") == "success" and len(edited):
            render_step1_export(edited, result)


def run_recognition(uploaded_file) -> None:
    with st.status("재료를 인식하고 있어요…", expanded=True) as status:
        status.update(label="1/2 사진을 정리하는 중…")
        b64 = ImageProcessor.process_image(uploaded_file)
        if not b64:
            status.update(label="사진을 처리하지 못했어요", state="error")
            st.error(
                "사진을 처리하는 중에 문제가 생겼어요. "
                "다른 사진으로 시도해 보거나, 파일이 손상되지 않았는지 확인해 주세요."
            )
            return
        status.update(label="2/2 AI가 재료를 찾고 있어요… (요청이 많으면 자동으로 다시 시도해요)")
        result = get_openrouter_client().recognize_ingredients(b64)
        if result.get("status") == "success":
            n = result["total_items"]
            if n == 0:
                status.update(label="재료를 찾지 못했어요", state="error")
            else:
                status.update(label=f"완료! {n}개의 재료를 찾았어요", state="complete")
        else:
            status.update(label="인식에 실패했어요", state="error")
    st.session_state["recognition"] = result
    st.session_state["edited_df"] = None
    if result.get("status") == "success":
        st.session_state["history"].append(
            {"time": datetime.now().strftime("%H:%M:%S"), "count": result["total_items"]}
        )


def render_editor(result: dict) -> pd.DataFrame:
    st.header("📋 인식된 재료")
    st.caption(
        "AI가 찾은 재료예요. **잘못 인식된 항목은 체크를 해제**하거나 행을 삭제하고, "
        "**빠진 재료는 표 아래 ‘+’ 버튼으로 추가**할 수 있어요."
    )
    if result.get("status") != "success":
        # User-facing friendly text + raw tucked under expander
        raw_err = result.get("error") or ""
        st.error(_friendly_error(raw_err))
        st.markdown("**다음 중 한 가지를 시도해 보세요.**")
        st.markdown(
            "- 잠시 후 ‘재료 인식 시작하기’를 다시 눌러 보세요.\n"
            "- 더 밝거나 또렷한 사진으로 바꿔 보세요.\n"
            "- 사이드바의 **‘AI 서비스 연결 확인’**으로 연결 상태를 확인해 보세요."
        )
        with st.expander("자세한 오류 정보 (관리자 문의용)"):
            st.code(raw_err or "(없음)")
            if result.get("raw_text"):
                st.text(result["raw_text"])
        return pd.DataFrame(columns=["선택", "재료", "카테고리", "신뢰도"])
    if not result["ingredients"]:
        st.warning("이 사진에서 식재료를 찾지 못했어요.")
        st.markdown(
            "**이렇게 시도해 보세요.**\n"
            "- 냉장고 안이 더 잘 보이는 사진으로 바꿔 보세요.\n"
            "- 아래 표에서 **‘+’**를 눌러 재료를 직접 입력할 수도 있어요."
        )
        # Still return an empty editable frame so the user can add manually
        empty = pd.DataFrame(columns=["선택", "재료", "카테고리", "신뢰도"])
        edited = st.data_editor(
            empty, num_rows="dynamic", use_container_width=True,
            column_config={
                "선택": st.column_config.CheckboxColumn("사용", default=True),
                "재료": st.column_config.TextColumn("재료", required=True),
                "카테고리": st.column_config.SelectboxColumn(
                    "카테고리", options=CATEGORY_OPTIONS, required=True
                ),
                "신뢰도": st.column_config.NumberColumn(
                    "신뢰도", min_value=0.0, max_value=1.0, step=0.01, format="%.2f"
                ),
            },
            key="editor",
        )
        st.session_state["edited_df"] = edited
        return edited

    base = pd.DataFrame(
        [{"선택": True, "재료": it["name"], "카테고리": it["category"],
          "신뢰도": round(it["confidence"], 2)} for it in result["ingredients"]]
    )
    df = st.session_state["edited_df"] if st.session_state["edited_df"] is not None else base
    edited = st.data_editor(
        df, num_rows="dynamic", use_container_width=True,
        column_config={
            "선택": st.column_config.CheckboxColumn(
                "사용", default=True,
                help="레시피 추천에 이 재료를 사용할지 선택하세요.",
            ),
            "재료": st.column_config.TextColumn(
                "재료", required=True,
                help="잘못 인식된 이름을 직접 수정할 수 있어요.",
            ),
            "카테고리": st.column_config.SelectboxColumn(
                "카테고리", options=CATEGORY_OPTIONS, required=True
            ),
            "신뢰도": st.column_config.NumberColumn(
                "AI 확신도",
                min_value=0.0, max_value=1.0, step=0.01, format="%.2f",
                help="AI가 이 재료를 얼마나 자신 있게 인식했는지 (0~1).",
            ),
        },
        key="editor",
    )
    st.session_state["edited_df"] = edited

    selected = edited[edited["선택"] == True]  # noqa: E712
    c1, c2, c3 = st.columns(3)
    c1.metric("총 인식", f"{result['total_items']}개")
    c2.metric("사용할 재료", f"{len(selected)}개")
    c3.metric("카테고리", f"{selected['카테고리'].nunique() if len(selected) else 0}종류")

    if len(selected) == 0:
        st.warning("최소 1개 이상의 재료를 선택해야 레시피를 추천받을 수 있어요.")
    return edited


def render_step1_export(edited: pd.DataFrame, result: dict) -> None:
    st.divider()
    payload = {
        "ingredients": selected_ingredients(),
        "model": Config.IMAGE_RECOGNITION_MODEL,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    n = len(payload["ingredients"])
    if n > 0:
        st.success(
            f"좋아요! **{n}개의 재료**가 준비됐어요. "
            "위쪽 탭의 **‘🍳 Step 2: 레시피 생성’**으로 이동해 레시피를 추천받아 보세요."
        )
    c1, c2 = st.columns([1, 2])
    with c1:
        st.download_button(
            "재료 목록 내려받기 (JSON)",
            data=json.dumps(payload, ensure_ascii=False, indent=2),
            file_name=f"ingredients_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json", use_container_width=True,
            help="선택한 재료를 JSON 파일로 저장해요. 백업이나 공유에 활용하세요.",
        )
    with st.expander("자세한 AI 응답 보기 (선택)"):
        st.text(result.get("raw_text", "") or "(없음)")


def selected_ingredients() -> List[Dict]:
    df = st.session_state.get("edited_df")
    if df is None or df.empty:
        return []
    sel = df[df["선택"] == True]  # noqa: E712
    return [
        {"name": str(r["재료"]).strip(), "category": str(r["카테고리"]).strip(),
         "confidence": float(r["신뢰도"])}
        for _, r in sel.iterrows() if str(r["재료"]).strip()
    ]


# ============================================================================
# STEP 2
# ============================================================================
def render_step2() -> None:
    _render_stepper(2)
    profile: Profile = st.session_state["profile"]
    ingredients = selected_ingredients()
    left, right = st.columns([1, 2])

    with left:
        st.header("⚙️ 레시피 옵션")
        if not ingredients:
            st.warning(
                "재료가 아직 준비되지 않았어요. "
                "**‘📷 Step 1: 재료 인식’** 탭에서 사진을 올리고 재료를 골라 주세요."
            )
            return

        # Selected ingredients chip-style preview at the top — 가장 중요한 정보가
        # 옵션 위에 보여야 "이 재료들로 레시피를 받는다"가 즉시 인식됨.
        with st.container(border=True):
            st.markdown(f"**선택한 재료 {len(ingredients)}개**")
            st.caption("· ".join(it["name"] for it in ingredients))

        st.markdown("##### 분량과 시간")
        # Prefill from profile (PRD §6.3)
        servings = st.slider("인분", 1, 6, profile.default_servings)
        max_minutes = st.slider("최대 조리 시간 (분)", 10, 120, profile.default_max_minutes, step=5)
        difficulty = st.selectbox(
            "난이도", DIFFICULTY_OPTIONS,
            index=DIFFICULTY_OPTIONS.index(profile.default_difficulty),
            help="‘쉬움’은 초보자도 따라 할 수 있는 단순 레시피를 우선해요.",
        )

        st.markdown("##### 식단·알레르기")
        diet = st.multiselect(
            "식단 제한", DIET_OPTIONS, default=list(profile.diet),
            help="여러 항목을 함께 선택할 수 있어요.",
        )

        # Allergen UX: 프로필 알레르기를 명확히 보여주고, 추가만 받는 형태로 단순화
        if profile.allergens:
            st.info(
                "🛡 프로필에 등록된 알레르기는 자동으로 차단돼요: "
                f"**{', '.join(profile.allergens)}**"
            )
        allergens_str = st.text_input(
            "이번에만 추가로 피할 재료 (쉼표로 구분)",
            value="",
            placeholder="예: 새우, 땅콩",
            help="프로필 알레르기에 더해, 이번 추천에서만 빼고 싶은 재료가 있다면 입력하세요.",
        )
        # Merge profile allergens with input
        extra = [a.strip() for a in allergens_str.split(",") if a.strip()]
        allergens = sorted(set(extra) | set(profile.allergens))

        if not profile.allergens and not extra:
            st.caption(
                "💡 알레르기가 있다면 **‘👤 프로필’** 탭에 등록해 두면, "
                "다음부터 자동으로 빼 줘요."
            )

        st.markdown("##### 추천 결과")
        num_recipes = st.slider("받을 레시피 개수", 1, 5, 3)

        opt = dict(
            servings=servings, max_minutes=max_minutes, difficulty=difficulty,
            diet=diet, allergens=allergens, num_recipes=num_recipes,
        )

        st.write("")  # spacing
        gen_clicked = st.button(
            "🍳 레시피 추천받기", type="primary", use_container_width=True,
            help="옵션을 바탕으로 새 레시피를 추천해요. (보통 10~20초)"
        )
        c1, c2 = st.columns(2)
        more_clicked = c1.button(
            "다른 레시피 더 보기", use_container_width=True,
            disabled=not st.session_state["recipes"],
            help="기존 결과는 유지하고, 중복되지 않는 새 레시피를 추가로 받아요.",
        )
        reset_clicked = c2.button(
            "결과 비우기", use_container_width=True,
            disabled=not st.session_state["recipes"],
        )
        if reset_clicked:
            st.session_state["recipes"] = []
            st.rerun()

    with right:
        st.header("🍳 추천 레시피")
        if gen_clicked:
            st.session_state["recipes"] = []
            run_recipe_generation(ingredients, opt, append=False)
        elif more_clicked:
            run_recipe_generation(ingredients, opt, append=True)

        recipes = st.session_state["recipes"]
        if not recipes:
            with st.container(border=True):
                st.markdown("#### 🍽 어떤 요리를 만들어 드릴까요?")
                st.write(
                    "왼쪽에서 분량·시간·난이도를 골라 **‘🍳 레시피 추천받기’**를 누르면, "
                    "선택한 재료로 만들 수 있는 한식 레시피를 추천해 드려요."
                )
                st.caption("결과가 마음에 들지 않으면 ‘다른 레시피 더 보기’로 다른 옵션을 받을 수 있어요.")
            return
        # M-1: pull saved-ids once instead of querying RecipeStore inside the
        # loop (the legacy code did one ``is_saved`` call per card, each of
        # which re-read saved_recipes.json from disk).
        user: User = st.session_state["user"]
        saved_ids = {sr.id for sr in get_recipe_store().list_for_user(user.id)}
        st.caption(f"총 {len(recipes)}개의 레시피를 준비했어요.")
        for i, r in enumerate(recipes, 1):
            render_recipe_card(i, r, savable=True, saved_ids=saved_ids)
        render_recipes_export(recipes)


def run_recipe_generation(ingredients: List[Dict], opt: Dict, *, append: bool) -> None:
    avoid = [r["title"] for r in st.session_state["recipes"]] if append else None
    key = cache_key(ingredients, **opt, avoid_titles=avoid)
    cache = st.session_state["recipe_cache"]

    with st.status("맛있는 레시피를 준비하고 있어요…", expanded=True) as status:
        if key in cache:
            status.update(label="이전에 받은 결과를 다시 보여드려요.", state="complete")
            new_recipes = cache[key]
        else:
            status.update(label="AI에게 레시피를 부탁하는 중…")
            result = get_recipe_generator().generate(ingredients, **opt, avoid_titles=avoid)
            if result["status"] != "success":
                status.update(label="레시피를 받지 못했어요", state="error")
                raw_err = result.get("error", "")
                st.error(_friendly_error(raw_err))
                st.markdown(
                    "**다시 시도해 보세요.**\n"
                    "- 같은 옵션으로 한 번 더 ‘🍳 레시피 추천받기’를 눌러 보세요.\n"
                    "- 재료가 너무 적다면 Step 1에서 몇 가지를 더 추가해 보세요.\n"
                    "- 조리 시간이나 난이도 옵션을 바꿔 보세요."
                )
                with st.expander("자세한 오류 정보 (관리자 문의용)"):
                    st.code(raw_err or "(없음)")
                    if result.get("raw_text"):
                        st.text(result["raw_text"])
                return
            new_recipes = result["recipes"]
            cache[key] = new_recipes
            n = len(new_recipes)
            status.update(
                label=f"{n}개의 레시피를 추천해 드려요!" if n else "조건에 맞는 레시피를 찾지 못했어요.",
                state="complete" if n else "error",
            )

    existing = {r["id"] for r in st.session_state["recipes"]}
    appended = [r for r in new_recipes if r["id"] not in existing]
    if append:
        st.session_state["recipes"].extend(appended)
        if not appended and new_recipes:
            st.info("새로운 레시피가 더 없어요. 옵션을 바꿔 다시 시도해 보세요.")
    else:
        st.session_state["recipes"] = appended
        if not appended:
            st.warning(
                "조건에 맞는 레시피를 찾지 못했어요. "
                "재료를 더 추가하거나 식단·알레르기 조건을 완화해 보세요."
            )


# ============================================================================
# RECIPE CARD (shared between Step 2 and My Recipes)
# ============================================================================
def render_recipe_card(
    idx: int,
    r: Dict,
    *,
    savable: bool,
    saved_ids: Optional[set] = None,
) -> None:
    user: User = st.session_state["user"]
    store = get_recipe_store()
    rid = r.get("id") or "(no-id)"
    # M-1: prefer the precomputed set when the caller supplied one — falls
    # back to ``is_saved`` for backwards compatibility.
    if savable:
        already = (rid in saved_ids) if saved_ids is not None else store.is_saved(user.id, rid)
    else:
        already = False

    with st.container(border=True):
        # Visual hierarchy: 제목 + 한 줄 설명을 가장 크게, 메타데이터는 보조
        st.subheader(f"{idx}. {r['title']}")
        if r.get("summary"):
            st.write(r["summary"])

        # Metadata row — chip-style, 일관된 위치
        b1, b2, b3, b4 = st.columns([1, 1, 1, 2])
        b1.markdown(f"⏱ **{r['estimated_minutes']}분**")
        b2.markdown(f"🎚 **{r['difficulty']}**")
        b3.markdown(f"🍽 **{r['servings']}인분**")
        if savable:
            # 저장됨 상태가 비활성 회색이 아니라 명확한 성공 컬러로 보이도록 라벨 변경
            label = "✅ 내 레시피에 저장됨" if already else "⭐ 내 레시피에 저장"
            # 위젯 키는 rerun 사이에 안정적이어야 클릭이 감지됨. idx로 위치 유일성
            # 보장. rid가 비어 있어도 (rid, idx) 조합으로 한 화면 내에서 충돌 없음.
            btn_key = f"save_{rid}_{idx}"
            if b4.button(
                label, key=btn_key, disabled=already,
                use_container_width=True,
                help="저장하면 ‘⭐ 내 레시피’ 탭에서 언제든 다시 볼 수 있어요." if not already else "이미 저장된 레시피예요.",
            ):
                store.save(user.id, r)
                st.toast(f"‘{r['title']}’를 내 레시피에 저장했어요.", icon="⭐")
                st.rerun()

        with st.expander("📖 자세한 레시피 보기 (재료·조리법)"):
            cols = st.columns(2)
            with cols[0]:
                st.markdown("**🥬 사용할 재료**")
                for ing in r.get("ingredients_used", []):
                    mark = "✅" if ing.get("from_fridge", True) else "▫️"
                    st.markdown(f"- {mark} {ing['name']} — {ing['amount']}")
                if r.get("extra_ingredients"):
                    st.markdown("**🧂 추가로 필요한 양념·재료**")
                    for ing in r["extra_ingredients"]:
                        st.markdown(f"- {ing['name']} — {ing['amount']}")
                st.caption("✅ 냉장고에 있는 재료 · ▫️ 새로 사야 하는 재료")
            with cols[1]:
                st.markdown("**👨‍🍳 조리 순서**")
                for n, step in enumerate(r.get("steps", []), 1):
                    st.markdown(f"{n}. {step}")
                if r.get("tips"):
                    st.markdown("**💡 요리 팁**")
                    for tip in r["tips"]:
                        st.markdown(f"- {tip}")
        st.caption(f"레시피 ID: `{rid}`")


def render_recipes_export(recipes: List[Dict]) -> None:
    st.divider()
    payload = {"recipes": recipes, "model": Config.RECIPE_GENERATION_MODEL,
               "created_at": datetime.now().isoformat(timespec="seconds")}
    st.download_button(
        "추천 레시피 내려받기 (JSON)",
        data=json.dumps(payload, ensure_ascii=False, indent=2),
        file_name=f"recipes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        mime="application/json", use_container_width=True,
        help="추천받은 레시피를 파일로 저장해요.",
    )


# ============================================================================
# STEP 3 — My Recipes
# ============================================================================
def render_my_recipes() -> None:
    _render_stepper(3)
    user: User = st.session_state["user"]
    store = get_recipe_store()

    st.header("⭐ 내 레시피")
    st.caption("마음에 든 레시피를 저장해 두고, 메모·평점·태그로 정리할 수 있어요.")

    c1, c2 = st.columns([3, 1])
    q = c1.text_input(
        "검색", key="search_q",
        placeholder="제목·재료·태그로 검색 (예: 계란, 볶음)",
        label_visibility="collapsed",
    )
    sort = c2.selectbox(
        "정렬 기준", ["recent", "rating", "title"],
        format_func={"recent": "최신순", "rating": "평점순", "title": "제목순"}.get,
        label_visibility="collapsed",
    )

    items = store.list_for_user(user.id, query=q, sort=sort)

    if not items:
        if q:
            st.info(f"‘{q}’에 해당하는 레시피가 없어요. 다른 검색어로 시도해 보세요.")
        else:
            with st.container(border=True):
                st.markdown("#### 📭 아직 저장한 레시피가 없어요")
                st.write(
                    "**‘🍳 Step 2: 레시피 생성’**에서 마음에 드는 레시피를 만나면, "
                    "**‘⭐ 내 레시피에 저장’** 버튼을 눌러 보세요. "
                    "여기에 모아 두고 평점·메모를 남길 수 있어요."
                )
        return

    st.caption(f"저장한 레시피 {len(items)}개")

    for i, sr in enumerate(items, 1):
        with st.container(border=True):
            top = st.columns([4, 1])
            top[0].subheader(f"{i}. {sr.recipe.get('title', '(제목 없음)')}")
            top[1].caption(f"저장일 {sr.saved_at.strftime('%Y-%m-%d')}")
            if sr.recipe.get("summary"):
                st.write(sr.recipe["summary"])

            row = st.columns([1, 1, 1, 2])
            row[0].markdown(f"⏱ **{sr.recipe.get('estimated_minutes', '-')}분**")
            row[1].markdown(f"🎚 **{sr.recipe.get('difficulty', '-')}**")
            row[2].markdown(f"⭐ **{sr.rating or '–'}**" + (" / 5" if sr.rating else ""))

            # Two-step delete confirmation — destructive action을 한 번 더 묻기
            confirm_key = f"_confirm_del_{sr.id}_{i}"
            if st.session_state.get(confirm_key):
                row[3].caption("정말 삭제할까요?")
                d1, d2 = row[3].columns(2)
                if d1.button("삭제", type="primary", key=f"del_yes_{sr.id}_{i}", use_container_width=True):
                    title = sr.recipe.get("title", "(제목 없음)")
                    store.delete(user.id, sr.id)
                    st.session_state[confirm_key] = False
                    st.toast(f"‘{title}’를 삭제했어요.", icon="🗑")
                    st.rerun()
                if d2.button("취소", key=f"del_no_{sr.id}_{i}", use_container_width=True):
                    st.session_state[confirm_key] = False
                    st.rerun()
            else:
                if row[3].button("🗑 삭제", key=f"del_{sr.id}_{i}", use_container_width=True):
                    st.session_state[confirm_key] = True
                    st.rerun()

            # Show note preview if exists — 메모는 자주 보고 싶을 정보이므로 요약 노출
            if sr.note:
                st.caption(f"📝 {sr.note[:80]}{'…' if len(sr.note) > 80 else ''}")
            if sr.tags:
                st.caption("🏷 " + " · ".join(f"#{t}" for t in sr.tags))

            with st.expander("✏️ 평점·메모·태그 편집"):
                with st.form(f"edit_{sr.id}_{i}"):
                    rating = st.slider(
                        "평점 (0이면 평점 없음)", 0, 5, sr.rating or 0,
                    )
                    note = st.text_area(
                        "메모", value=sr.note,
                        placeholder="이 레시피에 대한 후기, 다음에 시도할 변형 등을 자유롭게 적어 보세요.",
                    )
                    tags_str = st.text_input(
                        "태그 (쉼표로 구분)",
                        value=", ".join(sr.tags),
                        placeholder="예: 점심, 도시락, 매운맛",
                    )
                    if st.form_submit_button("변경 사항 저장", type="primary"):
                        tags = [t.strip() for t in tags_str.split(",") if t.strip()]
                        store.update(
                            user.id, sr.id, note=note,
                            rating=rating if rating > 0 else None, tags=tags,
                        )
                        st.toast("수정 사항을 저장했어요.", icon="✅")
                        st.rerun()

            with st.expander("📖 자세한 레시피 보기"):
                cols = st.columns(2)
                with cols[0]:
                    st.markdown("**🥬 사용할 재료**")
                    for ing in sr.recipe.get("ingredients_used", []):
                        mark = "✅" if ing.get("from_fridge", True) else "▫️"
                        st.markdown(f"- {mark} {ing['name']} — {ing['amount']}")
                    if sr.recipe.get("extra_ingredients"):
                        st.markdown("**🧂 추가 양념·재료**")
                        for ing in sr.recipe["extra_ingredients"]:
                            st.markdown(f"- {ing['name']} — {ing['amount']}")
                with cols[1]:
                    st.markdown("**👨‍🍳 조리 순서**")
                    for n, step in enumerate(sr.recipe.get("steps", []), 1):
                        st.markdown(f"{n}. {step}")


# ============================================================================
# STEP 3 — Profile
# ============================================================================
def render_profile() -> None:
    user: User = st.session_state["user"]
    profile: Profile = st.session_state["profile"]

    st.header("👤 프로필")
    st.caption(f"아이디: `{user.username}` · 가입일: {user.created_at.strftime('%Y년 %m월 %d일')}")

    st.write(
        "여기서 설정한 내용은 **‘🍳 Step 2: 레시피 생성’**의 옵션 기본값으로 자동 적용돼요. "
        "매번 설정할 필요 없이, 한 번 정해 두면 편해요."
    )

    with st.form("profile_form"):
        st.markdown("##### 기본 정보")
        display_name = st.text_input(
            "표시 이름", value=profile.display_name,
            help="앱 안에서 보일 이름이에요.",
        )

        st.markdown("##### 식단·알레르기")
        diet = st.multiselect(
            "식단 제한", DIET_OPTIONS, default=list(profile.diet),
            help="해당하는 항목을 선택하면 추천 레시피에 반영돼요.",
        )
        allergens_str = st.text_area(
            "알레르기 재료 (쉼표로 구분)",
            value=", ".join(profile.allergens),
            placeholder="예: 계란, 새우, 땅콩",
            help="여기에 등록한 재료는 모든 추천에서 자동으로 빠져요. 나중에도 언제든 수정할 수 있어요.",
        )

        st.markdown("##### 레시피 옵션 기본값")
        c1, c2, c3 = st.columns(3)
        servings = c1.number_input(
            "기본 인분", 1, 12, profile.default_servings,
            help="평소 몇 인분을 만드는지 알려 주시면 매번 설정할 필요가 없어요.",
        )
        max_minutes = c2.number_input(
            "기본 조리 시간 (분)", 10, 240, profile.default_max_minutes, step=5,
            help="평소 가능한 최대 조리 시간",
        )
        difficulty = c3.selectbox(
            "기본 난이도", DIFFICULTY_OPTIONS,
            index=DIFFICULTY_OPTIONS.index(profile.default_difficulty),
        )
        submitted = st.form_submit_button("프로필 저장", type="primary")

    if submitted:
        if not display_name.strip():
            st.error("표시 이름은 비워 둘 수 없어요.")
            return
        allergens = [a.strip() for a in allergens_str.split(",") if a.strip()]
        updated = get_profile_service().update(
            user.id,
            display_name=display_name.strip(),
            diet=diet, allergens=allergens,
            default_servings=int(servings),
            default_max_minutes=int(max_minutes),
            default_difficulty=difficulty,
        )
        st.session_state["profile"] = updated
        st.success("프로필을 저장했어요. 다음 추천부터 바로 반영돼요.")


# ============================================================================
# MAIN
# ============================================================================
def main() -> None:
    init_state()
    try:
        Config.validate()
    except ValueError as e:
        st.error(f"설정 오류: {e}")
        st.stop()

    if st.session_state["user"] is None or st.session_state["profile"] is None:
        render_auth_gate()
        return

    st.title("🍳 FridgeChef")
    st.caption("냉장고 사진 한 장으로 한식 레시피를 받아 보세요.")
    render_sidebar()

    tab1, tab2, tab3, tab4 = st.tabs([
        "📷 Step 1: 재료 인식",
        "🍳 Step 2: 레시피 생성",
        "⭐ 내 레시피",
        "👤 프로필",
    ])
    with tab1: render_step1()
    with tab2: render_step2()
    with tab3: render_my_recipes()
    with tab4: render_profile()

    st.divider()
    st.caption(f"FridgeChef v{Config.APP_VERSION}")


if __name__ == "__main__":
    main()
