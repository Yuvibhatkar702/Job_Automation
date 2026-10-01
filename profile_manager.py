import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_PATH = os.path.join(BASE_DIR, "profile.json")

def load_profile_data() -> dict:
    if os.path.exists(PROFILE_PATH):
        try:
            with open(PROFILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Error reading profile.json: {e}")
    return {}

def get_candidate_profile_prompt() -> str:
    p = load_profile_data()
    if not p:
        return """
Candidate Name: Yuvraj Bhatkar
Role: Fresher / Software Developer
Education: B.Tech Information Technology (2026 Graduate)
Experience: 0 Years Full-time, 1 Year Internship Experience
Skills: Java, Python, JavaScript, React.js, Node.js, Express.js, MongoDB, SQL, REST APIs, Tailwind CSS, Fast APIs, Data Structures, OOP
Notice Period: Immediate (0 Days)
Location: Pune, Mumbai, Remote India
Expected CTC: As per industry standards for freshers
"""

    personal = p.get("personal_info", {})
    edu = p.get("education", [])
    exp = p.get("experience", [])
    skills = p.get("skills", {})
    pref = p.get("preferences", {})

    edu_str = "\n".join([f"- {e.get('degree')} in {e.get('major')} ({e.get('start_date')} - {e.get('end_date')}, CGPA/Percentage: {e.get('cgpa', e.get('percentage', 'N/A'))})" for e in edu])
    exp_str = "\n".join([f"- {ex.get('role')} at {ex.get('company')} ({ex.get('start_date')} - {ex.get('end_date')}):\n  " + "\n  ".join(ex.get('summary', [])) for ex in exp])
    
    all_skills = []
    for category, items in skills.items():
        if isinstance(items, list):
            all_skills.extend(items)
    skills_str = ", ".join(all_skills)

    prompt = f"""
CANDIDATE PROFILE:
Name: {personal.get('full_name', 'Yuvraj Bhatkar')}
Email: {personal.get('email', '')}
Phone: {personal.get('phone', '')}
Location: {personal.get('address', 'Pune / Mumbai, India')}

EDUCATION:
{edu_str}

INTERNSHIP & WORK EXPERIENCE:
{exp_str}

TECHNICAL SKILLS:
{skills_str}

PREFERENCES:
Target Roles: {", ".join(pref.get('target_roles', []))}
Preferred Locations: {", ".join(pref.get('locations', []))}
Experience Level: Fresher (0 Years full-time, 1 year internship experience)
Notice Period: Immediate Joiner (0 Days)
Relocation: Willing to relocate
"""
    return prompt.strip()

if __name__ == "__main__":
    print(get_candidate_profile_prompt())
