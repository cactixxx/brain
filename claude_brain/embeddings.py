import asyncio
import httpx

OLLAMA_URL = "http://localhost:11334/api/embeddings"
MODEL = "nomic-embed-text"
# nomic-embed-text context is 2048 tokens; 2000 chars (~500 tokens) is a safe, fast limit
_MAX_CHARS = 2000


async def embed(text: str) -> list[float]:
    text = text[:_MAX_CHARS]
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(OLLAMA_URL,
                                         json={"model": MODEL, "prompt": text})
                resp.raise_for_status()
                return resp.json()["embedding"]
        except httpx.ConnectError as e:
            raise RuntimeError(
                "Cannot reach Ollama at http://localhost:11334. "
                "Is it running? Try: ollama serve"
            ) from e
        except Exception as e:
            last_exc = e
            await asyncio.sleep(2 ** attempt)
    raise RuntimeError(f"Embedding failed after 3 attempts: {last_exc}") from last_exc


def embed_sync(text: str) -> list[float]:
    return asyncio.run(embed(text))
