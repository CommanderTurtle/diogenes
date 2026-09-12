module ConvertedFiles.Workspace.MediaMd

let file = """# Gallery, media, and speech

The gallery stores uploaded and generated media under `data/generated_images` with metadata in `GalleryImage` rows. `routes/gallery/gallery_routes.py` handles library, album, transform, and deletion requests.

## Gallery API

~~~ text
POST  /api/gallery/upload
GET   /api/gallery/library
GET   /api/gallery/{id}
PATCH /api/gallery/{id}
DELETE /api/gallery/{id}
POST  /api/gallery/download-zip
GET   /api/gallery/albums
POST  /api/gallery/albums
POST  /api/gallery/albums/{id}/add
POST  /api/gallery/{id}/favorite
POST  /api/gallery/{id}/ai-tag
~~~

Uploads are byte-limited and extension-gated. Image metadata includes EXIF dimensions when Pillow can read it. Video imports skip EXIF extraction. Duplicate detection uses a stored file hash, while generated filenames are opaque media IDs.

`GET /api/generated-image/{filename}` validates the filename, resolves it through `src/generated_images.py:resolve_generated_image_path()`, checks the gallery row user where a row exists, and returns media with `nosniff` headers.

## Editor transforms

~~~ text
POST /api/image/inpaint
POST /api/image/harmonize
POST /api/image/sharpen
POST /api/image/denoise
POST /api/image/upscale-local
POST /api/image/mask
POST /api/image/remove-bg
POST /api/image/enhance-face
~~~

`static/js/galleryEditor.js` and modules below `static/js/editor/` manage layers, masks, history, strokes, snapping, model selection, and server-backed drafts. Transform availability depends on installed image packages and configured model endpoints.

Provider-returned media URLs pass through outbound address validation before server download. Model endpoint suffixes used by editor routes are restricted to the supported image API paths.

## Speech to text

~~~ text
GET  /api/stt/stats
POST /api/stt/transcribe
~~~

`services/stt/stt_service.py` supports:

- `disabled`: route reports unavailable;
- `browser`: the Web Speech API runs in the browser;
- `local`: `faster-whisper` processes a temporary WebM file;
- `endpoint:{id}`: audio is posted to `/audio/transcriptions` on a model endpoint.

The local path removes its temporary file in `finally`. A failed server transcription can leave the recording attached to the chat so the user can retry.

## Text to speech

~~~ text
GET  /api/tts/stats
POST /api/tts/synthesize
POST /api/tts/clear-cache
~~~

`services/tts/tts_service.py` supports browser speech synthesis, local Kokoro when its packages and CUDA runtime are present, and endpoint-backed `/audio/speech` requests. Binary replies are identified as WAV or MP3 from their bytes; JSON replies can contain base64 audio.

The server cache is `data/tts_cache`. Its key includes provider, model, voice, safe speed, and text. `ODYSSEUS_TTS_CACHE_MAX_BYTES` sets its size ceiling; zero or a negative value turns eviction off. Cache enforcement removes oldest WAV/MP3 entries toward eighty percent of the ceiling.

## Failure checks

- Microphone capture requires a secure browser context and permission.
- An endpoint-backed speech provider may pass discovery and fail on its audio route.
- Missing local image or speech packages return install guidance or an unavailable response.
- Gallery replacement can change bytes under one media filename; the browser adds cache-busting query data after edits.
"""

let render() = file
