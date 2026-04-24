import asyncio
import httpx

LLAMA_URL = "http://localhost:8080/v1/embeddings"
MODEL = "nomic-embed-text-v1.5"
MAX_EMBED_CHARS = 6000
_embed_lock = asyncio.Lock()


async def embed(text: str) -> list[float]:
    text = text[:MAX_EMBED_CHARS]
    async with _embed_lock:
        async with httpx.AsyncClient(timeout=180.0) as client:
            for attempt in range(3):
                try:
                    resp = await client.post(
                        LLAMA_URL,
                        json={"model": MODEL, "input": text},
                    )
                    resp.raise_for_status()
                    return resp.json()["data"][0]["embedding"]
                except httpx.ConnectError as e:
                    raise RuntimeError(
                        "Cannot reach llama-server at http://localhost:8080. "
                        "Is it running? Try: systemctl start llamacpp-embed"
                    ) from e
                except (httpx.HTTPError, httpx.TimeoutException) as e:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(2 ** attempt)


def embed_sync(text: str) -> list[float]:
    return asyncio.run(embed(text))
