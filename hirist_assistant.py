import os
import json
import time
import random
import argparse
from playwright.sync_api import sync_playwright
import google.generativeai as genai

# Setup directories and files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMIUM_DATA_DIR = os.path.join(BASE_DIR, "hirist_data")
APPLIED_JOBS_FILE = os.path.join(BASE_DIR, "hirist_applied.json")
FAILED_JOBS_FILE = os.path.join(BASE_DIR, "hirist_failed.json")

# User Profile
MCANDIDATE_PROFILE = """
ROLE:
You are my autonomous Job Application Agent.

PROFILE:
Name: Yuvraj Bhatkar
Location: Amravati, Maharashtra, India
Education: B.Tech Information Technology (2026 Graduate)
Experience Level: Fresher
Full-time Experience: 0 Years
Internship Experience: 1 Year
Joining Availability: Immediate
Relocation: Yes
Work Preference: Remote, Hybrid, Onsite

PRIMARY GOAL:
Apply ONLY to the newest and freshest jobs. Never waste time reviewing old or experienced jobs.

STRICT RULES:
1. Freshness has highest priority (<= 7 days old).
2. Experience Filter: 0-2 years maximum.
3. Preferred Roles: Software Engineer, Software Developer, Full Stack, MERN, React, Frontend, Backend, Node.js, Java, Python, SDE-1.
4. Preferred Locations: Remote India, Pune, Bengaluru, Hyderabad, Mumbai, Anywhere in India.
5. Skills: Java, Python, JavaScript, React.js, Node.js, Express.js, MongoDB, SQL, MySQL, REST API, HTML, CSS, Tailwind CSS, JWT, DSA, OOP, DBMS, Operating Systems, Computer Networks.
"""

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

def run_hirist():
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
        page.goto("https://www.hirist.tech/search/software-developer-jobs.html")
        
        print("\n>>> You have 45 seconds to set your filters in the browser window! <<<")
        for i in range(45, 0, -1):
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
        
        while applications_done < target_applications:
            print(f"\n--- Scanning page for jobs ({applications_done}/{target_applications} applied) ---")
            try:
                page.wait_for_selector("a[href*='/j/']", timeout=5000)
            except:
                pass
            page.wait_for_timeout(3000)
            
            # Hirist uses different job card classes, but all job links contain '/j/'
            job_cards = page.query_selector_all("a[href*='/j/']")
                
            job_links = []
            for card in job_cards:
                try:
                    href = card.get_attribute("href")
                    if href and "/j/" in href:
                        if href.startswith("/"): href = "https://www.hirist.tech" + href
                        if href not in applied_urls:
                            job_links.append(href)
                except:
                    pass
            
            if len(job_links) == 0:
                empty_scroll_count += 1
                if empty_scroll_count > 3:
                    print("Reached the end of available jobs or pagination failed. Stopping.")
                    break
                    
                print("No new jobs found on this page. Attempting to scroll...")
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(2000)
                
                # Check if we reached the bottom or if next page exists
                next_btn = page.query_selector("a[rel='next'], button[class*='next'], a[class*='next'], a:has-text('Next'), a:has-text('>')")
                if next_btn:
                    print("Clicking Next Page...")
                    next_btn.click(force=True)
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except:
                        pass
                    page.wait_for_timeout(4000) # Give SPA time to render new job cards
                continue
            
            empty_scroll_count = 0
            
            for job_url in job_links:
                if applications_done >= target_applications:
                    break
                    
                print(f"\nNavigating to: {job_url}")
                
                try:
                    # Open job in new tab to preserve search page
                    new_page = context.new_page()
                    new_page.goto(job_url)
                    new_page.wait_for_load_state("domcontentloaded")
                    human_delay(2.0, 4.0)
                    
                    title_el = new_page.query_selector("h1")
                    job_title = title_el.inner_text().strip() if title_el else "Unknown Role"
                    print(f"Title: {job_title}")
                        
                    # Find Apply Button
                    apply_btn = new_page.query_selector("button:has-text('Apply'), a:has-text('Apply'), button[id*='apply']")
                    if apply_btn:
                        print("  Found Apply button. Clicking...")
                        apply_btn.click()
                        human_delay(2.0, 3.0)
                        
                        # Handle possible modal or new page
                        solve_questions_with_ai(new_page)
                        
                        # Find Submit Button
                        submit_selectors = "button:has-text('Submit'), button:has-text('Confirm'), button:has-text('Proceed'), input[type='submit'], button[id*='submit'], button[class*='submit']"
                        try:
                            new_page.wait_for_selector(submit_selectors, timeout=5000)
                        except:
                            pass
                            
                        submit_btn = new_page.query_selector(submit_selectors)
                        if submit_btn:
                            if args.dry_run:
                                print("  [Dry Run] Simulating submit.")
                            else:
                                print("  Submitting application...")
                                submit_btn.click()
                                human_delay(3.0, 4.0)
                            
                            print("  Success!")
                            applied_jobs.append({"url": job_url, "title": job_title, "status": "Applied"})
                            applied_urls.add(job_url)
                            save_json(APPLIED_JOBS_FILE, applied_jobs)
                            applications_done += 1
                        else:
                            print("  Could not find Submit button. (Might be an instant-apply or external redirect)")
                            # We'll mark it as applied anyway if the first 'Apply' was successful and there's no submit needed
                            applied_jobs.append({"url": job_url, "title": job_title, "status": "Likely Applied"})
                            applied_urls.add(job_url)
                            save_json(APPLIED_JOBS_FILE, applied_jobs)
                            applications_done += 1
                    else:
                        print("  No Apply button found (already applied or closed).")
                        
                    new_page.close()
                    human_delay(1.0, 2.0)
                    
                except Exception as e:
                    error_msg = str(e)
                    print(f"  Error processing job: {error_msg}")
                    
                    if "Target page, context or browser has been closed" in error_msg:
                        print("\n[!] Browser was closed manually. Stopping the application loop.")
                        return # Exit the script cleanly
                        
                    failed_jobs.append({"url": job_url, "reason": error_msg})
                    save_json(FAILED_JOBS_FILE, failed_jobs)
                    try:
                        new_page.close()
                    except:
                        pass
                        
            # Scroll down to load more jobs if page pagination is infinite scroll
            page.mouse.wheel(0, 3000)
            human_delay(2.0, 3.0)
        
        print(f"\n[+] Finished. Applied to {applications_done} jobs.")
        
        # Generate Report
        report_path = os.path.join(BASE_DIR, "hirist_final_report.md")
        with open(report_path, "w") as f:
            f.write(f"# Hirist Automated Application Report\n\n")
            f.write(f"**Total Applications:** {applications_done}\n\n")
            f.write("### Successfully Applied:\n")
            for job in applied_jobs[-applications_done:]:
                f.write(f"- {job['title']} ([Link]({job['url']}))\n")
            
        print(f"Report saved to: {report_path}")

if __name__ == "__main__":
    run_hirist()
