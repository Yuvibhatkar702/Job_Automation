import os
import json
import time
import sys
import random
import re
import argparse
from playwright.sync_api import sync_playwright
from ai_provider import ask_ai, is_ai_available
from profile_manager import get_candidate_profile_prompt, load_profile_data
from qa_engine import answer_hr_question

# ═══════════════════════════════════════════════════════════════════════════════
# SETUP & CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMIUM_DATA_DIR = os.path.join(BASE_DIR, "indeed_data")
APPLIED_JOBS_FILE = os.path.join(BASE_DIR, "indeed_applied.json")
FAILED_JOBS_FILE = os.path.join(BASE_DIR, "indeed_failed.json")
REPORT_FILE = os.path.join(BASE_DIR, "indeed_final_report.md")
RESUME_PATH = os.path.join(BASE_DIR, "resume.pdf")

MCANDIDATE_PROFILE = get_candidate_profile_prompt()

# Search queries targeting 0-1 years / Fresher / Entry Level with iafilter=1 (Easily Apply Only)
SEARCH_QUERIES = [
    "https://in.indeed.com/jobs?q=software+developer+0-1+years&l=India&iafilter=1&fromage=7",
    "https://in.indeed.com/jobs?q=software+developer+fresher&l=India&iafilter=1&fromage=7",
    "https://in.indeed.com/jobs?q=junior+software+developer&l=India&iafilter=1&fromage=7",
    "https://in.indeed.com/jobs?q=full+stack+developer+fresher&l=India&iafilter=1&fromage=7",
    "https://in.indeed.com/jobs?q=web+developer+fresher&l=India&iafilter=1&fromage=7",
]

# Roles that do NOT fit 0-1 years experience
ANTI_KEYWORDS = [
    "senior", "lead", "principal", "manager", "architect", "staff",
    "sr.", "sr ", "head", "director", "vp", "3+", "4+", "5+", "6+", "team lead"
]

# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def human_delay(min_sec=1.5, max_sec=3.5):
    """Random human-like delay to avoid bot detection."""
    time.sleep(random.uniform(min_sec, max_sec))

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_profile_value(field_label):
    """Return correct profile value for known form fields."""
    profile = load_profile_data()
    personal = profile.get("personal_info", {})
    label = field_label.lower().strip()

    if "first name" in label or "first_name" in label:
        return personal.get("first_name", "Yuvraj")
    if "last name" in label or "last_name" in label or "surname" in label:
        return personal.get("last_name", "Bhakar")
    if "full name" in label or label == "name" or label == "your name":
        return personal.get("full_name", "Yuvraj Bhakar")
    if "email" in label:
        return personal.get("email", "yuvibhatkar702@gmail.com")
    if "phone" in label or "mobile" in label or "contact number" in label:
        return personal.get("phone", "+917767055408")
    if "city" in label or "location" in label:
        return personal.get("city", "Pune")
    if "state" in label or "province" in label:
        return personal.get("state", "Maharashtra")
    if "country" in label:
        return personal.get("country", "India")
    if "postal" in label or "zip" in label or "pin" in label:
        return "411001"
    if "linkedin" in label:
        return personal.get("linkedin", "")
    if "github" in label or "portfolio" in label or "website" in label:
        return personal.get("github", "")
    if "address" in label:
        return personal.get("address", "Pune, Maharashtra, India")
    return ""

def dismiss_cookie_banner(page_or_frame):
    """Dismiss any cookie banner that could obstruct buttons."""
    try:
        cookie_btn = page_or_frame.query_selector(
            'button:has-text("Accept All Cookies"), '
            'button#onetrust-accept-btn-handler, '
            'button:has-text("Accept cookies"), '
            'button:has-text("Agree and proceed")'
        )
        if cookie_btn and cookie_btn.is_visible():
            cookie_btn.click()
            time.sleep(1.0)
    except:
        pass

def get_page_url(target_page):
    """Safely get real page URL via JavaScript even if Playwright page.url is uninitialized."""
    try:
        url = target_page.evaluate("() => window.location.href")
        if url:
            return url.lower()
    except:
        pass
    try:
        return target_page.url.lower()
    except:
        return ""

# ═══════════════════════════════════════════════════════════════════════════════
# FORM SOLVER FOR SMARTAPPLY (TAB / WINDOW)
# ═══════════════════════════════════════════════════════════════════════════════
def solve_indeed_apply_on_page(apply_page, job_title=""):
    """
    Solves the Indeed Apply flow when opened in a tab/window (smartapply.indeed.com).
    Handles multi-step wizards: Contact Info -> Questions -> Resume -> Review -> Submit.
    """
    print(f"  [AI] Solving Indeed Apply for '{job_title}' on smartapply.indeed.com...")
    profile = load_profile_data()
    personal = profile.get("personal_info", {})

    dismiss_cookie_banner(apply_page)

    MAX_STEPS = 8
    for step_num in range(MAX_STEPS):
        print(f"  [Apply Step {step_num + 1}] Processing step...")
        time.sleep(2.5)

        # 1. Check if application has already been submitted (genuine confirmation page)
        try:
            curr_url = get_page_url(apply_page)
            body_text = apply_page.inner_text("body").lower()
            if "post-apply" in curr_url or "your application was submitted to" in body_text or "application submitted to" in body_text:
                print("  [✓] Application successfully submitted and verified!")
                return True
        except:
            pass

        # 2. If the tab was closed without submitting, it failed
        if apply_page.is_closed():
            print("  [!] Apply tab was closed before submission.")
            return False

        dismiss_cookie_banner(apply_page)

        # 3. Fill profile / contact fields
        contact_map = {
            "First name": personal.get("first_name", "Yuvraj"),
            "Last name": personal.get("last_name", "Bhakar"),
            "Email": personal.get("email", "yuvibhatkar702@gmail.com"),
            "Email address": personal.get("email", "yuvibhatkar702@gmail.com"),
            "Phone number": personal.get("phone", "+917767055408"),
            "Phone": personal.get("phone", "+917767055408"),
            "City": personal.get("city", "Pune"),
            "City, State": f"{personal.get('city', 'Pune')}, {personal.get('state', 'Maharashtra')}",
        }
        for label_text, val in contact_map.items():
            try:
                loc = apply_page.get_by_label(label_text, exact=False)
                if loc.count() > 0 and loc.first.is_visible():
                    if not loc.first.input_value().strip():
                        loc.first.fill(val)
                        print(f"    [Profile Fill] {label_text} → {val}")
                        time.sleep(0.3)
            except:
                pass

        # 4. Upload resume if prompted
        try:
            file_input = apply_page.locator('input[type="file"]')
            if file_input.count() > 0 and os.path.exists(RESUME_PATH):
                file_input.first.set_input_files(RESUME_PATH)
                print(f"    [✓] Uploaded resume: {RESUME_PATH}")
                time.sleep(1.0)
        except:
            pass

        # 5. Answer screening questions (Text inputs & textareas)
        try:
            inputs = apply_page.locator(
                'input[type="text"]:visible, input[type="number"]:visible, textarea:visible'
            )
            for i in range(inputs.count()):
                try:
                    el = inputs.nth(i)
                    if el.input_value().strip():
                        continue
                    label_text = el.get_attribute("aria-label") or ""
                    if not label_text:
                        el_id = el.get_attribute("id") or ""
                        if el_id:
                            lbl = apply_page.locator(f'label[for="{el_id}"]')
                            if lbl.count() > 0:
                                label_text = lbl.first.inner_text().strip()
                    if not label_text:
                        label_text = el.get_attribute("placeholder") or ""
                    if not label_text:
                        continue

                    pv = get_profile_value(label_text)
                    if pv:
                        el.fill(pv)
                        print(f"    [Profile Fill] {label_text[:40]} → {pv}")
                    else:
                        answer = answer_hr_question(label_text)
                        if not answer:
                            answer = "0"
                        el.fill(answer[:200])
                        print(f"    [AI Fill] {label_text[:40]} → {answer[:40]}")
                    time.sleep(0.3)
                except:
                    pass
        except:
            pass

        # 6. Answer radio buttons
        try:
            fieldsets = apply_page.locator('fieldset:visible, div[role="radiogroup"]:visible')
            for i in range(fieldsets.count()):
                try:
                    fs = fieldsets.nth(i)
                    question = ""
                    try:
                        question = fs.locator("legend, label").first.inner_text().strip()
                    except:
                        pass
                    if not question:
                        continue

                    radios = fs.locator('input[type="radio"]')
                    radio_labels = []
                    for j in range(radios.count()):
                        try:
                            r_id = radios.nth(j).get_attribute("id") or ""
                            lbl = apply_page.locator(f'label[for="{r_id}"]')
                            radio_labels.append(lbl.first.inner_text().strip() if lbl.count() > 0 else f"Option {j}")
                        except:
                            radio_labels.append(f"Option {j}")

                    if not radio_labels:
                        continue

                    already_checked = any(radios.nth(j).is_checked() for j in range(radios.count()))
                    if already_checked:
                        continue

                    answer = answer_hr_question(question, options=radio_labels)
                    try:
                        idx = int(answer)
                        if not (0 <= idx < len(radio_labels)):
                            idx = 0
                    except:
                        idx = 0

                    r_id = radios.nth(idx).get_attribute("id") or ""
                    if r_id:
                        apply_page.locator(f'label[for="{r_id}"]').first.click()
                    else:
                        radios.nth(idx).click(force=True)
                    print(f"    [AI Radio] {question[:40]} → {radio_labels[idx]}")
                    time.sleep(0.3)
                except:
                    pass
        except:
            pass

        # 7. Answer dropdowns
        try:
            selects = apply_page.locator('select:visible')
            for i in range(selects.count()):
                try:
                    sel = selects.nth(i)
                    cur = sel.evaluate("el => el.options[el.selectedIndex]?.text || ''").strip()
                    if cur and cur.lower() not in ["select", "select an option", "--", "choose", ""]:
                        continue
                    label_text = ""
                    sel_id = sel.get_attribute("id") or ""
                    if sel_id:
                        lbl = apply_page.locator(f'label[for="{sel_id}"]')
                        if lbl.count() > 0:
                            label_text = lbl.first.inner_text().strip()
                    options = sel.evaluate("""el => Array.from(el.options)
                        .map(o => ({text: o.text.trim(), value: o.value}))
                        .filter(o => o.text && !['select','select an option','--','choose',''].includes(o.text.toLowerCase()))""")
                    if not options:
                        continue
                    option_texts = [o["text"] for o in options]
                    answer = answer_hr_question(label_text or "Select best option", options=option_texts)
                    try:
                        idx = int(answer)
                        if not (0 <= idx < len(options)):
                            idx = 0
                    except:
                        idx = 0
                    o = options[idx]
                    sel.select_option(value=o["value"]) if o["value"] else sel.select_option(label=o["text"])
                    print(f"    [AI Select] {label_text[:35]} → {o['text']}")
                    time.sleep(0.3)
                except:
                    pass
        except:
            pass

        # 8. Check checkboxes (consent / agreement)
        try:
            cbs = apply_page.locator('input[type="checkbox"]:visible')
            for i in range(cbs.count()):
                try:
                    cb = cbs.nth(i)
                    if cb.is_checked():
                        continue
                    cb_id = cb.get_attribute("id") or ""
                    cb_label = ""
                    if cb_id:
                        lbl = apply_page.locator(f'label[for="{cb_id}"]')
                        if lbl.count() > 0:
                            cb_label = lbl.first.inner_text().strip().lower()
                    if any(kw in cb_label for kw in ["agree", "consent", "terms", "acknowledge", "confirm"]):
                        cb.check(force=True)
                        print(f"    [Auto Check] {cb_label[:40]}")
                except:
                    pass
        except:
            pass

        # Scroll page and any inner scrollable containers all the way to the bottom
        apply_page.evaluate("""() => {
            window.scrollTo(0, document.body.scrollHeight);
            document.querySelectorAll("div, main, section").forEach(d => {
                if (d.scrollHeight > d.clientHeight && d.clientHeight > 200) {
                    d.scrollTop = d.scrollHeight;
                }
            });
        }""")
        apply_page.mouse.wheel(0, 3000)
        time.sleep(1.5)

        # Check if we are on the review or final submission step
        is_review_step = (
            "/review" in get_page_url(apply_page) or
            bool(apply_page.query_selector('button:has-text("Submit your application"), button:has-text("Submit application")'))
        )

        # Handle reCAPTCHA ONLY on the review / submit step
        if is_review_step:
            try:
                # 1. Locate reCAPTCHA anchor via frame_locator
                rc_frame = apply_page.frame_locator('iframe[src*="recaptcha"], iframe[title*="reCAPTCHA" i]')
                rc_anchor = rc_frame.locator('#recaptcha-anchor, .recaptcha-checkbox, div.recaptcha-checkbox-border')

                if rc_anchor.count() > 0:
                    aria_checked = rc_anchor.first.get_attribute("aria-checked")
                    if aria_checked != "true":
                        print("  [AI] reCAPTCHA detected! Clicking 'I am not a robot'...")
                        try:
                            rc_anchor.first.click()
                        except:
                            # Coordinate fallback
                            rc_el = apply_page.query_selector('iframe[src*="recaptcha"], iframe[title*="reCAPTCHA" i]')
                            if rc_el:
                                box = rc_el.bounding_box()
                                if box:
                                    apply_page.mouse.click(box["x"] + 28, box["y"] + (box["height"] / 2))
                        time.sleep(3.0)

                        # Check if verified or if puzzle appeared
                        try:
                            if rc_anchor.first.get_attribute("aria-checked") == "true":
                                print("  [✓] reCAPTCHA verified automatically!")
                            else:
                                print("  [!] ⚠️ reCAPTCHA verification required! Please click 'I am not a robot' in the browser (waiting 15s)...")
                                for _ in range(15):
                                    time.sleep(1.0)
                                    if rc_anchor.first.get_attribute("aria-checked") == "true":
                                        print("  [✓] reCAPTCHA verified! Proceeding with submission...")
                                        break
                        except:
                            pass
            except Exception as e:
                pass

        # Re-scroll to ensure submit button is visible
        apply_page.mouse.wheel(0, 1000)
        time.sleep(0.5)

        # 9. PRIORITY 1: Check for Final Submit button
        submit_btn = apply_page.query_selector(
            'button:has-text("Submit your application"), '
            'button:has-text("Submit application"), '
            'button:has-text("Send application")'
        )
        if submit_btn:
            # If reCAPTCHA is present and still not checked, give a final 10-second window
            try:
                rc_frame = apply_page.frame_locator('iframe[src*="recaptcha"], iframe[title*="reCAPTCHA" i]')
                rc_anchor = rc_frame.locator('#recaptcha-anchor')
                if rc_anchor.count() > 0 and rc_anchor.first.get_attribute("aria-checked") != "true":
                    print("  [!] ⚠️ Please check 'I am not a robot' in the browser before submit (waiting 10s)...")
                    for _ in range(10):
                        time.sleep(1.0)
                        if rc_anchor.first.get_attribute("aria-checked") == "true":
                            break
            except:
                pass

            try:
                submit_btn.scroll_into_view_if_needed()
            except:
                pass
            time.sleep(0.5)
            print(f"  [AI] Found Submit button ('{submit_btn.inner_text().strip()}')! Submitting application...")
            try:
                submit_btn.click()
            except:
                submit_btn.evaluate("el => el.click()")

            # Strict verification: Wait up to 10 seconds for genuine post-apply confirmation
            print("  [AI] Waiting for submission confirmation...")
            for _ in range(10):
                time.sleep(1.0)
                try:
                    curr_url = get_page_url(apply_page)
                    body = apply_page.inner_text("body").lower()
                    if "post-apply" in curr_url or "your application was submitted to" in body or "application submitted to" in body:
                        print("  [✓] Application successfully submitted and verified!")
                        return True
                except:
                    pass

            print("  [!] Submission could not be confirmed (captcha or validation error).")
            return False

        # 10. PRIORITY 2: Check for Continue / Next / Review button
        continue_btn = apply_page.query_selector(
            'button:has-text("Continue"), '
            'button:has-text("Review your application"), '
            'button:has-text("Next"), '
            'button:has-text("Proceed")'
        )
        if continue_btn:
            try:
                continue_btn.scroll_into_view_if_needed()
            except:
                pass
            time.sleep(0.5)
            print(f"  [AI] Clicking Continue ('{continue_btn.inner_text().strip()}')...")
            try:
                continue_btn.click()
            except:
                continue_btn.evaluate("el => el.click()")
            time.sleep(3.0)
            continue

        print("  [!] No actionable Continue or Submit button found on this step.")
        time.sleep(2.0)

    return False

# ═══════════════════════════════════════════════════════════════════════════════
# FORM SOLVER FOR IN-PAGE / IFRAME APPLY
# ═══════════════════════════════════════════════════════════════════════════════
def solve_indeed_apply_in_page(page, job_title=""):
    """
    Solves Indeed Apply when rendered inside an iframe on the main page.
    """
    print(f"  [AI] Checking in-page iframe for '{job_title}'...")
    time.sleep(2.0)

    iframe_selectors = [
        'iframe[title*="apply" i]',
        'iframe[id*="indeedApply"]',
        'iframe[class*="apply"]',
        'iframe[src*="indeedapply"]',
        'iframe[src*="smartapply"]',
    ]
    frame_loc = None
    for sel in iframe_selectors:
        try:
            if page.locator(sel).count() > 0:
                frame_loc = page.frame_locator(sel)
                break
        except:
            pass

    if not frame_loc:
        print("  [!] No apply iframe found on main page.")
        return False

    for step in range(8):
        time.sleep(2.0)
        # Check success
        try:
            body = frame_loc.locator("body").inner_text().lower()
            if any(t in body for t in ["submitted", "sent", "applied"]):
                print("  [✓] Application submitted inside iframe!")
                return True
        except:
            return True

        # Fill profile
        profile = load_profile_data()
        personal = profile.get("personal_info", {})
        for label, val in {
            "First name": personal.get("first_name", "Yuvraj"),
            "Last name": personal.get("last_name", "Bhakar"),
            "Email": personal.get("email", "yuvibhatkar702@gmail.com"),
            "Phone": personal.get("phone", "+917767055408"),
            "City": personal.get("city", "Pune"),
        }.items():
            try:
                l = frame_loc.get_by_label(label, exact=False)
                if l.count() > 0 and l.first.is_visible() and not l.first.input_value().strip():
                    l.first.fill(val)
            except:
                pass

        # Submit or Continue
        try:
            sub = frame_loc.get_by_role("button", name=re.compile(r"submit.*application|submit", re.IGNORECASE))
            if sub.count() > 0 and sub.first.is_visible():
                sub.first.click()
                time.sleep(4.0)
                return True
            cont = frame_loc.get_by_role("button", name=re.compile(r"continue|next|review", re.IGNORECASE))
            if cont.count() > 0 and cont.first.is_visible():
                cont.first.click()
                time.sleep(2.5)
                continue
        except:
            pass

    return False

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN AUTOMATION RUNNER
# ═══════════════════════════════════════════════════════════════════════════════
applied_jobs = []
if os.path.exists(APPLIED_JOBS_FILE):
    with open(APPLIED_JOBS_FILE, "r", encoding="utf-8") as f:
        try:
            applied_jobs = json.load(f)
        except:
            pass

failed_jobs = []
if os.path.exists(FAILED_JOBS_FILE):
    with open(FAILED_JOBS_FILE, "r", encoding="utf-8") as f:
        try:
            failed_jobs = json.load(f)
        except:
            pass

applied_keys = {job.get("key") for job in applied_jobs if job.get("key")}

def run_indeed():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Run without actually clicking final submit.")
    args = parser.parse_args()

    with sync_playwright() as p:
        print("Launching Google Chrome...")
        context = p.chromium.launch_persistent_context(
            CHROMIUM_DATA_DIR,
            channel="chrome",
            headless=False,
            viewport={"width": 1366, "height": 900},
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ]
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            if (!window.chrome) {
                window.chrome = {};
            }
            if (!window.chrome.runtime) {
                window.chrome.runtime = {};
            }
        """)
        page = context.new_page()

        print("\n" + "=" * 65)
        print("  🔍 INDEED 0-1 YEARS EASILY APPLY ASSISTANT")
        print("=" * 65)
        print("""
  Features:
  - Filters strictly for 0-1 Years / Fresher Experience
  - Filters strictly for 'Easily Apply' jobs (iafilter=1)
  - Auto-skips external company websites
  - Auto-skips Senior/Lead/Architect roles (> 1 year experience)
  - Answers screening questions with AI & candidate profile
  - Auto-submits Indeed applications
""")
        print("=" * 65 + "\n")

        # Initial search query targeting 0-1 years and Easily Apply
        initial_url = SEARCH_QUERIES[0]
        try:
            page.goto(initial_url, wait_until="domcontentloaded")
        except Exception as e:
            pass

        print(">>> You have 45 seconds to review the browser and log in if needed! <<<")
        for i in range(45, 0, -1):
            print(f"Waiting... {i} seconds remaining.", end="\r")
            time.sleep(1)
        print("\n\nTimer finished. Starting automated application loop...\n")

        target_applications = 30
        applications_done = 0
        visited_keys = set()

        # Start with the active page URL (preserves user-selected filters from the 45s timer)
        current_active_url = page.url
        queries_to_run = [current_active_url] + [q for q in SEARCH_QUERIES if q != current_active_url]

        for q_idx, search_url in enumerate(queries_to_run):
            if applications_done >= target_applications:
                break

            # If it's not the initial loaded page, navigate to the query
            if q_idx > 0:
                print(f"\n[+] Navigating to search query: {search_url}")
                try:
                    page.goto(search_url, wait_until="domcontentloaded")
                    page.wait_for_timeout(4000)
                except Exception as e:
                    print(f"  [!] Navigation note: {e}")
                    page.wait_for_timeout(3000)
            else:
                print(f"\n[+] Processing search results currently on screen: {page.url}")
                page.wait_for_timeout(2000)

            for page_num in range(5):  # Scan up to 5 pages per query
                if applications_done >= target_applications:
                    break

                print(f"\n--- Scanning page {page_num + 1} ({applications_done}/{target_applications} applied) ---")
                page.wait_for_timeout(3000)

                # Collect cards
                cards = page.query_selector_all("div.cardOutline")
                if not cards:
                    cards = page.query_selector_all("div.job_seen_beacon")

                if not cards:
                    print("  No job cards found on this page. Checking next query...")
                    break

                new_jobs = []
                for c in cards:
                    try:
                        c_text = c.inner_text()
                        
                        # 1. STRICT FILTER: Must have 'Easily apply'
                        if "easily apply" not in c_text.lower():
                            continue

                        # Extract Title & Job Key
                        title_el = c.query_selector('a[id^="job_"], a.jcs-JobTitle, h2.jobTitle a, h2.jobTitle span')
                        title = title_el.inner_text().strip() if title_el else "Unknown Role"

                        # Extract Key
                        jk = ""
                        if title_el:
                            a_id = title_el.get_attribute("id") or ""
                            if a_id.startswith("job_"):
                                jk = a_id.replace("job_", "")
                            elif title_el.get_attribute("data-jk"):
                                jk = title_el.get_attribute("data-jk")

                        if not jk:
                            c_jk = c.get_attribute("data-jk") or ""
                            if c_jk:
                                jk = c_jk

                        # Skip already processed
                        if not jk or jk in visited_keys or jk in applied_keys:
                            continue

                        # 2. STRICT FILTER: Skip Senior/Lead roles
                        title_lower = title.lower()
                        if any(ak in title_lower for ak in ANTI_KEYWORDS):
                            print(f"  [Skipped] Non-fresher/Senior role: '{title}'")
                            continue

                        # Extract Company
                        comp_el = c.query_selector('span[data-testid="company-name"], span.companyName')
                        company = comp_el.inner_text().strip() if comp_el else "Unknown Company"

                        # Extract Location
                        loc_el = c.query_selector('div[data-testid="text-location"], div.companyLocation')
                        location = loc_el.inner_text().strip() if loc_el else ""

                        new_jobs.append({
                            "key": jk,
                            "title": title,
                            "company": company,
                            "location": location,
                            "card": c,
                        })
                    except:
                        pass

                if not new_jobs:
                    print("  No new 0-1 year Easily Apply jobs on this view. Paginating...")
                else:
                    print(f"  Found {len(new_jobs)} eligible 0-1 year Easily Apply jobs!")

                # Process jobs
                for job in new_jobs:
                    if applications_done >= target_applications:
                        break

                    visited_keys.add(job["key"])
                    print(f"\n[Job]: {job['title']} @ {job['company']} ({job['location']})")

                    # 1. Click job card to load right details pane
                    try:
                        job["card"].evaluate("el => { el.scrollIntoView({block: 'center'}); el.click(); }")
                        page.wait_for_timeout(3000)
                    except Exception as e:
                        print(f"  [!] Failed to click job card: {e}")
                        continue

                    # 2. Verify right pane apply button
                    apply_btn = page.query_selector(
                        'button#indeedApplyButton, '
                        'button:has-text("Apply with Indeed"), '
                        'button:has-text("Apply now"), '
                        'button.ia-IndeedApplyButton'
                    )
                    if not apply_btn or not apply_btn.is_visible():
                        print("  [Skipped] No active 'Apply with Indeed' button in right pane.")
                        continue

                    btn_text = apply_btn.inner_text().strip()
                    if "company site" in btn_text.lower() or "company website" in btn_text.lower():
                        print(f"  [Skipped] External application link ('{btn_text}').")
                        continue

                    print(f"  Found internal apply button: '{btn_text}'. Clicking...")
                    pages_before = len(context.pages)

                    try:
                        apply_btn.click()
                    except:
                        apply_btn.evaluate("el => el.click()")

                    human_delay(3.0, 5.0)

                    # 3. Check if opened in new tab/window
                    success = False
                    if len(context.pages) > pages_before:
                        apply_page = context.pages[-1]

                        # Wait for the newly opened tab to navigate away from empty/about:blank
                        print("  [→] Application tab opened. Waiting for URL to load...")
                        apply_url = ""
                        for _ in range(25):  # Wait up to 12 seconds
                            apply_url = get_page_url(apply_page)
                            if apply_url and "about:blank" not in apply_url:
                                break
                            time.sleep(0.5)

                        # If on smartapply trampoline (applybyapplyablejobid), wait for /form/
                        if "smartapply" in apply_url and "/form/" not in apply_url:
                            print("  [→] Waiting for SmartApply form redirect...")
                            for _ in range(20):
                                apply_url = get_page_url(apply_page)
                                if "/form/" in apply_url:
                                    break
                                time.sleep(0.5)

                        print(f"  [→] Application tab loaded: {apply_url[:80]}")

                        if "indeed" in apply_url or "smartapply" in apply_url:
                            print("  [→] Opened Indeed SmartApply in new tab.")
                            success = solve_indeed_apply_on_page(apply_page, job_title=job["title"])
                            if not apply_page.is_closed():
                                try:
                                    apply_page.close()
                                except:
                                    pass
                        else:
                            print(f"  [Skipped] Opened external site ({apply_url}). Closing tab.")
                            if not apply_page.is_closed():
                                try:
                                    apply_page.close()
                                except:
                                    pass
                            continue
                    else:
                        # In-page apply form
                        success = solve_indeed_apply_in_page(page, job_title=job["title"])

                    # 4. Record result
                    if success:
                        print(f"  ✅ SUCCESS: Applied to {job['title']} @ {job['company']}")
                        record = {
                            "key": job["key"],
                            "title": job["title"],
                            "company": job["company"],
                            "location": job["location"],
                            "status": "Applied via AI",
                            "url": f"https://in.indeed.com/viewjob?jk={job['key']}"
                        }
                        applied_jobs.append(record)
                        applied_keys.add(job["key"])
                        save_json(APPLIED_JOBS_FILE, applied_jobs)
                        applications_done += 1
                    else:
                        print(f"  [!] Application incomplete for {job['title']}")
                        failed_jobs.append({
                            "key": job["key"],
                            "title": job["title"],
                            "company": job["company"],
                            "reason": "Apply solver could not complete"
                        })
                        save_json(FAILED_JOBS_FILE, failed_jobs)

                    human_delay(2.0, 4.0)

                # Pagination: try Next Page
                try:
                    next_btn = page.query_selector(
                        'a[data-testid="pagination-page-next"], '
                        'a[aria-label="Next Page"], '
                        'a.np, '
                        'nav a:has-text("Next")'
                    )
                    if next_btn and next_btn.is_visible():
                        print("Clicking Next Page...")
                        next_btn.click()
                        page.wait_for_timeout(4000)
                    else:
                        break
                except:
                    break

        # ── Final Report ──────────────────────────────────────────────────
        print(f"\n[+] Indeed run completed. Applied to {applications_done} jobs.")
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            f.write("# Indeed 0-1 Years Automated Application Report\n\n")
            f.write(f"**Total Applications:** {applications_done}\n\n")
            f.write("### Successfully Applied:\n")
            for job in applied_jobs[-applications_done:]:
                t = job.get("title", "Unknown")
                c = job.get("company", "Unknown")
                u = job.get("url", "")
                f.write(f"- **{t}** @ {c} ([Link]({u}))\n")

        print(f"Report saved to: {REPORT_FILE}")

if __name__ == "__main__":
    run_indeed()
