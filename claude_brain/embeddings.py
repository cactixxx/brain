import asyncio
import httpx

OLLAMA_URL = "http://localhost:11334/api/embeddings"
MODEL = "nomic-embed-text"
MAX_EMBED_CHARS = 6000
_embed_lock = asyncio.Lock()


async def embed(text: str) -> list[float]:
    text = text[:MAX_EMBED_CHARS]
    async with _embed_lock:
        async with httpx.AsyncClient(timeout=180.0) as client:
            for attempt in range(3):
                try:
                    resp = await client.post(
                        OLLAMA_URL,
                        json={
                            "model": MODEL,
                            "prompt": text,
                            "options": {"num_ctx": 2048},
                        },
                    )
                    resp.raise_for_status()
                    return resp.json()["embedding"]
                except (httpx.HTTPError, httpx.TimeoutException) as e:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(2 ** attempt)


def embed_sync(text: str) -> list[float]:
    return asyncio.run(embed(text))
