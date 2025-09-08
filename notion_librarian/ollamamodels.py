import requests
from openai import OpenAI

def list_ollama_models(host: str = "http://localhost:11434") -> list[str]:
    """
    Return a list of available Ollama model names.
    """
    url = f"{host}/api/tags"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]
    except Exception as e:
        print(f"Error fetching models: {e}")
        return []

def has_ollama_model(model_name: str, host: str = "http://localhost:11434") -> bool:
    """
    Check if the given model name is available in Ollama.
    """
    models = list_ollama_models(host)
    return model_name in models

def is_local(client: OpenAI) -> bool:
    url = getattr(client, "base_url", None)
    if url is None:
        return False  # default OpenAI SDK points online
    return "127.0.0.1" in url or "localhost" in url

if __name__ == "__main__":
    from llmcall import ensure_ollama_up
    ensure_ollama_up()
    x = list_ollama_models()
    print(x)
