import os
import json
import urllib.request
import urllib.error

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
_MISTRAL_DISABLED = False

def load_config():
    config = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                config = json.load(f)
        except:
            pass
    return config

def ask_ai(prompt: str, system_prompt: str = "You are an expert HR response AI for job applications.") -> str:
    """
    Primary AI query function. Priority:
    1. Mistral AI API (MISTRAL_API_KEY)
    2. Gemini AI API (GEMINI_API_KEY) fallback
    """
    global _MISTRAL_DISABLED
    config = load_config()
    mistral_key = os.environ.get("MISTRAL_API_KEY") or config.get("MISTRAL_API_KEY")
    if mistral_key and not _MISTRAL_DISABLED:
        url = "https://api.mistral.ai/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {mistral_key}"
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": "mistral-small-latest",
            "messages": messages,
            "temperature": 0.2
        }
        
        import time
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    res_data = json.loads(response.read().decode('utf-8'))
                    content = res_data["choices"][0]["message"]["content"]
                    return content
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt == 0:
                    time.sleep(2.0)
                    continue
                if e.code in (401, 402):
                    _MISTRAL_DISABLED = True
                    print(f"  [!] Mistral HTTP Error: {e.code} - {e.reason} (Disabling Mistral for this session; using fallback/heuristics)")
                    break
                print(f"  [!] Mistral HTTP Error: {e.code} - {e.reason}")
                break
            except Exception as e:
                print(f"  [!] Mistral API Request Failed: {e}")
                break
            
    # Fallback to Gemini AI if Mistral Key is not set or fails
    gemini_key = os.environ.get("GEMINI_API_KEY") or config.get("GEMINI_API_KEY")
    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            try:
                model = genai.GenerativeModel('gemini-2.5-flash')
            except:
                model = genai.GenerativeModel('gemini-1.5-flash')
                
            full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
            res = model.generate_content(full_prompt)
            return res.text
        except Exception as e:
            print(f"  [!] Gemini AI Fallback Failed: {e}")
            
    return ""

def is_ai_available() -> bool:
    config = load_config()
    return bool(os.environ.get("MISTRAL_API_KEY") or config.get("MISTRAL_API_KEY") or os.environ.get("GEMINI_API_KEY") or config.get("GEMINI_API_KEY"))
