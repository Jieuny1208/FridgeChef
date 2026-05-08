/**
 * 냉장고를 부탁해 프론트엔드
 */

class FridgeRecipeApp {
    constructor() {
        this.currentImage = null;
        this.currentRecipe = null;
        this.recognizedIngredients = [];
        this.init();
    }

    init() {
        this.initSettingsModal();
        this.initImageUpload();
        this.initIngredientRecognition();
        this.initRecipeGeneration();
        this.updateUI();
    }

    /**
     * 설정 모달 초기화
     */
    initSettingsModal() {
        const settingsBtn = document.getElementById('settingsBtn');
        const settingsModal = document.getElementById('settingsModal');
        const closeSettingsBtn = document.getElementById('closeSettingsBtn');
        const cancelSettingsBtn = document.getElementById('cancelSettingsBtn');
        const saveApiKeyBtn = document.getElementById('saveApiKeyBtn');
        const apiKeyInput = document.getElementById('apiKeyInput');
        const apiKeyStatus = document.getElementById('apiKeyStatus');
        const modalBackdrop = settingsModal?.querySelector('.modal-backdrop');

        // 저장된 API 키 불러오기
        const savedApiKey = localStorage.getItem('openrouter_api_key');
        if (savedApiKey) {
            apiKeyInput.value = savedApiKey;
        }

        const openModal = () => {
            settingsModal?.classList.remove('hidden');
            document.body.style.overflow = 'hidden';
        };

        const closeModal = () => {
            settingsModal?.classList.add('hidden');
            document.body.style.overflow = '';
            apiKeyStatus?.classList.add('hidden');
        };

        settingsBtn?.addEventListener('click', openModal);
        closeSettingsBtn?.addEventListener('click', closeModal);
        cancelSettingsBtn?.addEventListener('click', closeModal);
        modalBackdrop?.addEventListener('click', closeModal);

        // ESC to close — standard keyboard expectation for modals (WCAG 2.1.2)
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !settingsModal?.classList.contains('hidden')) {
                closeModal();
            }
        });

        saveApiKeyBtn?.addEventListener('click', () => {
            const apiKey = apiKeyInput.value.trim();

            if (!apiKey) {
                apiKeyStatus.textContent = 'API 키를 입력해 주세요.';
                apiKeyStatus.style.color = '#ef4444';
                apiKeyStatus.classList.remove('hidden');
                return;
            }

            if (!apiKey.startsWith('sk-or-v1-')) {
                apiKeyStatus.textContent = 'OpenRouter API 키 형식이 아닌 것 같아요. (sk-or-v1- 으로 시작해야 해요)';
                apiKeyStatus.style.color = '#ef4444';
                apiKeyStatus.classList.remove('hidden');
                return;
            }

            window.fridgeRecipeBackend.setApiKey(apiKey);
            apiKeyStatus.textContent = '✅ API 키를 저장했어요. 잠시 후 창을 닫을게요.';
            apiKeyStatus.style.color = '#10b981';
            apiKeyStatus.classList.remove('hidden');

            setTimeout(() => {
                closeModal();
            }, 1500);
        });

        apiKeyInput?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                saveApiKeyBtn?.click();
            }
        });
    }

    /**
     * 이미지 업로드 초기화
     */
    initImageUpload() {
        const uploadArea = document.getElementById('uploadArea');
        const imageInput = document.getElementById('imageInput');
        const selectImageBtn = document.getElementById('selectImageBtn');
        const imagePreview = document.getElementById('imagePreview');
        const previewImage = document.getElementById('previewImage');
        const removeImageBtn = document.getElementById('removeImageBtn');
        const ingredientsText = document.getElementById('ingredientsText');
        const generateRecipeBtn = document.getElementById('generateRecipeBtn');

        // 파일 선택 버튼
        selectImageBtn?.addEventListener('click', () => {
            imageInput?.click();
        });

        // 샘플 이미지 버튼들
        document.querySelectorAll('.sample-image-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const sampleName = btn.dataset.sample;
                this.loadSampleImage(sampleName);
            });
        });

        // 파일 선택 시
        imageInput?.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) {
                this.handleImageFile(file);
            }
        });

        // 드래그 앤 드롭
        uploadArea?.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.style.borderColor = '#ff6b35';
        });

        uploadArea?.addEventListener('dragleave', () => {
            uploadArea.style.borderColor = '#ddd';
        });

        uploadArea?.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.style.borderColor = '#ddd';
            const file = e.dataTransfer.files[0];
            if (file && file.type.startsWith('image/')) {
                this.handleImageFile(file);
            }
        });

        // 이미지 제거
        removeImageBtn?.addEventListener('click', () => {
            this.currentImage = null;
            this.recognizedIngredients = [];
            imageInput.value = '';
            document.querySelector('.upload-placeholder')?.classList.remove('hidden');
            imagePreview?.classList.add('hidden');
            document.getElementById('recognizedIngredientsSection')?.classList.add('hidden');
            this.updateGenerateButton();
        });

        // 재료 입력 시
        ingredientsText?.addEventListener('input', () => {
            this.updateGenerateButton();
        });
    }

    /**
     * 이미지 최적화 (리사이징 및 품질 조정)
     */
    async optimizeImage(imageBase64, maxWidth = 1024, maxHeight = 1024, quality = 0.85) {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.onload = () => {
                const canvas = document.createElement('canvas');
                let width = img.width;
                let height = img.height;

                // 비율 유지하면서 리사이징
                if (width > maxWidth || height > maxHeight) {
                    const ratio = Math.min(maxWidth / width, maxHeight / height);
                    width = Math.floor(width * ratio);
                    height = Math.floor(height * ratio);
                }

                canvas.width = width;
                canvas.height = height;

                const ctx = canvas.getContext('2d');
                // 이미지 품질 향상을 위한 설정
                ctx.imageSmoothingEnabled = true;
                ctx.imageSmoothingQuality = 'high';
                ctx.drawImage(img, 0, 0, width, height);

                // JPEG 형식으로 변환 (용량 감소)
                const optimizedBase64 = canvas.toDataURL('image/jpeg', quality);
                console.log(`이미지 최적화: ${img.width}x${img.height} → ${width}x${height}`);
                console.log(`크기 감소: ${(imageBase64.length / 1024).toFixed(2)}KB → ${(optimizedBase64.length / 1024).toFixed(2)}KB`);
                resolve(optimizedBase64);
            };
            img.onerror = () => reject(new Error('이미지 로드 실패'));
            img.src = imageBase64;
        });
    }

    /**
     * 샘플 이미지 로드
     */
    async loadSampleImage(sampleName) {
        try {
            const response = await fetch(`samples/${sampleName}`);
            const blob = await response.blob();

            // Blob을 base64로 변환
            const reader = new FileReader();
            reader.onerror = () => {
                console.error('샘플 이미지 FileReader 오류:', reader.error);
                this.showToast('샘플 이미지를 읽지 못했습니다.', 'error');
            };
            reader.onload = async (e) => {
                // M-8: optimizeImage rejects when the browser can't decode
                // the bytes — surface that as a toast instead of an unhandled
                // promise rejection that leaves the UI stuck mid-state.
                try {
                    const optimizedImage = await this.optimizeImage(e.target.result);
                    this._applyLoadedImage(optimizedImage);
                } catch (err) {
                    console.error('샘플 이미지 최적화 실패:', err);
                    this.showToast('샘플 이미지 처리 중 오류가 발생했습니다.', 'error');
                }
            };
            reader.readAsDataURL(blob);
        } catch (error) {
            console.error('샘플 이미지 로드 실패:', error);
            this.showToast('샘플 이미지를 불러올 수 없습니다.', 'error');
        }
    }

    /**
     * 이미지 파일 처리
     */
    handleImageFile(file) {
        const reader = new FileReader();
        reader.onerror = () => {
            console.error('파일 읽기 오류:', reader.error);
            this.showToast('이미지 파일을 읽지 못했습니다.', 'error');
        };
        reader.onload = async (e) => {
            // M-8: catch optimizeImage rejections (decode failure, malformed
            // file, etc.) and notify the user instead of swallowing the error.
            try {
                const optimizedImage = await this.optimizeImage(e.target.result);
                this._applyLoadedImage(optimizedImage);
            } catch (err) {
                console.error('이미지 최적화 실패:', err);
                this.showToast('이미지 처리 중 오류가 발생했습니다. 다른 이미지를 시도해주세요.', 'error');
            }
        };
        reader.readAsDataURL(file);
    }

    /**
     * 공통: 최적화된 이미지가 준비되면 미리보기와 UI 상태를 갱신한다.
     * (loadSampleImage / handleImageFile 두 군데에서 동일한 후처리를 수행)
     */
    _applyLoadedImage(optimizedImage) {
        this.currentImage = optimizedImage;
        this.recognizedIngredients = [];

        const previewImage = document.getElementById('previewImage');
        if (previewImage) previewImage.src = this.currentImage;
        document.querySelector('.upload-placeholder')?.classList.add('hidden');
        document.getElementById('imagePreview')?.classList.remove('hidden');

        const ingredientsText = document.getElementById('ingredientsText');
        if (ingredientsText) ingredientsText.value = '';

        const recognizedSection = document.getElementById('recognizedIngredientsSection');
        recognizedSection?.classList.remove('hidden');

        const recognizedContent = document.getElementById('recognizedIngredientsContent');
        if (recognizedContent) {
            recognizedContent.innerHTML = '<p class="recognized-hint">📸 사진이 준비됐어요. 아래 <b>‘재료 분석하기’</b> 버튼을 눌러 시작해 보세요. (보통 5~15초)</p>';
        }

        this.updateGenerateButton();
    }

    /**
     * 레시피 생성 버튼 상태 업데이트
     */
    updateGenerateButton() {
        const ingredientsText = document.getElementById('ingredientsText');
        const generateRecipeBtn = document.getElementById('generateRecipeBtn');

        const hasImage = this.currentImage !== null;
        const hasText = ingredientsText?.value.trim().length > 0;
        const hasRecognized = this.recognizedIngredients.length > 0;

        generateRecipeBtn.disabled = !(hasImage || hasText || hasRecognized);
    }

    /**
     * 재료 인식 초기화
     */
    initIngredientRecognition() {
        const analyzeImageBtn = document.getElementById('analyzeImageBtn');

        analyzeImageBtn?.addEventListener('click', () => {
            this.analyzeImage();
        });
    }

    /**
     * 이미지 분석 및 재료 인식
     */
    async analyzeImage() {
        if (!this.currentImage) {
            this.showToast('이미지를 먼저 업로드해주세요.', 'error');
            return;
        }

        const analyzeBtn = document.getElementById('analyzeImageBtn');
        const recognizedContent = document.getElementById('recognizedIngredientsContent');

        // 분석 중 표시
        analyzeBtn.disabled = true;
        analyzeBtn.innerHTML = '<span class="btn-icon">⏳</span> 분석 중...';
        recognizedContent.innerHTML = '<div class="loading-mini"><div class="loading-spinner-small"></div><p>재료를 인식하는 중...</p></div>';

        try {
            const ingredients = await window.fridgeRecipeBackend.recognizeIngredients(this.currentImage);
            this.recognizedIngredients = ingredients;

            if (ingredients.length > 0) {
                // 인식된 재료 표시
                const html = `
                    <div class="recognized-list">
                        ${ingredients.map((ing, index) => `
                            <div class="recognized-item">
                                <span class="recognized-number" aria-hidden="true">${index + 1}</span>
                                <span class="recognized-name">${ing}</span>
                            </div>
                        `).join('')}
                    </div>
                    <p class="recognized-note">💡 잘못 인식된 재료가 있다면 아래 입력란에서 직접 수정하거나, 추가할 재료를 더 적어 주세요.</p>
                `;
                recognizedContent.innerHTML = html;

                // 재료를 텍스트 입력창에 업데이트 (항상 새로운 재료로 교체)
                const ingredientsText = document.getElementById('ingredientsText');
                ingredientsText.value = ingredients.join(', ');

                this.showToast(`${ingredients.length}개의 재료를 찾았어요.`, 'success');
            } else {
                recognizedContent.innerHTML = `
                    <p class="recognized-error">사진에서 재료를 찾지 못했어요.</p>
                    <p class="recognized-note">
                        💡 <b>이렇게 해 보세요</b><br>
                        · 더 밝고 또렷한 사진으로 바꿔 보세요.<br>
                        · 또는 아래 입력란에 재료를 직접 적어 주세요.
                    </p>
                `;
                this.showToast('재료를 인식하지 못했어요. 다른 사진으로 시도해 보세요.', 'warning');
            }
        } catch (error) {
            console.error('재료 인식 오류:', error);

            // 에러 메시지 분석 — 사용자가 다음에 무엇을 할지 명확히
            let errorMessage = '재료 인식에 실패했어요.';
            let actionHint = '잠시 후 다시 시도해 보세요.';
            let toastMessage = '재료 인식에 실패했어요. 잠시 후 다시 시도해 보세요.';
            let toastType = 'error';

            const msg = error.message || '';
            if (msg.includes('API 키')) {
                errorMessage = 'API 키 설정이 필요해요.';
                actionHint = '오른쪽 상단의 ⚙️ 버튼을 눌러 OpenRouter API 키를 등록해 주세요.';
                toastMessage = 'API 키를 먼저 설정해 주세요.';
                toastType = 'warning';
            } else if (msg.includes('처리하지 못했습니다')) {
                errorMessage = 'AI가 이 사진을 인식하지 못했어요.';
                actionHint = '냉장고 안이 잘 보이는, 더 또렷한 사진으로 시도해 보시겠어요?';
                toastMessage = '사진을 인식하지 못했어요. 다른 사진을 시도해 보세요.';
            } else if (msg.includes('크기가 너무')) {
                errorMessage = '사진 용량이 너무 커요.';
                actionHint = '10MB 이하의 사진으로 다시 올려 주세요.';
                toastMessage = '사진 용량이 너무 커요.';
            } else if (msg.includes('사용량이 많습니다')) {
                errorMessage = '지금 AI 서버 요청이 몰리고 있어요.';
                actionHint = '30초~1분 뒤에 다시 시도해 주세요.';
                toastMessage = '서버가 바빠요. 잠시 후 다시 시도해 주세요.';
                toastType = 'warning';
            }

            recognizedContent.innerHTML = `
                <p class="recognized-error">${errorMessage}</p>
                <p class="recognized-note">💡 ${actionHint}</p>
            `;
            this.showToast(toastMessage, toastType);
        } finally {
            analyzeBtn.disabled = false;
            analyzeBtn.innerHTML = '<span class="btn-icon" aria-hidden="true">🔍</span> 재료 분석하기';
            this.updateGenerateButton();
        }
    }

    /**
     * 레시피 생성 초기화
     */
    initRecipeGeneration() {
        const generateRecipeBtn = document.getElementById('generateRecipeBtn');
        const newSearchBtn = document.getElementById('newSearchBtn');

        generateRecipeBtn?.addEventListener('click', () => {
            this.generateRecipe();
        });

        newSearchBtn?.addEventListener('click', () => {
            this.resetSearch();
        });
    }

    /**
     * 레시피 생성
     */
    async generateRecipe() {
        const ingredientsText = document.getElementById('ingredientsText');
        const ingredients = ingredientsText?.value.trim() || '';

        // UI 업데이트
        document.getElementById('loadingSection')?.classList.remove('hidden');
        document.getElementById('recipeResult')?.classList.add('hidden');

        try {
            // 이미지가 있으면 이미지와 함께 전송
            const recipe = await window.fridgeRecipeBackend.generateRecipe(
                ingredients,
                this.currentImage
            );
            this.currentRecipe = {
                ...recipe,
                ingredients: ingredientsText?.value.trim() || '냉장고 재료',
                timestamp: new Date().toISOString()
            };
            this.displayRecipe(this.currentRecipe);
        } catch (error) {
            console.error('레시피 생성 오류:', error);

            const msg = error.message || '';
            if (msg.includes('API 키')) {
                this.showToast(
                    'API 키 설정이 필요해요. 오른쪽 위 ⚙️ 버튼에서 등록해 주세요. 우선 샘플 레시피를 보여 드릴게요.',
                    'warning'
                );
                // 대체 레시피 표시
                const fallbackRecipe = window.fridgeRecipeBackend.getFallbackRecipe(ingredients || '냉장고 재료');
                this.currentRecipe = {
                    ...fallbackRecipe,
                    ingredients: ingredients || '냉장고 재료',
                    timestamp: new Date().toISOString()
                };
                this.displayRecipe(this.currentRecipe);
            } else if (msg.includes('사용량이 많습니다') || msg.includes('429')) {
                this.showToast(
                    '지금 AI 서버 요청이 몰리고 있어요. 30초~1분 뒤에 다시 시도해 주세요.',
                    'warning'
                );
            } else if (msg.toLowerCase().includes('network') || msg.toLowerCase().includes('failed to fetch')) {
                this.showToast(
                    '네트워크 연결을 확인하고 다시 시도해 주세요.',
                    'error'
                );
            } else {
                this.showToast(
                    '레시피를 만들지 못했어요. 잠시 후 다시 시도하거나, 재료를 좀 더 추가해 보세요.',
                    'error'
                );
            }
        } finally {
            document.getElementById('loadingSection')?.classList.add('hidden');
        }
    }

    /**
     * 레시피 표시
     */
    displayRecipe(recipe) {
        const recipeContent = document.getElementById('recipeContent');
        const recipeResult = document.getElementById('recipeResult');

        // ingredients와 steps를 배열로 변환
        const ingredients = Array.isArray(recipe.ingredients)
            ? recipe.ingredients
            : [recipe.ingredients];

        const steps = Array.isArray(recipe.steps)
            ? recipe.steps
            : [recipe.steps];

        const html = `
            <div class="recipe-header">
                <h3 class="recipe-dish-name">${recipe.dishName}</h3>
                <div class="recipe-meta">
                    <span class="recipe-badge">⏱️ ${recipe.cookingTime}</span>
                    <span class="recipe-badge">📊 ${recipe.difficulty}</span>
                </div>
            </div>

            <div class="recipe-section">
                <h4 class="recipe-section-title">
                    <span>🥬</span> 재료
                </h4>
                <ul class="recipe-ingredients-list">
                    ${ingredients.map(ing => `<li>${ing}</li>`).join('')}
                </ul>
            </div>

            <div class="recipe-section">
                <h4 class="recipe-section-title">
                    <span>👨‍🍳</span> 조리법
                </h4>
                <ol class="recipe-steps-list">
                    ${steps.map(step => `<li>${step}</li>`).join('')}
                </ol>
            </div>

            <div class="recipe-tip">
                <strong>💡 Tip:</strong> ${recipe.tip}
            </div>
        `;

        recipeContent.innerHTML = html;
        recipeResult?.classList.remove('hidden');

        // 결과로 스크롤 + 키보드/스크린 리더 사용자에게 결과로 포커스 이동
        recipeResult?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        // setTimeout: scrollIntoView 직후 focus 시 일부 브라우저에서 스크롤이 끊김
        setTimeout(() => {
            recipeResult?.focus({ preventScroll: true });
        }, 400);
    }

    /**
     * 검색 초기화
     */
    resetSearch() {
        this.currentImage = null;
        this.currentRecipe = null;

        document.getElementById('imageInput').value = '';
        document.getElementById('ingredientsText').value = '';
        document.querySelector('.upload-placeholder')?.classList.remove('hidden');
        document.getElementById('imagePreview')?.classList.add('hidden');
        document.getElementById('recipeResult')?.classList.add('hidden');
        document.getElementById('recognizedIngredientsSection')?.classList.add('hidden');

        this.updateGenerateButton();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    /**
     * UI 업데이트
     */
    updateUI() {
        this.updateGenerateButton();
    }

    /**
     * 토스트 메시지 표시
     * type: 'success' | 'error' | 'warning' | 'info'
     */
    showToast(message, type = 'success') {
        const toast = document.getElementById('successToast');
        const toastIcon = toast?.querySelector('.toast-icon');
        const toastMessage = toast?.querySelector('.toast-message');

        if (toastMessage) {
            toastMessage.textContent = message;
        }
        // Visual differentiation by type — color alone is not enough (WCAG 1.4.1)
        if (toastIcon) {
            const icons = { success: '✅', error: '⚠️', warning: '⚠️', info: 'ℹ️' };
            toastIcon.textContent = icons[type] || '✅';
        }
        if (toast) {
            toast.classList.remove('toast-error', 'toast-warning', 'toast-info');
            if (type !== 'success') {
                toast.classList.add(`toast-${type}`);
            }
        }

        toast?.classList.remove('hidden');

        // Clear any previous auto-hide timer to avoid premature hide on rapid toasts
        if (this._toastTimer) {
            clearTimeout(this._toastTimer);
        }
        this._toastTimer = setTimeout(() => {
            toast?.classList.add('hidden');
        }, 4000);
    }
}

// 앱 초기화
let fridgeRecipeApp;

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        fridgeRecipeApp = new FridgeRecipeApp();
        window.fridgeRecipeApp = fridgeRecipeApp;
    });
} else {
    fridgeRecipeApp = new FridgeRecipeApp();
    window.fridgeRecipeApp = fridgeRecipeApp;
}

console.log('냉장고를 부탁해 앱이 로드되었습니다.');
