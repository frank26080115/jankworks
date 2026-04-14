import requests
from typing import List


# --- Message class (same structure as before) ---
class Message:
    def __init__(self, msg_id: str, username: str, timestamp: str, content: str):
        self.id = msg_id
        self.username = username
        self.timestamp_str = timestamp
        self.content = content

    def to_dict(self):
        return {
            "username": self.username,
            "timestamp": self.timestamp_str,
            "content": self.content
        }


# --- Ollama interaction ---
def _query_ollama(prompt: str, model: str = "llama3:8b") -> str:
    """
    Sends a prompt to local Ollama and returns the raw response text.
    """
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False
        }
    )

    response.raise_for_status()
    data = response.json()
    return data.get("response", "").strip()


# --- Prompt builder ---
def _build_prompt(message_text: str) -> str:
    return f"""
You are an expert engineering assistant.

Your task is to classify whether a message contains meaningful technical or engineering insight.

A message is USEFUL if it includes:
- Technical explanations
- Quantitative reasoning (numbers, formulas, measurements)
- Design decisions or tradeoffs
- Observations about system behavior
- Problem-solving insights
- Novel techniques or clever ideas

A message is NOT USEFUL if it includes:
- Casual conversation (e.g. "yup", "lol", "nice")
- Social coordination (e.g. "see you there", "good luck")
- Reactions or jokes
- Vague statements without technical detail

Example:

Message:
"You can rotate the accelerometer 45 degrees to get sqrt(2) more measurable range."

Answer:
USEFUL

Message:
"lol that's sick"

Answer:
NOT_USEFUL

Respond ONLY with:
USEFUL
or
NOT_USEFUL

Message:
\"\"\"
{message_text}
\"\"\"
""".strip()


# --- Main filtering function ---
def filter_useful_messages(messages: List[Message],
                           model: str = "llama3:8b",
                           verbose: bool = False) -> List[Message]:
    """
    Filters a list of Message objects using a local Ollama model.

    Default model: llama3:8b

    To switch to Mistral later:
        model="mistral:7b"
    """

    useful_messages = []

    for i, msg in enumerate(messages):
        prompt = _build_prompt(msg.content)

        try:
            result = _query_ollama(prompt, model=model)

            # Normalize response
            result_clean = result.strip().upper()

            if verbose:
                print(f"[{i}] {msg.username}: {result_clean}")

            if result_clean == "USEFUL":
                useful_messages.append(msg)

        except Exception as e:
            if verbose:
                print(f"[{i}] ERROR: {e}")

    return useful_messages
