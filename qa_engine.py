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
    q_lower = question.lower()
    for k, v in memory.items():
        if normalize_question(k) == norm_q:
            # If cached value is 'Yes' or 'No' but the question asks for a number, ignore toxic cache
            if str(v).lower() in ["yes", "no"] and any(x in q_lower for x in ["(days)", "in days", "how soon", "np in days", "official np", "out of 5", "/5", "scale of 1 to 5", "out of 10", "/10", "scale of 1 to 10", "rate", "rating", "how many years", "years of", "salary", "ctc"]):
                return ""
            return v
    return ""

def save_qa_pair(question: str, answer: str):
    q_lower = question.lower()
    # Guard against caching 'Yes' or 'No' for numeric or rating fields
    if str(answer).strip().lower() in ["yes", "no"] and any(x in q_lower for x in ["(days)", "in days", "how soon", "np in days", "official np", "out of 5", "/5", "scale of 1 to 5", "out of 10", "/10", "scale of 1 to 10", "rate", "rating", "how many years", "years of", "salary", "ctc"]):
        return
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

        # 1b. Check for explicit disqualifiers inside option labels (e.g. "Student (We do NOT hire students)")
        if any(any(d in opt for d in ["do not hire", "not eligible", "not hire students"]) for opt in opt_lowers):
            for idx, opt in enumerate(opt_lowers):
                if not any(d in opt for d in ["do not hire", "not eligible", "not hire students"]):
                    if any(pos in opt for pos in ["graduate", "eligible", "yes", "bachelor", "b.tech", "degree"]):
                        return str(idx)
            for idx, opt in enumerate(opt_lowers):
                if not any(d in opt for d in ["do not hire", "not eligible", "not hire students"]):
                    return str(idx)

        # 2. Positive screening (Disqualifiers if answered No)
        # Shifts, relocation, office work, bond, background checks, skill familiarity, licenses
        if any(pos in q_lower for pos in [
            "shift", "night", "rotational", "relocat", "open to", "comfortable",
            "bond", "commit", "travel", "attend", "onsite", "office", "fresher",
            "immediate", "fulltime", "full time", "experience with", "hands-on", "know",
            "programming", "background check", "drug", "eligible", "authorized",
            "two-wheeler", "two wheeler", "2-wheeler", "2 wheeler", "license", "licence",
            "driver", "driving", "speak", "fluent", "proficient", "language"
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

        # 6. Education options (check question keywords OR if options clearly represent degrees)
        has_degree_opts = any(any(d in opt for d in ["b.tech", "btech", "b.e", "bca", "mca", "diploma"]) for opt in opt_lowers)
        if has_degree_opts or any(k in q_lower for k in ["education", "qualification", "degree", "graduation"]):
            # Pass 1: Specific B.Tech / B.E. in Computer Science / IT
            for idx, opt in enumerate(opt_lowers):
                if any(t in opt for t in ["b.tech", "btech", "b.e", "be/", "be ", "bachelor"]) and any(cs in opt for cs in ["computer science", "cs/it", "/ it", "/it", "information technology"]) and "other" not in opt:
                    return str(idx)
            # Pass 2: B.Tech / B.E. / Bachelor / Engineering (excluding BCA/BSc/Diploma/Others)
            for idx, opt in enumerate(opt_lowers):
                if any(t in opt for t in ["b.tech", "btech", "b.e", "be/", "be ", "bachelor", "graduate", "information technology"]) and not any(ex in opt for ex in ["bca", "bsc", "b.sc", "mca", "msc", "diploma", "other"]):
                    return str(idx)
            # Pass 3: Any B.Tech / B.E. / Bachelor / Graduate
            for idx, opt in enumerate(opt_lowers):
                if any(t in opt for t in ["b.tech", "btech", "b.e", "be/", "be ", "bachelor", "graduate", "information technology"]):
                    return str(idx)

        # 7. Travel percentage options
        if "travel" in q_lower and any("%" in o for o in opt_lowers):
            for idx, opt in enumerate(opt_lowers):
                if "100%" in opt:
                    return str(idx)
            for idx, opt in enumerate(opt_lowers):
                if any(x in opt for x in ["75%", "50%"]):
                    return str(idx)
    else:
        # ── Deterministic checks for non-option numeric / specific inputs ──
        if any(k in q_lower for k in ["immediate joining", "join immediately", "available to join", "ready to join", "immediate joiner", "can you join"]):
            return "Yes"
        if any(k in q_lower for k in ["do you speak", "fluent in", "know english", "know hindi", "know marathi", "know malayalam"]):
            return "Yes"
        if any(k in q_lower for k in ["are you currently in", "currently residing in", "located in", "willing to relocate"]):
            return "Yes"
        if any(k in q_lower for k in ["2 wheeler", "two wheeler", "licence", "license"]):
            return "Yes"
        if any(k in q_lower for k in ["do you have experience", "have experience", "any experience", "hands-on experience", "hands on experience", "prior experience", "knowledge of", "familiar with", "worked on", "worked with"]):
            if not any(k in q_lower for k in ["how many", "years", "number of", "duration"]):
                return "Yes"
        if any(k in q_lower for k in ["(days)", "in days", "how soon can you fill", "np in days", "official np", "serving notice in days"]):
            return "0"
        if any(k in q_lower for k in ["out of 5", "/5", "scale of 1 to 5", "rating out of 5"]):
            return "5" if ("english" in q_lower or "communication" in q_lower) else "4"
        if any(k in q_lower for k in ["out of 10", "/10", "scale of 1 to 10"]):
            return "8"
        if any(k in q_lower for k in ["rate your", "rate yourself"]):
            return "4"
        if any(k in q_lower for k in ["how many years", "years of", "experience in years"]):
            if any(s in q_lower for s in ["fullstack", "full stack", "react", "node", "javascript", "python", "java", "web", "frontend", "backend"]):
                return "1"
            return "0"
        if any(k in q_lower for k in ["current monthly salary", "current salary per month"]):
            return "0"
        if any(k in q_lower for k in ["expected monthly salary", "expected salary per month"]):
            return "30000"
        if any(k in q_lower for k in ["current ctc", "current salary", "present ctc"]):
            return "0"
        if any(k in q_lower for k in ["expected ctc", "expected salary", "desired salary"]):
            if any(u in q_lower for u in ["lac", "lakh", "lpa"]):
                return "3.5"
            return "350000"

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
- If it asks about notice period in days or how soon to join in days, answer "0".
- If it asks to rate skills out of 5, answer "5" for English and "4" for coding / technical / system design.
- If it asks to rate skills out of 10, answer "8".
- If it asks about experience in years or numeric experience, answer "0".
- If it asks about CTC/Salary, answer "3.5 LPA" or "350000", or "0" if asking current.
- If it asks for City or Location, answer "Pune".
- IMPORTANT: If the question expects a number (e.g. days, years, ratings, score), NEVER return text or "Yes". Return ONLY digits.
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
    if any(k in q for k in ["immediate joining", "join immediately", "available to join", "ready to join", "can you join"]):
        return "Yes"
    if any(k in q for k in ["do you speak", "fluent in", "licence", "license"]):
        return "Yes"
    if any(k in q for k in ["do you have experience", "have experience", "any experience", "hands-on experience", "hands on experience", "prior experience", "knowledge of", "familiar with", "worked on", "worked with"]):
        if not any(k in q for k in ["how many", "years", "number of", "duration"]):
            return "Yes"
    if any(k in q for k in ["(days)", "in days", "how soon", "np in days", "official np", "serving notice in days", "notice period in days", "notice in days"]):
        return "0"
    if any(k in q for k in ["out of 5", "/5", "scale of 1 to 5", "rating out of 5"]):
        return "5" if ("english" in q or "communication" in q) else "4"
    if any(k in q for k in ["out of 10", "/10", "scale of 1 to 10"]):
        return "8"
    if any(k in q for k in ["rate your", "rate yourself"]):
        return "4"
    if any(k in q for k in ["how many years", "years of", "experience in years", "number of years"]):
        if any(s in q for s in ["fullstack", "full stack", "react", "node", "javascript", "python", "java", "web", "frontend", "backend"]):
            return "1"
        return "0"
    if any(k in q for k in ["experience", "years", "how many"]):
        return "0"
    if any(k in q for k in ["current monthly salary", "current salary per month"]):
        return "0"
    if any(k in q for k in ["expected monthly salary", "expected salary per month"]):
        return "30000"
    if any(k in q for k in ["current ctc", "current salary", "present ctc"]):
        return "0"
    if any(k in q for k in ["expected ctc", "expected salary", "package"]):
        return "350000"
    if any(k in q for k in ["notice period", "notice"]):
        return "0"
    if any(k in q for k in ["city", "location", "where"]):
        return "Pune"
    if any(k in q for k in ["state"]):
        return "Maharashtra"
    if any(k in q for k in ["country"]):
        return "India"
    if any(k in q for k in ["postal", "zip", "pin code", "pincode"]):
        return "411001"
    if any(k in q for k in ["referred", "referral"]):
        return "None"
    if any(k in q for k in ["degree", "qualification"]):
        return "B.Tech Information Technology"
    if any(k in q for k in ["passing", "year of grad", "graduation year"]):
        return "2026"
    if any(k in q for k in ["why do you want", "pursue a career", "career in", "interested in this role", "why should we hire", "about yourself", "web development"]):
        return "I have a strong foundation in full-stack development with hands-on project experience in React, JavaScript, Node.js, and Python, and I am passionate about building real-world web applications."
    return "Yes"

if __name__ == "__main__":
    print("Testing QA Engine:")
    print("Q: What is your notice period?")
    print("A:", answer_hr_question("What is your notice period?"))

