/**
 * Vercel 서버리스 함수 - 레시피 생성
 * API 키를 서버 측에서 관리
 */

// C-5: free OpenRouter multimodal model that actually exists in the model
// catalogue (verified via GET /api/v1/models). The previous value
// ``google/gemini-3-flash-preview`` was a paid model and silently failed for
// users without billing enabled.
const OPENROUTER_MODEL = process.env.OPENROUTER_MODEL || 'google/gemma-4-26b-a4b-it:free';

// C-6: lock CORS down to the deployment origin (configurable per-environment),
// instead of the wildcard ``*`` which let any site invoke this function.
const ALLOWED_ORIGIN =
    process.env.ALLOWED_ORIGIN || 'https://vibecoding-fridge.vercel.app';

// C-6: HTTP-Referer that OpenRouter records for attribution. Pulling it from
// an environment variable means it can't be spoofed via the incoming request.
const HTTP_REFERER =
    process.env.OPENROUTER_HTTP_REFERER || ALLOWED_ORIGIN;

// C-6 / H-10: prompt length cap (characters). OpenRouter rejects oversized
// requests anyway, but we want the rejection to happen before we burn quota.
const MAX_PROMPT_CHARS = parseInt(process.env.MAX_PROMPT_CHARS || '4000', 10);

// H-10: in-memory token bucket per IP. Vercel scales horizontally so this is
// best-effort — it caps abuse from a single warm instance, not from a
// determined attacker. Move to Redis/Upstash if stronger guarantees needed.
const RATE_LIMIT_WINDOW_MS = 60 * 1000; // 1 minute
const RATE_LIMIT_MAX = parseInt(process.env.RATE_LIMIT_MAX || '10', 10);
const _ipBuckets = new Map(); // ip -> { count, windowStart }

function _checkRateLimit(ip) {
    if (!ip) return true; // can't identify, fall open
    const now = Date.now();
    const bucket = _ipBuckets.get(ip);
    if (!bucket || now - bucket.windowStart >= RATE_LIMIT_WINDOW_MS) {
        _ipBuckets.set(ip, { count: 1, windowStart: now });
        // Best-effort cleanup: drop old buckets so the map can't grow unbounded.
        if (_ipBuckets.size > 1000) {
            for (const [k, v] of _ipBuckets) {
                if (now - v.windowStart >= RATE_LIMIT_WINDOW_MS) {
                    _ipBuckets.delete(k);
                }
            }
        }
        return true;
    }
    if (bucket.count >= RATE_LIMIT_MAX) {
        return false;
    }
    bucket.count += 1;
    return true;
}

function _getClientIp(req) {
    const fwd = req.headers['x-forwarded-for'];
    if (typeof fwd === 'string' && fwd.length) {
        return fwd.split(',')[0].trim();
    }
    return req.headers['x-real-ip'] || req.socket?.remoteAddress || '';
}

export default async function handler(req, res) {
    // C-6: lock CORS to a single, configurable origin instead of wildcard.
    res.setHeader('Access-Control-Allow-Credentials', true);
    res.setHeader('Access-Control-Allow-Origin', ALLOWED_ORIGIN);
    res.setHeader('Vary', 'Origin');
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    res.setHeader(
        'Access-Control-Allow-Headers',
        'X-CSRF-Token, X-Requested-With, Accept, Accept-Version, Content-Length, Content-MD5, Content-Type, Date, X-Api-Version'
    );

    // OPTIONS 요청 처리 (CORS preflight)
    if (req.method === 'OPTIONS') {
        res.status(200).end();
        return;
    }

    // POST 요청만 허용
    if (req.method !== 'POST') {
        return res.status(405).json({ error: 'Method not allowed' });
    }

    // H-10: cheap rate-limit gate before we touch the upstream model.
    const clientIp = _getClientIp(req);
    if (!_checkRateLimit(clientIp)) {
        return res.status(429).json({
            error: '요청이 너무 많습니다. 잠시 후 다시 시도해주세요.',
        });
    }

    try {
        const { prompt, imageBase64, type } = req.body || {};

        // 환경변수에서 API 키 가져오기
        const apiKey = process.env.OPENROUTER_API_KEY;

        if (!apiKey) {
            return res.status(500).json({
                error: 'Server configuration error: API key not set'
            });
        }

        // C-6 / H-10: prompt length validation before paying for an upstream call.
        if (typeof prompt !== 'string' || !prompt.trim()) {
            return res.status(400).json({ error: '프롬프트가 비어 있습니다.' });
        }
        if (prompt.length > MAX_PROMPT_CHARS) {
            return res.status(400).json({
                error: `프롬프트가 너무 깁니다. 최대 ${MAX_PROMPT_CHARS}자까지 허용됩니다.`,
                length: prompt.length,
            });
        }

        // 이미지 크기 체크 (Base64 문자열 길이로 대략적인 크기 추정)
        if (imageBase64) {
            if (typeof imageBase64 !== 'string') {
                return res.status(400).json({ error: '이미지 형식이 올바르지 않습니다.' });
            }
            const imageSizeKB = (imageBase64.length * 0.75) / 1024; // Base64는 원본의 약 133%
            console.log(`이미지 크기 (추정): ${imageSizeKB.toFixed(2)} KB`);

            // 5MB 제한 (OpenRouter/Gemma의 일반적인 제한)
            if (imageSizeKB > 5120) {
                return res.status(400).json({
                    error: '이미지 크기가 너무 큽니다. 5MB 이하의 이미지를 사용해주세요.',
                    size: `${imageSizeKB.toFixed(2)} KB`
                });
            }
        }

        // OpenRouter API 호출
        const openRouterUrl = 'https://openrouter.ai/api/v1/chat/completions';

        // content 구성
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
            model: OPENROUTER_MODEL,
            messages: [
                {
                    role: "user",
                    content: content
                }
            ],
            max_tokens: 2000,  // 토큰 증가
            temperature: 0.7,
            top_p: 0.9,  // 응답 다양성 증가
            frequency_penalty: 0.0,
            presence_penalty: 0.0,
            // M-7: prefer structured JSON output to avoid regex parsing on
            // the client side.
            response_format: { type: "json_object" }
        };

        console.log('이미지 포함:', !!imageBase64);

        const response = await fetch(openRouterUrl, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${apiKey}`,
                'Content-Type': 'application/json',
                // C-6: HTTP-Referer is server-controlled (env), never echoed
                // back from the incoming request.
                'HTTP-Referer': HTTP_REFERER,
                'X-Title': 'Fridge Recipe App'
            },
            body: JSON.stringify(requestBody)
        });

        if (!response.ok) {
            const errorText = await response.text();
            console.error('OpenRouter API error:', errorText);
            return res.status(response.status).json({
                error: `AI API error: ${response.status}`,
                details: errorText
            });
        }

        const data = await response.json();
        console.log('OpenRouter 응답:', JSON.stringify(data, null, 2));

        if (data.choices && data.choices[0] && data.choices[0].message) {
            const content = data.choices[0].message.content || '';

            // 빈 응답 체크
            if (!content || content.trim() === '') {
                console.warn('AI가 빈 응답을 반환했습니다.');
                return res.status(200).json({
                    success: false,
                    error: 'AI가 이미지를 처리하지 못했습니다.',
                    content: ''
                });
            }

            return res.status(200).json({
                success: true,
                content: content
            });
        } else {
            console.error('잘못된 응답 구조:', data);
            return res.status(500).json({
                error: 'Invalid response from AI API',
                responseData: data
            });
        }

    } catch (error) {
        console.error('Server error:', error);
        return res.status(500).json({
            error: 'Internal server error',
            message: error.message
        });
    }
}
