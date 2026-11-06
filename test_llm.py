import os
from graphkit.llm import make_client, model_name

base_url = os.environ.get("LLM_BASE_URL")
model = model_name()
key = os.environ.get("LLM_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""

print("--- Configuration ---")
print(f"Base URL : {base_url}")
print(f"Model    : {model}")
print(f"Key preview: {key[:8]}... (Length: {len(key)})")
if key.startswith('"') or key.endswith('"'):
    print("WARNING: Your API key has literal quote marks around it! Remove them.")

try:
    client = make_client()
    res = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "hi"}],
    )
    print("\nSUCCESS! Model replied:", res.choices[0].message.content)
except Exception as e:
    print("\n--- Failure Details ---")
    print(f"Exception : {type(e).__name__}")
    print(f"Message   : {e}")
    if hasattr(e, "response") and hasattr(e.response, "text"):
        print(f"Response  : {e.response.text}")