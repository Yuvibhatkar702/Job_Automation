import json
import os
import time
import re
import random
import urllib.parse
import argparse
from datetime import datetime
from playwright.sync_api import sync_playwright

import warnings

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=FutureWarning)
        import google.generativeai as genai
except ImportError:
    genai = None

BASE_DIR = "C:/Users/Admin/.gemini/antigravity/scratch/job_assistant"
JOBS_FILE = os.path.join(BASE_DIR, "jobs.json")
PROFILE_FILE = os.path.join(BASE_DIR, "profile.json")
APPLIED_JOBS_FILE = os.path.join(BASE_DIR, "applied_jobs.json")
BLACKLIST_FILE = os.path.join(BASE_DIR, "blacklist_companies.json")
FAILED_JOBS_FILE = os.path.join(BASE_DIR, "failed_jobs.json")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
DEFAULT_RESUME_PATH = "C:/Users/Admin/Documents/Yuvraj_Bhakar_Resume.pdf"

# Priority of platforms
SOURCE_PRIORITY = {
    "Wellfound": 1,
    "Greenhouse": 2,
    "Lever": 3,
    "Company Career Pages": 4,
    "Naukri": 5,
    "LinkedIn": 6
}

def load_json(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_json(filepath, data):
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

def log_action(company, role, source, status, reason=""):
    os.makedirs(LOGS_DIR, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(LOGS_DIR, f"report_{date_str}.log")
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {status} | Company: {company} | Role: {role} | Source: {source} | Reason: {reason}\n"
    with open(log_file, "a") as f:
        f.write(log_entry)

def human_delay(min_s=1.0, max_s=3.0):
    time.sleep(random.uniform(min_s, max_s))

def human_scroll(page):
    try:
        for _ in range(random.randint(1, 3)):
            page.mouse.wheel(0, random.randint(300, 700))
            human_delay(0.5, 1.5)
    except Exception:
        pass

def fallback_is_suitable(text):
    text_lower = text.lower()
    exp_matches = re.findall(r'(\d+)\s*\+?\s*(?:to\s*\d+\s*)?years?\s+(?:of\s+)?experience', text_lower)
    for match in exp_matches:
        try:
            years = int(match)
            if years > 2:
                return False
        except ValueError:
            continue
    
    exclude_keywords = ["senior", "lead", "principal", "architect", "manager"]
    if any(keyword in text_lower[:200] for keyword in exclude_keywords):
         return False
         
    return True

def analyze_job_with_gemini(job_text, profile):
    if not genai or not os.environ.get("GEMINI_API_KEY"):
        print("  Warning: Gemini API not configured. Falling back to simple checks.")
        return fallback_is_suitable(job_text), {}
        
    try:
        prompt = f"""
You are an expert technical recruiter analyzing a job description.

Job Description:
{job_text[:5000]}

Candidate Profile Summary:
Target Roles: {profile.get('preferences', {}).get('target_roles', [])}
Experience: Fresher (0-2 years max)
Skills: {profile.get('skills', [])}

Extract the following details as JSON only, no markdown formatting blocks, just raw JSON:
{{
    "company_name": "extracted name or Unknown",
    "role": "extracted job title or Unknown",
    "location": "extracted location or Unknown",
    "required_skills": ["skill1", "skill2"],
    "experience_required_years": integer (use 0 for fresher, or maximum if a range is given),
    "salary_if_available": "extracted salary or None",
    "match_score": integer (0-100 based on how well this job fits a fresher with the candidate's skills),
    "reasoning": "short explanation of the match score"
}}
"""
        models_to_try = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-1.0-pro', 'gemini-pro']
        response = None
        for m_name in models_to_try:
            try:
                model = genai.GenerativeModel(m_name)
                response = model.generate_content(prompt)
                break
            except Exception:
                continue
                
        if not response:
            raise Exception(f"Failed to find a working Gemini model. Make sure your API key is correct.")
            
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:-3]
        elif text.startswith("```"):
            text = text[3:-3]
            
        data = json.loads(text.strip())
        is_suitable = data.get("match_score", 0) > 75 and data.get("experience_required_years", 99) <= 2
        return is_suitable, data
    except Exception as e:
        print(f"  Gemini analysis failed: {e}")
        return fallback_is_suitable(job_text), {}

def answer_screening_question(page_text, profile_text):
    if not genai or not os.environ.get("GEMINI_API_KEY"):
        return "Yes, I meet the requirements."
        
    prompt = f"""
You are helping a candidate apply for a job.
Here is the text from the application page/chatbot (focus on the end to find the latest question):
...
{page_text[-1500:]}
...

Candidate's Profile details:
{profile_text}

Identify the screening question being asked, and provide a short, direct, and professional answer (maximum 2 sentences) based ONLY on the profile. 
Do not include quotes, prefixes like "Answer:", or extra formatting. Provide ONLY the plain text answer to be typed into the box.
If the question is Yes/No, answer Yes/No and briefly explain.
"""
    models_to_try = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-1.0-pro', 'gemini-pro']
    for m_name in models_to_try:
        try:
            model = genai.GenerativeModel(m_name)
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception:
            continue
    return "Yes, I meet all the requirements."

def fill_text_field(page, selector, value):
    try:
        element = page.query_selector(selector)
        if element and element.is_visible() and not element.is_disabled():
            element.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            human_delay(0.2, 0.5)
            element.fill(value)
            return True
    except Exception:
        pass
    return False

def upload_resume(page, resume_path):
    if not os.path.exists(resume_path):
        print(f"  Warning: Resume file not found at '{resume_path}'.")
        return False
    try:
        file_inputs = page.query_selector_all("input[type='file']")
        for file_input in file_inputs:
            name = (file_input.get_attribute("name") or "").lower()
            id_attr = (file_input.get_attribute("id") or "").lower()
            if any(k in (name + id_attr) for k in ["resume", "cv", "attachment", "document"]):
                file_input.set_input_files(resume_path)
                print(f"  Uploaded resume: {resume_path}")
                human_delay(1.0, 2.0)
                return True
        if file_inputs:
            file_inputs[0].set_input_files(resume_path)
            print(f"  Uploaded resume to first file field: {resume_path}")
            human_delay(1.0, 2.0)
            return True
    except Exception as e:
        print(f"  Error uploading resume: {e}")
    return False

def agentic_form_fill(page, profile):
    if not genai or not os.environ.get("GEMINI_API_KEY"):
        return False
        
    try:
        dom_script = """
        () => {
            let inputs = Array.from(document.querySelectorAll('input, textarea, select'));
            let map = {};
            inputs.forEach((el, index) => {
                if (el.type === 'hidden' || el.style.display === 'none' || el.offsetWidth === 0) return;
                if (!el.id) el.id = 'ai-injected-id-' + index;
                
                let label = '';
                if (el.id) {
                    let l = document.querySelector(`label[for='${el.id}']`);
                    if (l) label = l.innerText;
                }
                if (!label) label = el.getAttribute('aria-label') || el.placeholder || el.name || '';
                
                map['#' + el.id] = { type: el.type, label: label.trim() };
            });
            
            let buttons = Array.from(document.querySelectorAll('button, input[type="submit"], a.btn'));
            let btnMap = {};
            buttons.forEach((el, index) => {
                if (el.style.display === 'none' || el.offsetWidth === 0) return;
                if (!el.id) el.id = 'ai-injected-btn-' + index;
                btnMap['#' + el.id] = el.innerText.trim() || el.value || '';
            });
            return { inputs: map, buttons: btnMap };
        }
        """
        dom_data = page.evaluate(dom_script)
        
        if not dom_data['inputs']:
            return False
            
        prompt = f"""
You are an AI autonomous agent filling out a job application form.
Candidate Profile:
{json.dumps(profile["personal_info"])}

Form Fields Available (Map of Selector -> Field Info):
{json.dumps(dom_data['inputs'], indent=2)}

Visible Buttons Available (Map of Selector -> Button Text):
{json.dumps(dom_data['buttons'], indent=2)}

Task: Provide a JSON object mapping the correct selectors to the values to fill. 
For file upload fields (like Resume/CV), provide the exact string "UPLOAD_RESUME" as the value.
For the button, pick the selector that most likely submits the application or moves to the next step (e.g. 'Submit', 'Next', 'Apply', 'Continue').
Return strictly JSON (no markdown ticks):
{{
    "fills": {{
        "#selector_for_first_name": "Yuvraj",
        "#selector_for_resume": "UPLOAD_RESUME"
    }},
    "submit_button": "#selector_for_submit_button"
}}
"""
        models_to_try = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']
        ai_json = None
        for m_name in models_to_try:
            try:
                model = genai.GenerativeModel(m_name)
                resp = model.generate_content(prompt).text.strip()
                if resp.startswith("```json"): resp = resp[7:-3]
                elif resp.startswith("```"): resp = resp[3:-3]
                ai_json = json.loads(resp.strip())
                break
            except Exception:
                continue
                
        if not ai_json:
            return False
            
        print("  Executing AI Agent actions...")
        for sel, val in ai_json.get("fills", {}).items():
            try:
                el = page.query_selector(sel)
                if el:
                    if val == "UPLOAD_RESUME":
                        el.set_input_files(profile["personal_info"].get("resume_path", ""))
                        print(f"    Uploaded Resume -> {sel}")
                    else:
                        el.fill(str(val))
                        print(f"    Filled '{val}' -> {sel}")
                    human_delay(0.2, 0.5)
            except Exception as ex:
                pass
                
        submit_sel = ai_json.get("submit_button")
        if submit_sel:
            btn = page.query_selector(submit_sel)
            if btn:
                print(f"  Clicking AI identified button: {submit_sel}")
                try:
                    btn.click(force=True, timeout=5000)
                except Exception:
                    btn.evaluate("el => el.click()")
                human_delay(3.0, 5.0)
                return True
                
        return False
    except Exception as e:
        print(f"  Agentic fill error: {e}")
        return False

def fill_linkedin_modal_fields(page, profile, resume_path):
    info = profile["personal_info"]
    text_inputs = page.query_selector_all("input[type='text'], input[type='number']")
    for inp in text_inputs:
        label_el = page.query_selector(f"label[for='{inp.get_attribute('id')}']")
        label_text = label_el.inner_text().lower() if label_el else ""
        
        if "first name" in label_text:
            inp.fill(info["first_name"])
        elif "last name" in label_text:
            inp.fill(info["last_name"])
        elif "email" in label_text:
            inp.fill(info["email"])
        elif "phone" in label_text or "mobile" in label_text:
            inp.fill(info["phone"])
        elif "experience" in label_text or "years of" in label_text:
            inp.fill("1") 
        elif "gpa" in label_text or "cgpa" in label_text:
            inp.fill("8.4")
        human_delay(0.5, 1.5)

    upload_resume(page, resume_path)

def run_easy_apply_flow(page, profile, resume_path):
    try:
        btn_selectors = ".jobs-apply-button, .jobs-s-apply button, button:has-text('Easy Apply'), button[aria-label*='Easy Apply'], button.jobs-apply-button--top-card"
        btn = page.query_selector(btn_selectors)
        if btn:
            btn.click(force=True)
            human_delay(2.0, 3.0)
        else:
            raise Exception("Button not found")
    except Exception:
        print("  Could not click Easy Apply button.")
        return False
        
    steps = 0
    while steps < 10:
        if not page.query_selector(".jobs-easy-apply-modal"):
            print("  Modal closed or application completed.")
            return "applied"
            
        fill_linkedin_modal_fields(page, profile, resume_path)
        
        # Use AI to answer any custom recruiter questions on this stage
        print("  Analyzing modal stage with Agentic AI...")
        agentic_form_fill(page, profile)
        
        # After AI fills fields, try to advance if AI didn't already click Next/Submit
        next_btn = page.query_selector("button[aria-label*='Next'], button[aria-label*='Continue']")
        review_btn = page.query_selector("button[aria-label*='Review']")
        submit_btn = page.query_selector("button[aria-label*='Submit']")
        
        # LinkedIn also uses generic class names for primary buttons in the modal footer
        primary_btn = page.query_selector(".artdeco-modal__actionbar button.artdeco-button--primary")
        
        if submit_btn:
            print("  Clicking Submit automatically...")
            submit_btn.click()
            human_delay(2.0, 3.0)
            return "applied"
        elif review_btn:
            human_delay(0.5, 1.5)
            review_btn.click()
            human_delay(1.5, 2.5)
        elif next_btn:
            human_delay(0.5, 1.5)
            next_btn.click()
            human_delay(1.5, 2.5)
        elif primary_btn:
            human_delay(0.5, 1.5)
            primary_btn.click()
            human_delay(1.5, 2.5)
        else:
            print("  Encountered custom questions or verification. AI could not advance. Please check browser.")
            human_delay(5.0, 5.0) # Give user a moment to see it
            
        steps += 1
    return True

def generate_daily_report():
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(LOGS_DIR, f"report_{date_str}.log")
    if not os.path.exists(log_file):
        print(f"No report available for today ({date_str}).")
        return
        
    print(f"\n=== Daily Application Report ({date_str}) ===")
    applied = 0
    skipped = 0
    failed = 0
    
    with open(log_file, "r") as f:
        for line in f:
            print(line.strip())
            if "APPLIED" in line: applied += 1
            elif "SKIPPED" in line: skipped += 1
            elif "FAILED" in line: failed += 1
            
    print(f"Summary: {applied} Applied, {skipped} Skipped, {failed} Failed.")

def main():
    parser = argparse.ArgumentParser(description="Autonomous Job Application Assistant")
    parser.add_argument("--dry-run", action="store_true", help="Run without user interaction or submission")
    parser.add_argument("--report", action="store_true", help="Generate daily summary report and exit")
    args = parser.parse_args()

    if args.report:
        generate_daily_report()
        return

    profile = load_json(PROFILE_FILE)
    if not profile:
        print("Error: profile.json not found or invalid.")
        return
        
    if genai and os.environ.get("GEMINI_API_KEY"):
        genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
        print("Gemini Pro integration enabled.")
    else:
        print("Warning: GEMINI_API_KEY not found. Using fallback parsing.")

    resume_path = profile["personal_info"].get("resume_path", DEFAULT_RESUME_PATH)
    
    user_data_dir = os.path.join(BASE_DIR, "browser_data")
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0] if context.pages else context.new_page()
        
        # --- LinkedIn Manual Login Pause ---
        print("\nChecking LinkedIn login status...")
        page.goto("https://www.linkedin.com/login", timeout=60000)
        try:
            page.wait_for_url("**/feed/**", timeout=10000)
            print("Already logged in to LinkedIn!")
        except Exception:
            print("\n[ACTION REQUIRED] Please log into LinkedIn in the Chromium browser window.")
            print("Waiting for you to log in...")
            try:
                page.wait_for_url("**/feed/**", timeout=300000) # Wait up to 5 minutes
                print("Login successful! Starting autonomous job search...")
            except Exception:
                print("Login timed out. Exiting.")
                return
        # -----------------------------------
        
        print("Starting Assistant...")
        applied_jobs = load_json(APPLIED_JOBS_FILE)
        blacklist = load_json(BLACKLIST_FILE)
        failed_jobs = load_json(FAILED_JOBS_FILE)
        
        applied_urls = {job["url"].split("?")[0].split("#")[0] for job in applied_jobs}
        failed_urls = {job["url"].split("?")[0].split("#")[0] for job in failed_jobs}
        applied_roles = { (job.get("company", "Unknown").lower(), job.get("role", job.get("title", "Unknown")).lower()) for job in applied_jobs }
        
        roles = profile.get("preferences", {}).get("target_roles", ["Software Developer"])
        locations = profile.get("preferences", {}).get("locations", ["Remote"])
        
        for role_kw in roles:
            for loc_kw in locations:
                import urllib.parse
                search_kw_encoded = urllib.parse.quote(role_kw)
                search_loc_encoded = urllib.parse.quote(loc_kw)
                
                # Pagination loop (Up to 10 pages per role/location to get 100+ jobs)
                for page_num in range(0, 10):
                    start_offset = page_num * 25
                    # f_AL=true -> Easy Apply Only. f_TPR=r86400 -> Past 24 hours Only. distance=100 expands the default 40km filter.
                    search_url = f"https://www.linkedin.com/jobs/search/?keywords={search_kw_encoded}&location={search_loc_encoded}&f_AL=true&f_TPR=r86400&distance=100&start={start_offset}"
                    
                    print(f"\n[LinkedIn Search] Navigating to: {search_url}")
                    try:
                        page.goto(search_url, timeout=60000)
                        human_delay(3.0, 5.0)
                        
                        # Scroll left panel to load lazy cards
                        for _ in range(4):
                            page.evaluate("document.querySelector('.jobs-search-results-list')?.scrollBy(0, 5000)")
                            page.wait_for_timeout(1000)
                            
                    except Exception as e:
                        print(f"  Failed to load search page: {e}")
                        break # Break pagination if page fails to load
                        
                    job_elements = page.query_selector_all(".job-card-container, .jobs-search-results__list-item")
                    if not job_elements:
                        print("  No more jobs found on this page. Moving to next search combination.")
                        break # Break pagination if no jobs exist
                        
                    print(f"  Found {len(job_elements)} job listings on page {page_num}.")
                
                    for i in range(len(job_elements)):
                        try:
                            # Re-query elements to prevent stale element errors
                            cards = page.query_selector_all(".job-card-container, .jobs-search-results__list-item")
                            if i >= len(cards): break
                            card = cards[i]
                            
                            title_el = card.query_selector("a.job-card-list__title, a.job-card-container__link")
                            if not title_el: continue
                            
                            href = title_el.get_attribute("href")
                            if not href: continue
                            job_url = href.split("?")[0].split("#")[0]
                            if job_url.startswith("/"): job_url = "https://www.linkedin.com" + job_url
                            
                            if job_url in applied_urls or job_url in failed_urls:
                                continue
                                
                            job_title = title_el.inner_text().strip()
                            job_platform = "LinkedIn"
                            
                            print(f"\nProcessing: {job_title} ({job_platform})")
                            
                            # Click the card in the left pane to load details in the right pane!
                            card.scroll_into_view_if_needed()
                            try:
                                title_el.click(force=True)
                            except Exception:
                                card.click(force=True)
                                
                            human_delay(2.0, 3.0)
                            
                            # Wait for right panel details to load
                            try:
                                page.wait_for_selector(".jobs-search__job-details--container, .job-view-layout, .jobs-details", timeout=5000)
                            except Exception:
                                pass # Proceed anyway
                                
                            # Extract Company Name from right pane natively
                            comp_el = page.query_selector(".jobs-unified-top-card__company-name, .job-details-jobs-unified-top-card__company-name")
                            company = comp_el.inner_text().strip() if comp_el else "Unknown"
                            role = job_title
                            
                            # Fast Keyword Matching (Bypass Gemini)
                            title_lower = role.lower()
                            
                            non_tech_keywords = ['sales', 'bpo', 'hr', 'marketing', 'teacher', 'data entry', 'officer', 'content writer', 'reporter', 'support', 'customer', 'caller', 'telesales', 'business development', 'bd', 'recruiter', 'manager', 'lead', 'architect', 'principal']
                            tech_keywords = ['software', 'developer', 'engineer', 'python', 'java', 'react', 'node', 'full stack', 'frontend', 'backend', 'programmer', 'it', 'web', 'app', 'fresher', 'intern', 'trainee', 'data', 'ai', 'ml']
                            
                            is_non_tech = any(kw in title_lower for kw in non_tech_keywords)
                            is_tech = any(kw in title_lower for kw in tech_keywords)
                            
                            # Check Company + Role Duplicate
                            if (company.lower(), role.lower()) in applied_roles and company.lower() != "unknown":
                                print(f"  Skipping: Already applied to {role} at {company} (Duplicate Detection)")
                                continue
                            
                            if company in blacklist:
                                print(f"  Skipping: Company '{company}' is blacklisted.")
                                log_action(company, role, job_platform, "SKIPPED", f"Blacklisted company: {company}")
                                continue
                            
                            if is_non_tech:
                                print(f"  Skipping: Detected non-tech role -> {role}")
                                log_action(company, role, job_platform, "SKIPPED", "Non-tech role")
                                continue
                                
                            if not is_tech:
                                print(f"  Skipping: Title doesn't look like a tech role -> {role}")
                                log_action(company, role, job_platform, "SKIPPED", "No tech keywords")
                                continue
                            
                            print(f"  Good match! Proceeding...")
                            
                            if args.dry_run:
                                print("  [Dry Run] Simulating apply and skipping real submission.")
                                job_data = {"url": job_url, "title": job_title, "company": company, "status": "Applied (Dry Run)", "date_applied": time.strftime("%Y-%m-%d %H:%M:%S")}
                                applied_jobs.append(job_data)
                                save_json(APPLIED_JOBS_FILE, applied_jobs)
                                log_action(company, role, job_platform, "APPLIED (DRY-RUN)", "Simulated")
                                continue
                            
                            # Attempt to apply based on platform
                            auto_applied = False
                            
                            # Wait up to 5 seconds for the Easy Apply button to appear in right pane
                            btn_selectors = ".jobs-apply-button, .jobs-s-apply button, button:has-text('Easy Apply'), button[aria-label*='Easy Apply'], button.jobs-apply-button--top-card"
                            try:
                                page.wait_for_selector(btn_selectors, timeout=5000)
                            except Exception:
                                pass
                            
                            easy_apply_btn = page.query_selector(btn_selectors)
                            
                            if easy_apply_btn:
                                print("  Found LinkedIn Easy Apply! Starting modal solver...")
                                if run_easy_apply_flow(page, profile, resume_path) == "applied":
                                    auto_applied = True
                                else:
                                    # Fallback: force close modal if stuck
                                    close_btn = page.query_selector("button[aria-label='Dismiss']")
                                    if close_btn: close_btn.click(force=True)
                                    human_delay(1.0, 2.0)
                                    discard_btn = page.query_selector("button[data-control-name='discard_application_confirm_btn']")
                                    if discard_btn: discard_btn.click(force=True)
                            else:
                                print("  Skipping: No Easy Apply button found (might be an external redirect or blocked).")
                                log_action(company, role, job_platform, "SKIPPED", "Not Easy Apply")
                                continue
                                    
                            if auto_applied:
                                print("  Successfully Auto-Applied!")
                                job_data = {"url": job_url, "title": job_title, "company": company, "status": "Applied", "date_applied": time.strftime("%Y-%m-%d %H:%M:%S")}
                                applied_jobs.append(job_data)
                                save_json(APPLIED_JOBS_FILE, applied_jobs)
                                applied_urls.add(job_url)
                                applied_roles.add((company.lower(), role.lower()))
                                log_action(company, role, job_platform, "APPLIED", "Auto-submitted")
                            else:
                                print("  Failed to fully auto-apply (External redirect or CAPTCHA). Skipping autonomously.")
                                job_data = {"url": job_url, "title": job_title, "company": company, "status": "Failed", "reason": "Failed autonomous apply flow"}
                                failed_jobs.append(job_data)
                                failed_urls.add(job_url)
                                save_json(FAILED_JOBS_FILE, failed_jobs)
                                log_action(company, role, job_platform, "FAILED", "Failed autonomous apply flow")
                                
                        except Exception as e:
                            error_msg = str(e)
                            print(f"  Error processing job: {error_msg}")
                            if "Target page, context or browser has been closed" in error_msg:
                                print("\n[!] Browser was closed manually. Stopping the application loop to prevent mass-failures.")
                                return # Exit the entire nested loop
                                
                            job_data = {"url": getattr(job_url, '', 'unknown'), "title": getattr(job_title, '', 'unknown'), "company": getattr(company, '', 'unknown'), "status": "Failed", "reason": error_msg}
                            failed_jobs.append(job_data)
                            failed_urls.add(job_url)
                            save_json(FAILED_JOBS_FILE, failed_jobs)
                        # 100% Autonomous Mode: Immediately proceed to next job without asking
                        continue
                
        context.close()
    
    print("\nBatch process finished.")
    generate_daily_report()

if __name__ == "__main__":
    main()
