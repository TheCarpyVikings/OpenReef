import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { validateContentType, safeErrorResponse } from '@/lib/validation';
import { rateLimit } from '@/lib/rate-limit';

const ALLOWED_VOICES = ['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'] as const;

const TTSSchema = z.object({
    text: z.string().min(1, 'Text is required').max(5000, 'Text too long (max 5000 chars)'),
    voice: z.enum(ALLOWED_VOICES).optional().default('shimmer'),
});

export async function POST(req: NextRequest) {
    // Rate limit: 10 requests per minute for TTS (paid API)
    const rateLimitError = rateLimit('tts', 10);
    if (rateLimitError) return rateLimitError;

    // Validate Content-Type
    const ctError = validateContentType(req);
    if (ctError) return ctError;

    try {
        const body = await req.json();
        const parsed = TTSSchema.safeParse(body);

        if (!parsed.success) {
            return NextResponse.json(
                { error: 'Invalid input', details: parsed.error.flatten() },
                { status: 400 }
            );
        }

        const { text, voice } = parsed.data;

        const apiKey = process.env.OPENAI_API_KEY;

        if (!apiKey) {
            return NextResponse.json(
                { error: 'OpenAI API key not configured on server' },
                { status: 500 }
            );
        }

        const response = await fetch('https://api.openai.com/v1/audio/speech', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${apiKey}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                model: 'tts-1',
                input: text,
                voice: voice,
            }),
        });

        if (!response.ok) {
            console.error('OpenAI TTS API error:', response.status);
            return NextResponse.json(
                { error: 'TTS generation failed' },
                { status: response.status }
            );
        }

        const audioBuffer = await response.arrayBuffer();

        return new NextResponse(audioBuffer, {
            headers: {
                'Content-Type': 'audio/mpeg',
            },
        });
    } catch (error: unknown) {
        return safeErrorResponse(error, 'TTS processing failed');
    }
}
