import json
import os
import time
import re
from playwright.sync_api import sync_playwright

JOBS_FILE = "C:/Users/Admin/.gemini/antigravity/scratch/job_assistant/jobs.json"
PROFILE_FILE = "C:/Users/Admin/.gemini/antigravity/scratch/job_assistant/profile.json"
APPLIED_JOBS_FILE = "C:/Users/Admin/.gemini/antigravity/scratch/job_assistant/applied_jobs.json"

# Default fallback path for resume if user hasn't specified
DEFAULT_RESUME_PATH = "C:/Users/Admin/Documents/Yuvraj_Bhakar_Resume.pdf"

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

def is_experience_suitable(job_description_text):
    # Scan the text for experience requirements like "3+ years", "4-6 years", "senior", "lead", "manager"
    # To filter out roles requiring more than 2 years of experience.
    text_lower = job_description_text.lower()
    
    # Check for experience keywords
    exp_matches = re.findall(r'(\d+)\s*\+?\s*(?:to\s*\d+\s*)?years?\s+(?:of\s+)?experience', text_lower)
    for match in exp_matches:
        try:
            years = int(match)
            if years > 2:
                print(f"Skipping job: Requires {years} years of experience (threshold is <= 2).")
                return False
        except ValueError:
            continue
            
    # Check for senior/lead titles in text if heavily emphasized
    exclude_keywords = ["senior developer", "senior engineer", "lead developer", "lead engineer", "principal developer", "architect"]
    if any(keyword in text_lower for keyword in exclude_keywords):
        print("Skipping job: Title or description suggests Senior/Lead role.")
        return False
        
    return True

def fill_field(page, selector, value):
    try:
        element = page.query_selector(selector)
        if element and element.is_visible() and not element.is_disabled():
            # Clear field
            element.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            element.fill(value)
            print(f"  Filled field '{selector}' with: {value}")
            return True
    except Exception as e:
        print(f"  Error filling '{selector}': {e}")
    return False

def upload_resume(page, resume_path):
    if not os.path.exists(resume_path):
        print(f"  Warning: Resume file not found at '{resume_path}'. Please place your resume there.")
        return False
        
    # Search for common file input selectors
    file_inputs = page.query_selector_all("input[type='file']")
    for file_input in file_inputs:
        name = file_input.get_attribute("name") or ""
        id_attr = file_input.get_attribute("id") or ""
        class_attr = file_input.get_attribute("class") or ""
        
        # Check if file input is likely for resume/cv
        if any(keyword in (name + id_attr + class_attr).lower() for keyword in ["resume", "cv", "attachment", "document"]):
            try:
                file_input.set_input_files(resume_path)
                print(f"  Uploaded resume: {resume_path}")
                return True
            except Exception as e:
                print(f"  Error uploading resume: {e}")
                
    # If no matching keywords, try the first file input
    if file_inputs:
        try:
            file_inputs[0].set_input_files(resume_path)
            print(f"  Uploaded resume to first file input field: {resume_path}")
            return True
        except Exception as e:
            print(f"  Error uploading resume to first input: {e}")
            
    return False

def autofill_application(page, profile, resume_path):
    info = profile["personal_info"]
    
    # 1. Fill Name
    name_filled = False
    name_filled |= fill_field(page, "input[name*='first_name'], input[id*='first_name'], input[name='firstname']", info["first_name"])
    name_filled |= fill_field(page, "input[name*='last_name'], input[id*='last_name'], input[name='lastname']", info["last_name"])
    if not name_filled:
        fill_field(page, "input[name*='name'], input[id*='name'], input[placeholder*='name']", info["full_name"])
        
    # 2. Fill Contact Info
    fill_field(page, "input[type='email'], input[name*='email'], input[id*='email']", info["email"])
    fill_field(page, "input[type='tel'], input[name*='phone'], input[id*='phone'], input[name*='mobile']", info["phone"])
    
    # 3. Fill Profile Links
    fill_field(page, "input[name*='linkedin'], input[id*='linkedin'], input[placeholder*='linkedin']", info["linkedin"])
    fill_field(page, "input[name*='github'], input[id*='github'], input[placeholder*='github']", info["github"])
    
    # 4. Fill Address details if present
    fill_field(page, "input[name*='city'], input[id*='city']", info["city"])
    fill_field(page, "input[name*='state'], input[id*='state']", info["state"])
    
    # 5. Upload Resume
    upload_resume(page, resume_path)

def apply_to_jobs():
    profile = load_json(PROFILE_FILE)
    if not profile:
        print("Error: profile.json not found or invalid.")
        return
        
    jobs = load_json(JOBS_FILE)
    applied_jobs = load_json(APPLIED_JOBS_FILE)
    applied_urls = {job["url"] for job in applied_jobs}
    
    resume_path = profile["personal_info"].get("resume_path", DEFAULT_RESUME_PATH)
    
    print(f"Total jobs in database: {len(jobs)}")
    print(f"Total applied jobs: {len(applied_jobs)}")
    
    candidate_jobs = [job for job in jobs if job["url"] not in applied_urls and job["status"] != "Skipped"]
    print(f"Pending candidate jobs to process: {len(candidate_jobs)}")
    
    if not candidate_jobs:
        print("No new jobs to process. Run searcher.py to find fresh jobs first!")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False) # Headful browser for manual verification/CAPTCHAs
        context = browser.new_context()
        page = context.new_page()
        
        for job in candidate_jobs:
            url = job["url"]
            print(f"\nProcessing: {job['title']} | Platform: {job['platform']}")
            print(f"Navigating to: {url}")
            
            try:
                page.goto(url)
                page.wait_for_load_state("domcontentloaded")
                time.sleep(3) # Wait for page elements to load
                
                # Extract text for suitability check
                body_text = page.inner_text("body")
                if not is_experience_suitable(body_text):
                    job["status"] = "Skipped"
                    job["reason"] = "Requires > 2 years experience"
                    save_json(JOBS_FILE, jobs)
                    continue
                
                print("Job matches experience requirements. Starting autofill...")
                autofill_application(page, profile, resume_path)
                
                # Check for CAPTCHAs, OTPs, or Submit stage
                print("\n[ACTION REQUIRED]")
                print("1. Please review the autofilled details on the browser window.")
                print("2. Log in, solve any CAPTCHAs/OTPs, or answer any custom questions if prompted.")
                print("3. Click the final 'Submit Application' button on the browser.")
                print("4. Once you have submitted, return here and enter the status:")
                
                status_input = input("Enter 'a' if applied successfully, 's' to skip this job, or 'q' to quit: ").strip().lower()
                
                if status_input == 'a':
                    job["status"] = "Applied"
                    job["date_applied"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    applied_jobs.append(job)
                    save_json(APPLIED_JOBS_FILE, applied_jobs)
                    print(f"Logged job as APPLIED: {job['title']}")
                elif status_input == 's':
                    job["status"] = "Skipped"
                    print(f"Logged job as SKIPPED: {job['title']}")
                elif status_input == 'q':
                    print("Exiting applier...")
                    break
                else:
                    print("Invalid input. Keeping job status as is.")
                    
                # Save changes after each job
                save_json(JOBS_FILE, jobs)
                
            except Exception as e:
                print(f"Error processing {url}: {e}")
                
        browser.close()
    
    print("\nBatch processing completed.")

if __name__ == "__main__":
    apply_to_jobs()
