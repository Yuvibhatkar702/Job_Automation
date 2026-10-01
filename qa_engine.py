import os
import json
import re
from ai_provider import ask_ai
from profile_manager import get_candidate_profile_prompt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QA_MEMORY_PATH = os.path.join(BASE_DIR, "qa_memory.json")

def load_qa_memory() -> dict:
    if os.path.exists(QA_MEMORY_PATH):
        try:
            with open(QA_MEMORY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Error loading qa_memory.json: {e}")
    return {}

def save_qa_memory(data: dict):
    try:
        with open(QA_MEMORY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[!] Error saving qa_memory.json: {e}")

def normalize_question(q: str) -> str:
    cleaned = re.sub(r'[^\w\s]', '', q.lower()).strip()
    return " ".join(cleaned.split())

def get_cached_answer(question: str) -> str:
    memory = load_qa_memory()
    norm_q = normalize_question(question)
    for k, v in memory.items():
        if normalize_question(k) == norm_q:
            return v
    return ""

def save_qa_pair(question: str, answer: str):
    memory = load_qa_memory()
    norm_q = normalize_question(question)
    memory[norm_q] = answer
    save_qa_memory(memory)

def answer_hr_question(question: str, options: list = None) -> str:
    # ── Deterministic screening heuristics ────────────────────────────────
    q_lower = question.lower()
    
    if options:
        opt_lowers = [str(o).lower().strip() for o in options]
        
        # 1. Negative screening (Disqualifiers if answered Yes)
        if any(neg in q_lower for neg in ["backlog", "criminal", "convicted", "sponsorship", "visa sponsor", "currently serving notice", "previous employee"]):
            for idx, opt in enumerate(opt_lowers):
                if opt in ["no", "no, i don't", "no, i am not", "none", "false"]:
                    return str(idx)

        # 2. Positive screening (Disqualifiers if answered No)
        # Shifts, relocation, office work, bond, background checks, skill familiarity
        if any(pos in q_lower for pos in [
            "shift", "night", "rotational", "relocat", "open to", "comfortable",
            "bond", "commit", "travel", "attend", "onsite", "office", "fresher",
            "immediate", "fulltime", "full time", "experience with", "hands-on", "know",
            "programming", "background check", "drug", "eligible", "authorized"
        ]):
            for idx, opt in enumerate(opt_lowers):
                if opt in ["yes", "yes, i am", "yes, i do", "willing", "comfortable", "agree", "true", "open to relocate"]:
                    return str(idx)
            for idx, opt in enumerate(opt_lowers):
                if opt.startswith("yes"):
                    return str(idx)

        # 3. Notice period options
        if any(k in q_lower for k in ["notice", "availability", "join", "earliest"]):
            for idx, opt in enumerate(opt_lowers):
                if any(x in opt for x in ["immediate", "0 day", "15 day", "1 month or less", "less than 15", "serving notice"]):
                    return str(idx)

        # 4. Experience options
        if any(k in q_lower for k in ["experience", "years of", "how many years"]):
            for idx, opt in enumerate(opt_lowers):
                if any(x in opt for x in ["0-1", "0 to 1", "0 to 2", "0 - 1", "fresher", "less than 1", "entry"]):
                    return str(idx)
            for idx, opt in enumerate(opt_lowers):
                if opt in ["0", "1"]:
                    return str(idx)

        # 5. CTC / Salary options
        if any(k in q_lower for k in ["ctc", "salary", "lakhs", "lacs", "package"]):
            for idx, opt in enumerate(opt_lowers):
                if any(x in opt for x in ["fresher", "0-3", "0 to 3", "less than 3", "3-5", "as per company"]):
                    return str(idx)

        # 6. Education options
        if any(k in q_lower for k in ["education", "qualification", "degree", "graduation"]):
            for idx, opt in enumerate(opt_lowers):
                if any(x in opt for x in ["b.tech", "b.e", "bachelor", "graduate", "information technology"]):
                    return str(idx)

    cached = get_cached_answer(question)
    if cached:
        print(f"  [QA Memory Hit]: {cached}")
        return cached

    profile = get_candidate_profile_prompt()
    system_prompt = "You are an expert HR response AI applying for a job on behalf of a candidate."
    
    prompt = f"""
Candidate Profile:
{profile}

Question asked by recruiter/bot: "{question}"

INSTRUCTIONS:
- You are applying on behalf of Yuvraj Bhakar, a 2026 B.Tech IT graduate, fresher with 1 year internship experience.
- For screening questions (shifts, relocation, availability, onsite work, bonds), ALWAYS pick the positive/affirmative answer (Yes) to avoid disqualification.
- If it asks about notice period, answer "0 Days" or "Immediate".
- If it asks about experience, answer "0" or "0-1 Years".
- If it asks about CTC/Salary, answer "3.5 LPA" or "0" if asking current.
"""
    if options:
        options_formatted = "\n".join([f"{idx}: {opt}" for idx, opt in enumerate(options)])
        prompt += f"\nYou MUST select one of the following options by returning ONLY its index number (e.g. 0 or 1):\n{options_formatted}"
    else:
        prompt += "\nProvide ONLY the short answer text suitable for a form or chat input."

    try:
        res = ask_ai(prompt, system_prompt=system_prompt).strip()
        if options:
            match = re.search(r'\d+', res)
            idx = int(match.group()) if match else 0
            if 0 <= idx < len(options):
                answer = str(idx)
            else:
                answer = "0"
        else:
            answer = res.replace('"', '').strip()
            if not answer:
                answer = get_smart_fallback(question)

        save_qa_pair(question, answer)
        return answer
    except Exception as e:
        print(f"  [!] QA Engine Error: {e}")
        return get_smart_fallback(question, options)

def get_smart_fallback(question, options=None):
    if options:
        # If options contain 'Yes', return its index
        for idx, opt in enumerate(options):
            if "yes" in str(opt).lower():
                return str(idx)
        return "0"
    q = question.lower()
    if any(k in q for k in ["experience", "years", "how many"]):
        return "0"
    if any(k in q for k in ["current ctc", "current salary"]):
        return "0"
    if any(k in q for k in ["expected ctc", "expected salary", "package"]):
        return "350000"
    if any(k in q for k in ["notice", "availability", "join", "earliest", "start date"]):
        return "Immediate"
    if any(k in q for k in ["city", "location", "where"]):
        return "Pune"
    if any(k in q for k in ["referred", "referral"]):
        return "None"
    if any(k in q for k in ["degree", "qualification"]):
        return "B.Tech Information Technology"
    if any(k in q for k in ["passing", "year of grad"]):
        return "2026"
    return "Yes"

if __name__ == "__main__":
    print("Testing QA Engine:")
    print("Q: What is your notice period?")
    print("A:", answer_hr_question("What is your notice period?"))

