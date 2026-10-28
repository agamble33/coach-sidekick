# Meta Model API notes (verified Oct 27, 2026)

Base URL: `https://api.meta.ai/v1`. Auth: `Authorization: Bearer <key>`.

## Models available to this key
muse-spark-1.3, muse-spark-1.2, muse-spark-1.1 (+ `-contributor` variants), muse-wonder-1.0,
muse-image-1.0, muse-voice-transcribe-1.0, sam-3.1.

## Text / agent: `POST /responses`
OpenAI Responses-style body: `{"model": "muse-spark-1.3", "input": [{"role": "user", "content": [{"type": "input_text", "text": "..."}]}], "stream": false}`.
Reply text is in `output[*]` where `type == "message"`, `content[*].type == "output_text"`.
Default `reasoning.effort` is **high**: a one-line greeting cost 842 reasoning tokens. Set `"reasoning": {"effort": "low"}` for fast in-game replies.

## Speech to text: `POST /asr/transcribe`
multipart/form-data: `request` (JSON) + `audio` (WAV). WAV must be mono, 16-bit PCM, 16 or 24 kHz.
Limits: 10 minutes, 32 MB. Modes: PUSH_TO_TALK (default), ENDPOINTING, DIARIZATION.
Options: `languageBias: ["English"]`, `keywords: ["..."]` for game vocabulary.
Response: `{sessionId, transcript, audioDurationMs, turns: [{turnId, startMs, endMs, transcript, speaker?}]}`.
Realtime: `wss://api.meta.ai/v1/asr/realtime`, auth in the first JSON frame, raw PCM frames paced at real time.
Pricing $0.18 per hour of audio.

## Text to speech
Not offered by the Meta Model API. Coach speaks through the local OS voice (Windows SAPI) or the browser's `speechSynthesis`.
