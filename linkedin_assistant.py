import os
import json
import time
import sys
import random
import argparse
from playwright.sync_api import sync_playwright
from universal_form_filler import solve_complex_form_with_ai
from ai_provider import ask_ai, is_ai_available
from profile_manager import get_candidate_profile_prompt
from qa_engine import answer_hr_question

def _get_field_label(el):
    """Extract the human-readable label for a form field."""
    label_text = ""
    try:
        # Try aria-label
        label_text = el.get_attribute("aria-label") or ""
    except:
        pass
    if not label_text:
        try:
            # Try associated <label>
            el_id = el.get_attribute("id") or ""
            if el_id:
                label_el = el.evaluate_handle(f"el => document.querySelector('label[for=\"{el_id}\"]')")
                if label_el:
                    label_text = label_el.inner_text().strip()
        except:
            pass
    if not label_text:
        try:
            # Try parent label or closest text container
            parent = el.evaluate_handle("el => el.closest('label, .jobs-easy-apply-form-section__grouping, fieldset, .fb-dash-form-element, div.mt2')")
            if parent:
                label_text = parent.inner_text().strip()
        except:
            pass
    if not label_text:
        try:
            label_text = el.get_attribute("placeholder") or ""
        except:
            pass
    return label_text.lower()

def _is_profile_field(label):
    """Check if the label matches a known profile/contact field (not a screening question)."""
    profile_keywords = [
        "city", "location", "country", "state", "postal", "zip", "pin code",
        "address", "phone", "mobile", "email", "first name", "last name",
        "full name", "name", "linkedin", "website", "github"
    ]
    return any(kw in label for kw in profile_keywords)

def _get_profile_value_for_field(label, profile_data):
    """Return the correct profile value for a known field."""
    personal = profile_data.get("personal_info", {})
    
    if "email" in label:
        return personal.get("email", "yuvibhatkar702@gmail.com")
    if "phone" in label or "mobile" in label:
        return personal.get("phone", "+917767055408")
    if "first name" in label:
        return personal.get("first_name", "Yuvraj")
    if "last name" in label:
        return personal.get("last_name", "Bhakar")
    if "full name" in label or label == "name":
        return personal.get("full_name", "Yuvraj Bhakar")
    if "linkedin" in label:
        return personal.get("linkedin", "https://www.linkedin.com/in/yuvraj-bhatkar-b50a0327b")
    if "github" in label or "website" in label or "portfolio" in label:
        return personal.get("github", "https://github.com/Yuvibhatkar702")
    if "postal" in label or "zip" in label or "pin" in label:
        return "411001"  # Pune postal code
    if "country" in label:
        return "India"
    if "state" in label:
        return personal.get("state", "Maharashtra")
    if "city" in label or "location" in label:
        return personal.get("city", "Pune")
    if "address" in label:
        return personal.get("address", "Pune, Maharashtra, India")
    return ""

def _select_dropdown_best_match(select_el, target_text):
    """Select the best matching option in a <select> dropdown."""
    try:
        options = select_el.query_selector_all("option")
        target_lower = target_text.lower().strip()
        
        # First: try exact or substring match
        for opt in options:
            opt_text = opt.inner_text().strip()
            opt_val = opt.get_attribute("value") or ""
            if not opt_text or opt_text.lower() in ["select", "select an option", "--", ""]:
                continue
            if target_lower in opt_text.lower() or opt_text.lower() in target_lower:
                select_el.select_option(value=opt_val) if opt_val else select_el.select_option(label=opt_text)
                return True
        
        # Second: first real option as fallback
        for opt in options:
            opt_text = opt.inner_text().strip()
            opt_val = opt.get_attribute("value") or ""
            if opt_text and opt_text.lower() not in ["select", "select an option", "--", ""]:
                select_el.select_option(value=opt_val) if opt_val else select_el.select_option(label=opt_text)
                return True
    except Exception as e:
        print(f"    [!] Dropdown selection error: {e}")
    return False

def solve_linkedin_easy_apply(page, profile):
    print("  [AI] Initiating LinkedIn Easy Apply Solver...")
    if not is_ai_available():
        print("  [!] No AI API key available. Cannot auto-fill.")
        return False

    from profile_manager import load_profile_data
    profile_data = load_profile_data()

    for step in range(12):  # Max 12 steps in modal
        time.sleep(2)
        
        # Detect modal — LinkedIn Easy Apply or third-party embedded forms
        modal = page.query_selector(".jobs-easy-apply-modal, div[data-test-modal-id='easy-apply-modal'], div.jobs-easy-apply-content")
        
        if not modal:
            # Check if successful (modal closed and success banner present)
            success_msg = page.query_selector("h3:has-text('Application sent'), div:has-text('Application submitted'), span:has-text('applied')")
            return bool(success_msg)
            
        # ── Step 1: Collect all visible form fields ────────────────────────
        inputs = modal.query_selector_all("input:not([type='hidden']):not([type='file']), textarea, select")
        
        if inputs:
            filled_count = 0
            ai_questions = []  # Fields that need AI (screening questions)
            
            for idx, el in enumerate(inputs):
                try:
                    tag = el.evaluate("el => el.tagName").lower()
                    el_type = el.get_attribute("type") or "text"
                    
                    if el_type in ["hidden", "file", "submit"]:
                        continue
                    
                    label = _get_field_label(el)
                    
                    # Check if already filled
                    current_value = ""
                    try:
                        if tag == "select":
                            current_value = el.evaluate("el => el.options[el.selectedIndex]?.text || ''").strip()
                            if current_value.lower() in ["select", "select an option", "--", ""]:
                                current_value = ""
                        else:
                            current_value = el.input_value().strip()
                    except:
                        pass
                    
                    if current_value and el_type not in ["checkbox", "radio"]:
                        continue  # Already filled, skip
                    
                    # ── Profile fields: fill directly from profile ──────────
                    if _is_profile_field(label):
                        value = _get_profile_value_for_field(label, profile_data)
                        if value:
                            if tag == "select":
                                _select_dropdown_best_match(el, value)
                                filled_count += 1
                                print(f"    [Profile Fill] {label[:40]} → {value}")
                            else:
                                el.fill(value)
                                filled_count += 1
                                print(f"    [Profile Fill] {label[:40]} → {value}")
                            continue
                    
                    # ── Screening questions: queue for AI ───────────────────
                    # Get full context text for the question
                    context_text = label
                    try:
                        parent = el.evaluate_handle("el => el.closest('.jobs-easy-apply-form-section__grouping, fieldset, .pb4, .mt2, div')")
                        if parent:
                            context_text = parent.inner_text().strip()
                    except:
                        pass
                    
                    ai_questions.append({
                        "index": idx,
                        "tag": tag,
                        "type": el_type,
                        "label": label[:100],
                        "context_text": context_text[:200]
                    })
                    
                except Exception as e:
                    pass
            
            # ── Step 2: Send screening questions to AI ─────────────────────
            if ai_questions:
                prompt = f"""
You are an AI helping a candidate apply for a job on LinkedIn.

CANDIDATE PROFILE:
{profile}

The application form has the following UNANSWERED fields. Answer each based on the profile.
Fields:
{json.dumps(ai_questions, indent=2)}

CRITICAL RULES:
- For experience questions: answer "0" or "0 years" or "1" (for internship)
- For salary/CTC questions: answer "As per industry standards" or "0" for current CTC
- For notice period: answer "0" or "Immediate"
- For city/location: answer "Pune" 
- For "Why do you want to work here": give a 1-sentence professional answer
- For yes/no questions: answer "Yes" if it benefits the candidate
- Return ONLY a JSON array of objects with "index" and "value"
- For select dropdowns, return the EXACT option text to select
- For checkboxes/radios, return boolean true/false
"""
                try:
                    res_text = ask_ai(prompt, system_prompt="You are an AI assistant filling out a job application. Give concise, accurate answers.")
                    text = res_text.replace('```json', '').replace('```', '').strip()
                    answers = json.loads(text)
                    
                    for ans in answers:
                        idx = ans.get("index")
                        val = ans.get("value")
                        if idx is not None and idx < len(inputs):
                            el = inputs[idx]
                            q = ai_questions[[q["index"] for q in ai_questions].index(idx)] if idx in [q["index"] for q in ai_questions] else None
                            if not q:
                                continue
                            
                            if q["type"] in ["checkbox", "radio"]:
                                if val:
                                    try:
                                        el.evaluate("el => { const l = el.closest('label') || el; l.click(); }")
                                    except:
                                        try: el.click(force=True)
                                        except: pass
                            elif q["tag"] == "select":
                                try:
                                    _select_dropdown_best_match(el, str(val))
                                except:
                                    pass
                            else:
                                try:
                                    el.fill(str(val))
                                    filled_count += 1
                                    print(f"    [AI Fill] {q['label'][:40]} → {str(val)[:50]}")
                                except:
                                    pass
                except Exception as e:
                    print(f"  [!] AI Form Fill Error: {e}")
                    # Fallback: fill remaining empty fields with smart defaults
                    for q in ai_questions:
                        idx = q["index"]
                        el = inputs[idx]
                        label = q.get("label", "")
                        try:
                            if q["tag"] in ["input", "textarea"]:
                                current = el.input_value().strip()
                                if not current:
                                    if "experience" in label or "year" in label:
                                        el.fill("0")
                                    elif "salary" in label or "ctc" in label or "compensation" in label:
                                        el.fill("0")
                                    elif "notice" in label:
                                        el.fill("0")
                                    elif "city" in label or "location" in label:
                                        el.fill("Pune")
                                    else:
                                        el.fill("Fresher / Immediate joiner")
                        except:
                            pass
        
        # ── Step 3: Click Next / Review / Submit ───────────────────────────
        # Try Submit first
        submit_btn = modal.query_selector("button[aria-label='Submit application'], button span:has-text('Submit application'), button span:has-text('Submit')")
        if submit_btn and submit_btn.is_visible():
            print("  [AI] Submitting application...")
            submit_btn.click(force=True)
            time.sleep(3)
            return True
        
        # Try Next / Review
        next_btn = modal.query_selector("button[aria-label='Continue to next step'], button[aria-label='Review your application'], button span:has-text('Next'), button span:has-text('Review'), footer button.artdeco-button--primary")
        
        if next_btn and next_btn.is_visible():
            next_btn.click(force=True)
            time.sleep(2)
            
            # Check for validation errors
            err = modal.query_selector(".artdeco-inline-feedback--error, .fb-dash-form-element__error-field, div[class*='error']")
            if err and err.is_visible():
                err_text = err.inner_text().strip()
                print(f"  [!] Validation error: {err_text}")
                
                # Smart fallback: fill remaining empty required fields
                empty_inputs = modal.query_selector_all("input:not([type='hidden']):not([type='file']), textarea, select")
                for inp in empty_inputs:
                    try:
                        tag = inp.evaluate("el => el.tagName").lower()
                        label = _get_field_label(inp)
                        
                        if tag == "select":
                            current = inp.evaluate("el => el.options[el.selectedIndex]?.text || ''").strip()
                            if current.lower() in ["select", "select an option", "--", ""]:
                                _select_dropdown_best_match(inp, _get_profile_value_for_field(label, profile_data) or "India")
                        else:
                            current = inp.input_value().strip()
                            if not current:
                                # Use profile value if known, else smart default
                                val = _get_profile_value_for_field(label, profile_data)
                                if not val:
                                    if "experience" in label or "year" in label:
                                        val = "0"
                                    elif "salary" in label or "ctc" in label:
                                        val = "0"
                                    elif "notice" in label:
                                        val = "0"
                                    else:
                                        val = "N/A"
                                inp.fill(val)
                                print(f"    [Fallback Fill] {label[:40]} → {val}")
                    except:
                        pass
                
                # Retry click
                time.sleep(1)
                try:
                    next_btn.click(force=True)
                    time.sleep(2)
                    err2 = modal.query_selector(".artdeco-inline-feedback--error, .fb-dash-form-element__error-field")
                    if err2 and err2.is_visible():
                        print("  [!] Cannot resolve validation error. Aborting.")
                        close_btn = modal.query_selector("button[aria-label='Dismiss'], .artdeco-modal__dismiss")
                        if close_btn:
                            close_btn.click(force=True)
                            time.sleep(1)
                        discard_btn = page.query_selector("button[data-control-name='discard_application_confirm_btn'], button:has-text('Discard'), button span:has-text('Discard')")
                        if discard_btn and discard_btn.is_visible():
                            discard_btn.click(force=True)
                        return False
                except:
                    pass
        else:
            print("  [!] Could not find Next/Submit button in modal. Aborting.")
            break
            
    return False

# Setup directories and files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMIUM_DATA_DIR = os.path.join(BASE_DIR, "linkedin_data")
APPLIED_JOBS_FILE = os.path.join(BASE_DIR, "linkedin_applied.json")
FAILED_JOBS_FILE = os.path.join(BASE_DIR, "linkedin_failed.json")
REPORT_FILE = os.path.join(BASE_DIR, "linkedin_final_report.md")

# Dynamic Candidate Profile
MCANDIDATE_PROFILE = get_candidate_profile_prompt()

RESUME_PATH = "Resume.pdf" # Make sure this exists or user uploads manually

# Helpers
def human_delay(min_sec=1.0, max_sec=3.0):
    time.sleep(random.uniform(min_sec, max_sec))

def save_json(filepath, data):
    with open(filepath, "w") as f:
        json.dump(data, f, indent=4)

applied_jobs = []
if os.path.exists(APPLIED_JOBS_FILE):
    with open(APPLIED_JOBS_FILE, "r") as f:
        try:
            applied_jobs = json.load(f)
        except:
            pass

failed_jobs = []
if os.path.exists(FAILED_JOBS_FILE):
    with open(FAILED_JOBS_FILE, "r") as f:
        try:
            failed_jobs = json.load(f)
            # DO NOT add failed jobs to applied_urls, we want to retry them!
        except:
            pass

applied_urls = {job.get("url") for job in applied_jobs if job.get("url")}

# Gemini AI Form Filler
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
else:
    model = None

def solve_questions_with_ai(page):
    if not model:
        print("    [!] Gemini API Key not set. Cannot auto-answer custom questions.")
        return False
        
    print("    [AI] Analyzing custom questions on page...")
    # Extract visible text/questions
    try:
        form_text = page.inner_text("body")
    except:
        form_text = ""
        
    prompt = f"""
    You are an AI job applicant bot filling out an application on Hirist.tech.
    The form text is below. Find any unanswered text inputs, radio buttons, or dropdowns.
    
    Candidate Profile:
    {MCANDIDATE_PROFILE}
    
    Form Text:
    {form_text[:2000]}
    
    If there are questions like 'Why should we hire you?', 'Experience in years', 'Current CTC', provide short, professional answers based on the profile (e.g. 0 years exp, Fresher, N/A for CTC).
    Output your plan in a few lines.
    """
    try:
        response = model.generate_content(prompt)
        print(f"    [AI Decision]:\n{response.text}")
        # Try to fill any empty text inputs with generic answers if they are required.
        inputs = page.query_selector_all("input[type='text'], textarea")
        for inp in inputs:
            if not inp.input_value():
                inp.fill("Please refer to my resume. I am a 2026 graduate looking for fresher opportunities.")
                human_delay(0.5, 1.0)
        return True
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "Quota exceeded" in error_msg:
            print("    [!] Rate limited by Gemini (Free Tier 5 requests/min). Waiting 35 seconds...")
            time.sleep(35)
            try:
                response = model.generate_content(prompt)
                print(f"    [AI Decision]:\n{response.text}")
                inputs = page.query_selector_all("input[type='text'], textarea")
                for inp in inputs:
                    if not inp.input_value():
                        inp.fill("Please refer to my resume. I am a 2026 graduate looking for fresher opportunities.")
                        human_delay(0.5, 1.0)
                return True
            except Exception as e2:
                print(f"    [!] AI Error on retry: {e2}")
                return False
        else:
            print(f"    [!] AI Error: {e}")
            return False

def run_linkedin():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Run without actually clicking submit.")
    args = parser.parse_args()

    with sync_playwright() as p:
        print("Launching Google Chrome...")
        context = p.chromium.launch_persistent_context(
            CHROMIUM_DATA_DIR,
            channel="chrome",
            headless=False,
            viewport={"width": 1280, "height": 800},
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
        )
        page = context.new_page()
        
        # Step 1: Wait for user to set filters manually
        print("\n=======================================================")
        print("1. Please apply any filters you want (Location, Experience, etc).")
        print("2. Wait for the page to load your filtered jobs.")
        print("3. Press ENTER in this terminal when you are ready!")
        print("=======================================================\n")
        
        # Navigate to the base search URL and let the user take over
        page.goto("https://www.linkedin.com/jobs/search/?keywords=software%20developer")
        
        print("\n>>> You have 60 seconds to log in and set your filters in the browser window! <<<")
        for i in range(60, 0, -1):
            print(f"Waiting... {i} seconds remaining.", end="\r")
            time.sleep(1)
        print("\n\nTime's up! Proceeding with the search results currently on screen...\n")
        
        search_url = page.url
        print(f"\n[+] Starting automated application loop on: {search_url}")
        
        target_applications = 50
        applications_done = 0
        
        # Keywords for filtering
        tech_keywords = [
            "software", "developer", "engineer", "full stack", "mern", "react", 
            "frontend", "backend", "node", "java", "python", "sde-1", "application"
        ]
        
        anti_keywords = [
            "senior", "lead", "principal", "manager", "architect", 
            "sales", "marketing", "bpo", "support", "sr", "sr.", "head", "director", "vp"
        ]
        
        empty_scroll_count = 0
        visited_urls = set()
        
        while applications_done < target_applications:
            print(f"\n--- Scanning page for jobs ({applications_done}/{target_applications} applied) ---")
            
            # Scroll left-hand job list pane on LinkedIn to trigger lazy loading
            try:
                page.evaluate("""() => {
                    const list = document.querySelector('.jobs-search-results-list, .jobs-search-results-display, .scaffold-layout__list');
                    if (list) list.scrollTop += 2000;
                }""")
            except:
                pass
            page.wait_for_timeout(2500)
            
            # Query job cards on left side pane
            job_cards = page.query_selector_all("li.jobs-search-results__list-item, div.job-card-container, div.jobs-search-results-list__list-item, div[data-job-id]")
            
            if not job_cards:
                job_cards = page.query_selector_all("a.job-card-container__link, a.job-card-list__title, a[href*='/jobs/view/']")
                
            processed_in_this_page = 0
            
            for card in job_cards:
                if applications_done >= target_applications:
                    break
                    
                try:
                    # Get unique ID or href to avoid duplicate clicks
                    card_id = card.get_attribute("data-job-id") or card.get_attribute("data-occurs-id")
                    if not card_id:
                        link_el = card.query_selector("a[href*='/jobs/view/']") or card
                        href = link_el.get_attribute("href") or ""
                        card_id = href.split("?")[0] if href else ""
                        
                    if not card_id or card_id in applied_urls or card_id in visited_urls:
                        continue
                        
                    visited_urls.add(card_id)
                    processed_in_this_page += 1
                    
                    # Scroll card into view and click it to update the right panel
                    try:
                        card.scroll_into_view_if_needed()
                        card.click(force=True)
                    except:
                        page.evaluate("el => el.click()", card)
                        
                    human_delay(2.0, 3.0)
                    
                    # Extract Job Title from right panel
                    title_el = page.query_selector(".jobs-unified-top-card__job-title, .job-details-jobs-unified-top-card__job-title, h1.t-24, h1")
                    job_title = title_el.inner_text().strip() if title_el else "Software Developer Role"
                    print(f"\n[Job]: {job_title}")
                    
                    # Wait up to 4s for Apply button in right panel to render
                    apply_btn = None
                    selectors = [
                        "button.jobs-apply-button",
                        ".jobs-s-apply button",
                        "div.jobs-apply-button--top-card button",
                        "button:has-text('Easy Apply')",
                        "button[aria-label*='Easy Apply']",
                        "button:has-text('Apply')",
                        "button[aria-label*='Apply']"
                    ]
                    
                    for _ in range(5):
                        for sel in selectors:
                            try:
                                candidate_btn = page.query_selector(sel)
                                if candidate_btn and candidate_btn.is_visible():
                                    apply_btn = candidate_btn
                                    break
                            except:
                                pass
                        if apply_btn:
                            break
                        time.sleep(0.8)
                    
                    if not apply_btn:
                        print("  No active Apply button found (already applied or closed). Skipping.")
                        continue
                        
                    btn_text = apply_btn.inner_text().strip()
                    
                    if "Applied" in btn_text:
                        print(f"  Already applied ('{btn_text}'). Skipping.")
                        continue
                    
                    # Click the Apply button regardless of text — we'll detect external vs. LinkedIn after clicking
                    print(f"  Found Apply button: '{btn_text}'. Clicking...")
                    
                    pages_before = len(context.pages)
                    apply_btn.click(force=True)
                    human_delay(2.0, 3.0)
                    
                    # Check if external site opened in new tab
                    if len(context.pages) > pages_before:
                        print("  [Skipped] External company site redirect detected (new tab). Skipping as requested.")
                        ext_page = context.pages[-1]
                        if not ext_page.is_closed():
                            ext_page.close()
                        continue
                    
                    # Check if the current URL left LinkedIn (rare but possible)
                    current_url = page.url.lower()
                    if "linkedin.com" not in current_url:
                        print(f"  [Skipped] Navigated away from LinkedIn ({current_url}). Going back...")
                        page.go_back()
                        time.sleep(2)
                        continue
                        
                    # Check if Easy Apply modal opened on same page
                    modal = page.query_selector(".jobs-easy-apply-modal, div[data-test-modal-id='easy-apply-modal'], div.jobs-easy-apply-content")
                    
                    if not modal:
                        # Wait a bit more for modal to appear
                        time.sleep(2)
                        modal = page.query_selector(".jobs-easy-apply-modal, div[data-test-modal-id='easy-apply-modal'], div.jobs-easy-apply-content")
                    
                    if modal:
                        success = solve_linkedin_easy_apply(page, MCANDIDATE_PROFILE)
                        if success:
                            print("  ✅ Success! Applied to job via LinkedIn Apply.")
                            applied_jobs.append({"id": card_id, "title": job_title, "status": "Applied via AI"})
                            applied_urls.add(card_id)
                            save_json(APPLIED_JOBS_FILE, applied_jobs)
                            applications_done += 1
                        else:
                            print("  LinkedIn Apply was not completed.")
                            # Close modal if still open
                            dismiss_btn = page.query_selector("button[aria-label='Dismiss'], button[data-test-modal-close-btn], .artdeco-modal__dismiss")
                            if dismiss_btn:
                                try:
                                    dismiss_btn.click(force=True)
                                    time.sleep(1)
                                    # If there's a discard dialog, confirm it
                                    discard_btn = page.query_selector("button[data-test-dialog-primary-btn], button:has-text('Discard'), button span:has-text('Discard')")
                                    if discard_btn and discard_btn.is_visible():
                                        discard_btn.click(force=True)
                                        time.sleep(1)
                                except:
                                    pass
                    else:
                        print("  No LinkedIn Apply modal opened. May be external or already applied.")
                        
                    human_delay(1.5, 2.5)
                    
                except Exception as e:
                    error_msg = str(e)
                    print(f"  Error processing card: {error_msg}")
                    if "Target page, context or browser has been closed" in error_msg:
                        print("\n[!] Browser closed manually. Exiting.")
                        return

            if processed_in_this_page == 0:
                empty_scroll_count += 1
                if empty_scroll_count > 3:
                    print("Reached the end of available jobs or pagination failed. Stopping.")
                    break
                    
                print("No new unapplied jobs on this view. Scrolling list...")
                try:
                    page.evaluate("""() => {
                        const list = document.querySelector('.jobs-search-results-list, .jobs-search-results-display, .scaffold-layout__list');
                        if (list) list.scrollTop += 1500;
                    }""")
                except:
                    page.mouse.wheel(0, 1500)
                page.wait_for_timeout(2500)
                
                # Check for LinkedIn next page button safely
                next_btn = page.query_selector("button.artdeco-pagination__button--next, button[aria-label='Next'], button[aria-label='Page next']")
                if next_btn:
                    try:
                        if next_btn.is_visible():
                            print("Clicking Next Page...")
                            next_btn.scroll_into_view_if_needed()
                            next_btn.click(force=True)
                            page.wait_for_timeout(4000)
                        else:
                            page.evaluate("btn => btn.click()", next_btn)
                            page.wait_for_timeout(4000)
                    except Exception as err:
                        print(f"  [!] Pagination click error: {err}")
                continue
                
            empty_scroll_count = 0
                        
            # Scroll down to load more jobs if page pagination is infinite scroll
            page.mouse.wheel(0, 3000)
            human_delay(2.0, 3.0)
        
        print(f"\n[+] Finished. Applied to {applications_done} jobs.")
        
        # Generate Report
        report_path = os.path.join(BASE_DIR, "linkedin_final_report.md")
        with open(report_path, "w") as f:
            f.write(f"# LinkedIn Automated Application Report\n\n")
            f.write(f"**Total Applications:** {applications_done}\n\n")
            f.write("### Successfully Applied:\n")
            for job in applied_jobs[-applications_done:]:
                f.write(f"- {job['title']} ([Link]({job['url']}))\n")
            
        print(f"Report saved to: {report_path}")

if __name__ == "__main__":
    run_linkedin()
