/**
 * 냉장고를 부탁해 백엔드
 * OpenRouter API를 사용하여 레시피 생성
 */

class FridgeRecipeBackend {
    constructor() {
        // 서버리스 함수 사용 - API 키는 서버에서 관리
        this.useServerlessAPI = true;
        this.serverlessUrl = '/api/recipe';

        // 개발/로컬 테스트용 - 로컬에서는 직접 API 호출 가능
        this.apiKey = this.getApiKey();
        this.baseUrl = 'https://openrouter.ai/api/v1';
        // C-5: free OpenRouter multimodal model that actually exists in the
        // model catalogue. The previous slug ``google/gemini-3-flash-preview``
        // was a paid model and silently failed without billing.
        this.model = 'google/gemma-4-26b-a4b-it:free';
    }

    /**
     * API 키 가져오기 (로컬 개발용)
     */
    getApiKey() {
        if (typeof localStorage !== 'undefined') {
            const storedKey = localStorage.getItem('openrouter_api_key');
            if (storedKey) {
                return storedKey;
            }
        }
        return null;
    }

    /**
     * API 키 설정 (로컬 개발용)
     */
    setApiKey(apiKey) {
        if (typeof localStorage !== 'undefined') {
            localStorage.setItem('openrouter_api_key', apiKey);
            this.apiKey = apiKey;
            console.log('API 키가 설정되었습니다.');
        }
    }

    /**
     * 레시피 생성 프롬프트 작성
     *
     * M-7: We now ask the model for a strict JSON object so the client
     * doesn't need to massage Korean section headers with regexes. The
     * old text-form prompt is preserved as a graceful fallback inside
     * ``parseRecipeResponse`` for models that ignore ``response_format``.
     */
    createRecipePrompt(ingredients, hasImage) {
        const intro = hasImage
            ? '당신은 전문 요리사입니다. 이미지에서 보이는 냉장고 재료들을 분석하고, 맛있는 레시피를 추천해주세요.'
            : '당신은 전문 요리사입니다. 다음 재료들을 사용하여 맛있는 레시피를 추천해주세요.';

        const ingredientsLine = hasImage
            ? (ingredients ? `추가 재료/요청사항: ${ingredients}` : '추가 재료/요청사항: 없음')
            : `재료: ${ingredients}`;

        return `${intro}

${ingredientsLine}

응답은 반드시 아래 스키마를 따르는 단 하나의 JSON 객체로만 반환하세요. 코드펜스/마크다운/설명을 절대 포함하지 마세요.

{
  "dishName": "요리 이름",
  "difficulty": "쉬움|보통|어려움",
  "cookingTime": "예: 30분",
  "ingredients": ["재료1", "재료2", "재료3"],
  "steps": ["1. 단계1", "2. 단계2", "3. 단계3"],
  "tip": "요리 팁"
}

응답 규칙:
1. 한국인의 입맛에 맞는, 실용적이고 만들기 쉬운 레시피를 추천하세요.
2. 조리법은 명확하고 구체적으로 작성하세요.
3. 추가 재료가 필요하면 일반적으로 가정에 있는 것들만 사용하세요.
4. JSON 외 다른 출력은 금지됩니다.`;
    }

    /**
     * API 응답 파싱
     *
     * M-7: try JSON first (we ask for ``response_format: {type:"json_object"}``
     * upstream) and fall back to the legacy regex parser when the model
     * returns a Korean text block.
     */
    parseRecipeResponse(responseText) {
        const text = (responseText || '').trim();

        // 1) JSON path — strip optional code fences before parsing.
        const cleaned = text.replace(/^```(?:json)?\s*|\s*```$/gi, '').trim();
        const firstBrace = cleaned.indexOf('{');
        const lastBrace = cleaned.lastIndexOf('}');
        if (firstBrace !== -1 && lastBrace > firstBrace) {
            const candidate = cleaned.slice(firstBrace, lastBrace + 1);
            try {
                const obj = JSON.parse(candidate);
                if (obj && typeof obj === 'object') {
                    return {
                        dishName: typeof obj.dishName === 'string' ? obj.dishName.trim() : '맛있는 요리',
                        difficulty: typeof obj.difficulty === 'string' ? obj.difficulty.trim() : '보통',
                        cookingTime: typeof obj.cookingTime === 'string' ? obj.cookingTime.trim() : '30분',
                        ingredients: Array.isArray(obj.ingredients) && obj.ingredients.length > 0
                            ? obj.ingredients.map(s => String(s))
                            : ['재료 정보를 불러올 수 없습니다'],
                        steps: Array.isArray(obj.steps) && obj.steps.length > 0
                            ? obj.steps.map(s => String(s))
                            : ['1. 재료를 준비합니다.', '2. 조리를 시작합니다.'],
                        tip: typeof obj.tip === 'string' ? obj.tip.trim() : '맛있게 드세요!',
                        fullText: text,
                    };
                }
            } catch (_) {
                // fall through to regex parser
            }
        }

        // 2) Legacy regex fallback for plain-text responses.
        try {
            const dishMatch = text.match(/요리명:\s*(.+)/);
            const difficultyMatch = text.match(/난이도:\s*(.+)/);
            const timeMatch = text.match(/조리시간:\s*(.+)/);
            const ingredientsMatch = text.match(/재료:\s*([\s\S]+?)(?=조리법:|$)/);
            const stepsMatch = text.match(/조리법:\s*([\s\S]+?)(?=팁:|$)/);
            const tipMatch = text.match(/팁:\s*(.+)/);

            let ingredientsList = [];
            if (ingredientsMatch) {
                ingredientsList = ingredientsMatch[1]
                    .split('\n')
                    .filter(line => line.trim().startsWith('-'))
                    .map(line => line.trim().substring(1).trim());
            }

            let stepsList = [];
            if (stepsMatch) {
                stepsList = stepsMatch[1]
                    .split('\n')
                    .filter(line => /^\d+\./.test(line.trim()))
                    .map(line => line.trim());
            }

            return {
                dishName: dishMatch ? dishMatch[1].trim() : '맛있는 요리',
                difficulty: difficultyMatch ? difficultyMatch[1].trim() : '보통',
                cookingTime: timeMatch ? timeMatch[1].trim() : '30분',
                ingredients: ingredientsList.length > 0 ? ingredientsList : ['재료 정보를 불러올 수 없습니다'],
                steps: stepsList.length > 0 ? stepsList : ['1. 재료를 준비합니다.', '2. 조리를 시작합니다.'],
                tip: tipMatch ? tipMatch[1].trim() : '맛있게 드세요!',
                fullText: text,
            };
        } catch (error) {
            console.error('레시피 파싱 오류:', error);
            return {
                dishName: '추천 요리',
                difficulty: '보통',
                cookingTime: '30분',
                ingredients: ['파싱 오류가 발생했습니다'],
                steps: ['1. 재료를 준비합니다.'],
                tip: '다시 시도해주세요.',
                fullText: text,
            };
        }
    }

    /**
     * API 호출 (서버리스 또는 직접)
     */
    async callAPI(prompt, imageBase64 = null) {
        // 서버리스 API 사용
        if (this.useServerlessAPI) {
            return await this.callServerlessAPI(prompt, imageBase64);
        }

        // 직접 OpenRouter API 호출 (로컬 개발용)
        return await this.callOpenRouterAPI(prompt, imageBase64);
    }

    /**
     * 서버리스 함수 호출
     */
    async callServerlessAPI(prompt, imageBase64 = null) {
        try {
            const response = await fetch(this.serverlessUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    prompt: prompt,
                    imageBase64: imageBase64
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                console.error('서버 API 오류:', errorData);

                // Rate limit 에러 처리
                if (response.status === 429) {
                    throw new Error('무료 AI 서버가 현재 사용량이 많습니다. 잠시 후 다시 시도해주세요.');
                }

                throw new Error(`서버 오류: ${response.status} - ${errorData.error || response.statusText}`);
            }

            const data = await response.json();
            console.log('=== 서버 응답 데이터 ===', data);

            // success: false인 경우 서버에서 반환한 에러 처리
            if (data.success === false) {
                const errorMsg = data.error || 'AI가 이미지를 처리하지 못했습니다.';
                console.warn('서버 응답:', errorMsg);
                throw new Error(errorMsg);
            }

            if (data.success) {
                // content가 빈 문자열인 경우 처리
                if (!data.content || data.content.trim() === '') {
                    console.warn('AI 응답이 비어있습니다. 이미지 처리에 실패했을 가능성이 있습니다.');
                    throw new Error('AI가 이미지를 처리하지 못했습니다. 다른 이미지를 시도해보세요.');
                }

                // OpenRouter 응답 형식으로 변환
                return {
                    choices: [
                        {
                            message: {
                                content: data.content
                            }
                        }
                    ]
                };
            } else {
                console.error('응답 형식 오류 - data.success:', data.success, 'data.content:', data.content);
                throw new Error('서버 응답 형식이 올바르지 않습니다.');
            }
        } catch (error) {
            console.error('서버리스 API 호출 실패:', error);
            throw error;
        }
    }

    /**
     * OpenRouter API 직접 호출 (로컬 개발용)
     */
    async callOpenRouterAPI(prompt, imageBase64 = null) {
        if (!this.apiKey) {
            throw new Error('API 키가 설정되지 않았습니다. 설정 버튼을 눌러 API 키를 입력해주세요.');
        }

        // 이미지가 있으면 content를 배열로 구성
        let content;
        if (imageBase64) {
            content = [
                {
                    type: "text",
                    text: prompt
                },
                {
                    type: "image_url",
                    image_url: {
                        url: imageBase64
                    }
                }
            ];
        } else {
            content = prompt;
        }

        const requestBody = {
            model: this.model,
            messages: [
                {
                    role: "user",
                    content: content
                }
            ],
            max_tokens: 2000,
            temperature: 0.7,
            top_p: 0.9,
            // M-7: ask for JSON directly so the client parser doesn't have to
            // grovel through Korean section headers with regex. The fallback
            // regex parser still handles models that ignore this hint.
            response_format: { type: "json_object" }
        };

        const requestOptions = {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${this.apiKey}`,
                'Content-Type': 'application/json',
                'HTTP-Referer': window.location.origin,
                'X-Title': 'Fridge Recipe App'
            },
            body: JSON.stringify(requestBody)
        };

        const url = `${this.baseUrl}/chat/completions`;
        const response = await fetch(url, requestOptions);

        if (!response.ok) {
            const errorText = await response.text();
            console.error('API 오류:', errorText);
            throw new Error(`API 호출 실패: ${response.status} ${response.statusText}`);
        }

        return await response.json();
    }

    /**
     * 이미지에서 재료 인식
     */
    async recognizeIngredients(imageBase64) {
        if (!imageBase64) {
            throw new Error('이미지가 필요합니다.');
        }

        const prompt = `냉장고 사진을 분석하여 보이는 모든 식재료를 찾아주세요.

중요한 규칙:
1. 이미지를 자세히 관찰하고 보이는 모든 식재료를 나열하세요
2. 계란, 채소, 과일, 음료, 소스 등 모든 것을 포함하세요
3. 쉼표로 구분하여 나열하세요 (예: 계란, 우유, 당근, 양파, 토마토)
4. 다른 설명이나 형식 없이 재료 이름만 작성하세요
5. 한국어로 작성하세요

응답 형식: 재료1, 재료2, 재료3, ...`;

        try {
            console.log('재료 인식 중...');
            const response = await this.callAPI(prompt, imageBase64);

            if (response.choices && response.choices[0] && response.choices[0].message) {
                const content = response.choices[0].message.content;
                console.log('=== AI 원본 응답 ===');
                console.log(content);
                console.log('===================');

                // 여러 방식으로 파싱 시도
                let ingredientsList = [];

                // 방법 1: 쉼표로 구분된 형식
                if (content.includes(',')) {
                    ingredientsList = content
                        .split(',')
                        .map(item => item.trim())
                        .map(item => item.replace(/^[-•*]\s*/, '')) // 앞의 기호 제거
                        .map(item => item.replace(/\d+\.\s*/, '')) // 숫자. 제거
                        .filter(item => item.length > 0 && item.length < 50)
                        .filter(item => !item.match(/^(예시|응답|규칙|식재료|보이는|다음|형식)/));
                }

                // 방법 2: - 로 시작하는 목록 형식
                if (ingredientsList.length === 0 && content.includes('-')) {
                    ingredientsList = content
                        .split('\n')
                        .filter(line => line.trim().startsWith('-'))
                        .map(line => line.trim().substring(1).trim())
                        .filter(ing => ing.length > 0 && ing.length < 50);
                }

                // 방법 3: 숫자. 로 시작하는 목록 형식
                if (ingredientsList.length === 0 && /\d+\./.test(content)) {
                    ingredientsList = content
                        .split('\n')
                        .filter(line => /^\d+\./.test(line.trim()))
                        .map(line => line.replace(/^\d+\.\s*/, '').trim())
                        .filter(ing => ing.length > 0 && ing.length < 50);
                }

                // 방법 4: 줄바꿈으로만 구분된 경우 (아무 형식 없이)
                if (ingredientsList.length === 0) {
                    ingredientsList = content
                        .split('\n')
                        .map(item => item.trim())
                        .filter(item => item.length > 2 && item.length < 50)
                        .filter(item => !item.match(/^(예시|응답|규칙|식재료|보이는|다음|형식|:|！)/));
                }

                // 중복 제거
                ingredientsList = [...new Set(ingredientsList)];

                console.log('파싱된 재료 목록:', ingredientsList);
                console.log('재료 개수:', ingredientsList.length);
                return ingredientsList;
            } else {
                throw new Error('API 응답 형식이 올바르지 않습니다.');
            }
        } catch (error) {
            console.error('재료 인식 실패:', error);
            throw error;
        }
    }

    /**
     * 레시피 생성 메인 함수
     */
    async generateRecipe(ingredients, imageBase64 = null) {
        if (!ingredients && !imageBase64) {
            throw new Error('재료를 입력하거나 이미지를 업로드해주세요.');
        }

        const hasImage = !!imageBase64;
        const prompt = this.createRecipePrompt(ingredients || '', hasImage);

        try {
            console.log('레시피 생성 중...', hasImage ? '(이미지 포함)' : '');
            const response = await this.callAPI(prompt, imageBase64);

            if (response.choices && response.choices[0] && response.choices[0].message) {
                const result = this.parseRecipeResponse(response.choices[0].message.content);
                console.log('레시피 생성 완료:', result);
                return result;
            } else {
                throw new Error('API 응답 형식이 올바르지 않습니다.');
            }
        } catch (error) {
            console.error('레시피 생성 실패:', error);
            throw error;
        }
    }

    /**
     * 대체 레시피 (API 호출 실패시)
     */
    getFallbackRecipe(ingredients) {
        return {
            dishName: '간단한 볶음밥',
            difficulty: '쉬움',
            cookingTime: '15분',
            ingredients: [
                '밥 1공기',
                '계란 2개',
                '식용유 2큰술',
                '소금, 후추 약간',
                `사용 가능한 재료: ${ingredients}`
            ],
            steps: [
                '1. 팬에 식용유를 두르고 달군다.',
                '2. 계란을 풀어서 스크램블을 만든다.',
                '3. 밥을 넣고 함께 볶는다.',
                '4. 소금과 후추로 간을 맞춘다.',
                '5. 추가 재료가 있다면 함께 볶아준다.'
            ],
            tip: 'API 키를 설정하면 더 다양한 레시피를 추천받을 수 있습니다!',
            fullText: 'API를 사용할 수 없을 때 표시되는 기본 레시피입니다.'
        };
    }
}

// 전역 인스턴스 생성
const fridgeRecipeBackend = new FridgeRecipeBackend();

// 브라우저 환경에서 전역 함수로 노출
if (typeof window !== 'undefined') {
    window.FridgeRecipeBackend = FridgeRecipeBackend;
    window.fridgeRecipeBackend = fridgeRecipeBackend;
}

console.log('냉장고를 부탁해 백엔드가 로드되었습니다.');
