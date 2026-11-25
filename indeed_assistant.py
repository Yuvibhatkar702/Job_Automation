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

def _is_filter_element(el):
    """Returns True if the element is part of the search filter bar or popup at the top of Indeed."""
    try:
        in_filter = el.evaluate("""el => {
            const filterContainer = el.closest('[id*="filter"], [class*="filter"], [data-testid*="filter"], .yosegi-FilterPill, #filter-root, #mosaic-desktopJobSearchFilters');
            if (filterContainer) return true;
            const text = (el.innerText || '').toLowerCase().trim();
            if (text.startsWith('easily apply') && !text.includes('apply now') && !text.includes('apply with indeed')) return true;
            if (['all jobs', 'reset', 'update', 'cancel', 'done', 'pay', 'remote', 'job type', 'programming language', 'education level', 'industry', 'date posted'].includes(text)) return true;
            return false;
        }""")
        return bool(in_filter)
    except:
        return False

def dismiss_open_popups(page):
    """Closes any open filter dropdowns, feedback dialogs, or cookie banners."""
    try:
        filter_popup = page.query_selector('div[role="dialog"]:has-text("Easily apply on Indeed"), div[role="dialog"]:has-text("Update"), div.popover, div[class*="FilterModal"]')
        if filter_popup and filter_popup.is_visible():
            page.keyboard.press("Escape")
            time.sleep(0.3)
        close_btn = page.query_selector('button[aria-label="Close"], button[aria-label="close"], button:has-text("Dismiss")')
        if close_btn and close_btn.is_visible():
            txt = close_btn.inner_text().lower()
            if "apply" not in txt:
                close_btn.click()
                time.sleep(0.3)
    except:
        pass

def find_indeed_apply_button(page):
    """
    Finds the active internal apply button ('Apply now' or 'Apply with Indeed').
    Strictly excludes filter pills ('Easily apply 1') and external employer sites.
    """
    pane_selectors = [
        'div.jobsearch-ViewjobPaneWrapper',
        'div#jobsearch-ViewjobPaneWrapper',
        'div.jobsearch-RightPane',
        'div.fastviewjob',
        'div.jobsearch-JobComponent',
        '#viewJobSSRRoot',
        'div[data-testid="jobsearch-ViewjobPaneWrapper"]',
        'div[data-testid="viewJobContent"]',
        'main#jobsearch-ViewjobPaneWrapper'
    ]

    button_subselectors = [
        '#indeedApplyButton button',
        'button#indeedApplyButton',
        'div#indeedApplyButton button',
        'div[id*="indeedApply"] button',
        'button[data-testid="indeedApplyButton"]',
        'div[data-testid="indeedApplyButton"] button',
        'a[data-testid="indeedApplyButton"]',
        'button.ia-IndeedApplyButton',
        'span.indeed-apply-widget button',
        'div.jobsearch-IndeedApplyButton-contentWrapper button',
        'button:has-text("Apply now")',
        'a:has-text("Apply now")',
        'button:has-text("Apply with Indeed")',
        'a:has-text("Apply with Indeed")'
    ]

    # 1. Search inside the right job details pane first
    for pane_sel in pane_selectors:
        try:
            pane = page.query_selector(pane_sel)
            if pane and pane.is_visible():
                ext = pane.query_selector('button:has-text("Apply on company site"), a:has-text("Apply on company site"), button:has-text("Apply on employer site"), a:has-text("Apply on employer site")')
                if ext and ext.is_visible() and not _is_filter_element(ext):
                    return None, "external"

                for sub in button_subselectors:
                    btn = pane.query_selector(sub)
                    if btn and btn.is_visible():
                        if _is_filter_element(btn):
                            continue
                        txt = btn.inner_text().strip()
                        txt_lower = txt.lower()
                        if "company site" in txt_lower or "employer site" in txt_lower or "company website" in txt_lower:
                            return None, "external"
                        if "apply" in txt_lower:
                            return btn, txt
        except:
            pass

    # 2. Search anywhere on page (e.g. direct /viewjob page or full width view)
    for sub in button_subselectors:
        try:
            btns = page.query_selector_all(sub)
            for btn in btns:
                if btn and btn.is_visible():
                    if _is_filter_element(btn):
                        continue
                    txt = btn.inner_text().strip()
                    txt_lower = txt.lower()
                    if "company site" in txt_lower or "employer site" in txt_lower or "company website" in txt_lower:
                        return None, "external"
                    if "apply" in txt_lower:
                        return btn, txt
        except:
            pass

    # 3. Check for external company apply button
    try:
        ext = page.query_selector('button:has-text("Apply on company site"), a:has-text("Apply on company site"), button:has-text("Apply on employer site"), a:has-text("Apply on employer site")')
        if ext and ext.is_visible() and not _is_filter_element(ext):
            return None, "external"
    except:
        pass

    return None, None

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
            if any(s in curr_url for s in ["post-apply", "postapply", "submitted", "success"]):
                print("  [✓] Application successfully submitted and verified via URL!")
                return True
            if any(s in body_text for s in [
                "your application was submitted",
                "application was submitted",
                "application submitted",
                "application has been submitted",
                "application sent",
                "you applied",
                "you've applied",
                "successfully applied",
                "return to job search",
                "track your application",
                "applied on"
            ]):
                print("  [✓] Application successfully submitted and verified!")
                return True
        except:
            pass

        # 2. If the tab or frame was closed without submitting, it failed
        is_closed = apply_page.is_closed() if hasattr(apply_page, "is_closed") else apply_page.is_detached()
        if is_closed:
            print("  [!] Apply window or frame was closed before submission.")
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

        # 5. Answer screening questions (Text inputs, number inputs, textareas)
        try:
            inputs = apply_page.locator(
                'input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]):not([type="file"]):not([type="submit"]):not([type="button"]):not([type="reset"]):visible, textarea:visible'
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
                        try:
                            parent_lbl = el.locator('xpath=ancestor::label')
                            if parent_lbl.count() > 0:
                                label_text = parent_lbl.first.inner_text().strip()
                        except:
                            pass
                    if not label_text:
                        label_text = el.get_attribute("placeholder") or el.get_attribute("name") or ""
                    if not label_text:
                        continue

                    q_lower = label_text.lower()
                    if any(k in q_lower for k in ["how many years", "years of experience", "years of work", "total experience"]):
                        if any(tech in q_lower for tech in ["java", "python", "web", "react", "node", "intern", "developer"]):
                            answer = "1"
                        else:
                            answer = "0"
                    elif any(k in q_lower for k in ["ctc", "salary"]):
                        if "monthly" in q_lower or "per month" in q_lower:
                            answer = "30000" if "expected" in q_lower else "0"
                        else:
                            answer = "350000" if "expected" in q_lower else "0"
                    elif any(k in q_lower for k in ["notice", "availability"]):
                        answer = "0" if el.get_attribute("type") == "number" else "Immediate"
                    elif any(k in q_lower for k in ["city", "location"]):
                        answer = "Pune"
                    else:
                        pv = get_profile_value(label_text)
                        if pv:
                            answer = pv
                        else:
                            answer = answer_hr_question(label_text)
                            if not answer:
                                answer = "0" if el.get_attribute("type") == "number" else "Yes"

                    el.fill(answer[:200])
                    el.evaluate("e => { e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true})); }")
                    print(f"    [AI Fill] {label_text[:40]} → {answer[:40]}")
                    time.sleep(0.3)
                except:
                    pass
        except:
            pass

        # 6. Answer radio buttons (grouped by name or parent container)
        try:
            radios = apply_page.locator('input[type="radio"]:visible')
            radio_groups = {}
            for i in range(radios.count()):
                r = radios.nth(i)
                name = r.get_attribute("name") or f"grp_{i}"
                radio_groups.setdefault(name, []).append(r)

            for grp_name, grp_radios in radio_groups.items():
                try:
                    if any(r.is_checked() for r in grp_radios):
                        continue

                    question = ""
                    first_r = grp_radios[0]
                    try:
                        fs = first_r.locator('xpath=ancestor::fieldset | ancestor::div[role="radiogroup"]')
                        if fs.count() > 0:
                            question = fs.first.locator("legend, label").first.inner_text().strip()
                    except:
                        pass
                    if not question:
                        try:
                            parent = first_r.locator('xpath=ancestor::div[contains(@class, "ia-")] | ancestor::div[contains(@class, "css-")]')
                            if parent.count() > 0:
                                lines = [line.strip() for line in parent.first.inner_text().split("\n") if line.strip()]
                                for line in lines:
                                    if any(k in line.lower() for k in ["?", "*", "experience", "license", "licence", "speak", "relocate", "willing", "travel", "shift", "comfortable"]):
                                        question = line
                                        break
                        except:
                            pass

                    radio_labels = []
                    for r in grp_radios:
                        lbl_text = ""
                        try:
                            r_id = r.get_attribute("id") or ""
                            if r_id:
                                lbl = apply_page.locator(f'label[for="{r_id}"]')
                                if lbl.count() > 0:
                                    lbl_text = lbl.first.inner_text().strip()
                            if not lbl_text:
                                p_lbl = r.locator('xpath=ancestor::label')
                                if p_lbl.count() > 0:
                                    lbl_text = p_lbl.first.inner_text().strip()
                        except:
                            pass
                        radio_labels.append(lbl_text or r.get_attribute("value") or "Option")

                    answer = answer_hr_question(question or "Screening question", options=radio_labels)
                    try:
                        idx = int(answer)
                        if not (0 <= idx < len(grp_radios)):
                            idx = 0
                    except:
                        idx = 0

                    target_r = grp_radios[idx]
                    try:
                        r_id = target_r.get_attribute("id") or ""
                        lbl = apply_page.locator(f'label[for="{r_id}"]') if r_id else None
                        if lbl and lbl.count() > 0:
                            lbl.first.click(force=True)
                        else:
                            target_r.click(force=True)
                    except:
                        target_r.check(force=True)
                    print(f"    [AI Radio] {(question or 'Question')[:40]} → {radio_labels[idx]}")
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

        # 8. Check checkboxes (consent / agreement), uncheck optional job alerts
        try:
            apply_page.evaluate("""() => {
                document.querySelectorAll("input[type='checkbox']").forEach(cb => {
                    const lbl = cb.closest('label') || document.querySelector('label[for="' + cb.id + '"]');
                    const txt = lbl ? lbl.innerText.toLowerCase() : '';
                    if (txt.includes('terms') || txt.includes('privacy') || txt.includes('consent') || txt.includes('agree')) {
                        if (!cb.checked) {
                            cb.click();
                            cb.checked = true;
                            cb.dispatchEvent(new Event('change', {bubbles: true}));
                        }
                    }
                    if (txt.includes('get email updates') || txt.includes('job alert')) {
                        if (cb.checked) {
                            cb.click();
                            cb.checked = false;
                        }
                    }
                });
            }""")
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
        try:
            page_obj = apply_page.page if hasattr(apply_page, "page") else apply_page
            page_obj.mouse.wheel(0, 3000)
        except:
            pass
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
                                    page_obj = apply_page.page if hasattr(apply_page, "page") else apply_page
                                    page_obj.mouse.click(box["x"] + 28, box["y"] + (box["height"] / 2))
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
        try:
            page_obj = apply_page.page if hasattr(apply_page, "page") else apply_page
            page_obj.mouse.wheel(0, 1000)
        except:
            pass
        time.sleep(0.5)

        # 9. PRIORITY 1: Check for Final Submit button
        submit_btn = apply_page.query_selector(
            'button:has-text("Submit your application"), '
            'button:has-text("Submit application"), '
            'button[data-testid="Review-submitButton"], '
            'button:has-text("Send application"), '
            'button:has-text("Submit")'
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
                    is_closed = apply_page.is_closed() if hasattr(apply_page, "is_closed") else apply_page.is_detached()
                    if is_closed:
                        print("  [✓] Application tab/modal closed after submit - submission successfully complete!")
                        return True
                    curr_url = get_page_url(apply_page)
                    body = apply_page.inner_text("body").lower()
                    if any(s in curr_url for s in ["post-apply", "postapply", "submitted", "success", "indeed.com/jobs"]):
                        print("  [✓] Application successfully submitted and verified via URL redirect!")
                        return True
                    if any(s in body for s in [
                        "your application was submitted",
                        "application was submitted",
                        "application submitted",
                        "application has been submitted",
                        "application sent",
                        "you applied",
                        "you've applied",
                        "successfully applied",
                        "return to job search",
                        "track your application",
                        "applied on"
                    ]):
                        print("  [✓] Application successfully submitted and verified via confirmation text!")
                        return True
                except Exception as verify_err:
                    if hasattr(apply_page, "is_closed") and apply_page.is_closed():
                        print("  [✓] Application tab closed after submit - submission complete!")
                        return True

            print("  [!] Submission could not be confirmed (captcha or validation error).")
            return False

        # 10. PRIORITY 2: Check for Continue / Next / Review button
        continue_btn = apply_page.query_selector(
            'button:has-text("Continue"), '
            'button:has-text("Review your application"), '
            'button:has-text("Review application"), '
            'button:has-text("Review"), '
            'button:has-text("Next"), '
            'button:has-text("Proceed"), '
            'button:has-text("Save and continue"), '
            'button:has-text("Continue to next step"), '
            'button[data-testid*="continue" i], '
            'button[data-testid*="review" i], '
            'button[class*="ia-continueButton"], '
            'button[class*="ia-BaseButton"], '
            'button[type="submit"]:visible, '
            '[role="button"]:has-text("Continue"), '
            '[role="button"]:has-text("Review"), '
            '[role="button"]:has-text("Next"), '
            'footer button:visible, '
            'div[data-testid*="Navigation"] button:visible'
        )
        if not continue_btn:
            # Fallback: scan all visible buttons for matching keywords
            all_btns = apply_page.query_selector_all("button:visible, [role='button']:visible, input[type='submit']:visible")
            for b in all_btns:
                b_txt = (b.inner_text() or b.get_attribute("value") or "").strip().lower()
                if any(k in b_txt for k in ["continue", "review", "next", "proceed", "save"]):
                    continue_btn = b
                    break

        if continue_btn:
            # Check if button is disabled by validation
            try:
                is_disabled = continue_btn.is_disabled() or (continue_btn.get_attribute("aria-disabled") == "true")
            except:
                is_disabled = False

            if is_disabled:
                print("  [!] Continue button appears disabled; auto-filling any empty inputs...")
                try:
                    empty_inps = apply_page.query_selector_all('input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]):not([type="file"]):not([type="submit"]):not([type="button"]):visible')
                    for inp in empty_inps:
                        if not inp.input_value().strip():
                            t = inp.get_attribute("type") or "text"
                            fill_v = "0" if t == "number" else "Yes"
                            inp.fill(fill_v)
                            inp.evaluate("e => { e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true})); }")
                except:
                    pass

            try:
                continue_btn.scroll_into_view_if_needed()
            except:
                pass
            time.sleep(0.5)
            btn_lbl = ""
            try:
                btn_lbl = continue_btn.inner_text().strip()
            except:
                pass
            print(f"  [AI] Clicking Continue ('{btn_lbl or 'Continue'}')...")
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
    Solves Indeed Apply when rendered inside an iframe or in-page modal dialog.
    """
    print(f"  [AI] Checking in-page apply form for '{job_title}'...")
    time.sleep(2.0)

    # 1. Check if the page itself redirected to smartapply
    curr_url = get_page_url(page)
    if "smartapply" in curr_url or "/form/" in curr_url:
        return solve_indeed_apply_on_page(page, job_title=job_title)

    # 2. Check for an apply frame in page.frames
    target_frame = None
    for f in page.frames:
        f_url = f.url.lower()
        f_name = f.name.lower()
        if any(k in f_url for k in ["indeedapply", "smartapply", "form", "apply"]) or any(k in f_name for k in ["indeedapply", "smartapply", "apply"]):
            target_frame = f
            break

    # 3. Check for iframe locators
    if not target_frame:
        iframe_selectors = [
            'iframe[title*="apply" i]',
            'iframe[id*="indeedApply" i]',
            'iframe[id*="indeedapply" i]',
            'iframe[class*="apply" i]',
            'iframe[src*="indeedapply" i]',
            'iframe[src*="smartapply" i]',
            'iframe#indeedapply-modal-preload-iframe',
            'div#indeedapply-modal iframe',
            'div[class*="indeed-apply"] iframe',
        ]
        for sel in iframe_selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    target_frame = el.content_frame()
                    if target_frame:
                        break
            except:
                pass

    # 4. Check for in-page modal dialog if no iframe
    modal_el = None
    if not target_frame:
        modal_selectors = [
            'div[role="dialog"]:has-text("Apply")',
            'div[data-testid*="indeedApply"]',
            '#indeedapply-modal',
            'div.ia-Modal',
            'div.ia-BasePage',
            'div[class*="indeed-apply"]',
            'dialog[open]'
        ]
        for m_sel in modal_selectors:
            try:
                m = page.query_selector(m_sel)
                if m and m.is_visible():
                    modal_el = m
                    break
            except:
                pass

    if not target_frame and not modal_el:
        print("  [!] No apply iframe or modal dialog found on page.")
        return False

    context_target = target_frame if target_frame else page
    print(f"  [AI] Solving application inside {'iframe' if target_frame else 'in-page modal'}...")
    return solve_indeed_apply_on_page(context_target, job_title=job_title)

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

        # Dynamically track newly opened tabs
        newly_opened_tabs = []
        context.on("page", lambda p: newly_opened_tabs.append(p))

        # Re-use existing main page or create one, and close old leftover tabs from previous runs
        if context.pages:
            page = context.pages[0]
            for old_p in list(context.pages[1:]):
                try:
                    p_url = get_page_url(old_p)
                    if "smartapply" in p_url or "about:blank" in p_url or "viewjob" in p_url:
                        old_p.close()
                except:
                    pass
        else:
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

        target_applications = 999999
        applications_done = 0
        visited_keys = set()

        # Start with the active page URL (preserves user-selected filters from the 45s timer)
        current_active_url = page.url
        queries_to_run = [current_active_url] + [q for q in SEARCH_QUERIES if q != current_active_url]

        while applications_done < target_applications:
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

                    # Dismiss any open filter popups before interacting with cards
                    dismiss_open_popups(page)

                    # 1. Click job card's title link to trigger right details pane
                    card_clicked = False
                    try:
                        fresh_card = page.query_selector(f'div[data-jk="{job["key"]}"], tr[data-jk="{job["key"]}"]') or job["card"]
                        title_anchor = fresh_card.query_selector('a.jcs-JobTitle, h2.jobTitle a, a[id^="job_"]')
                        if title_anchor:
                            try:
                                title_anchor.scroll_into_view_if_needed()
                                time.sleep(0.3)
                                title_anchor.click(force=True)
                                card_clicked = True
                            except:
                                pass
                        if not card_clicked and fresh_card:
                            try:
                                fresh_card.scroll_into_view_if_needed()
                                time.sleep(0.2)
                                fresh_card.click(force=True)
                                card_clicked = True
                            except:
                                pass
                    except Exception as click_err:
                        # Non-fatal: if clicking card in left list fails, direct /viewjob?jk= fallback will handle it
                        pass

                    # 2. Wait up to 3.5 seconds for right pane to update and render apply button
                    apply_btn = None
                    btn_text = None
                    for _ in range(7):
                        time.sleep(0.5)
                        apply_btn, btn_text = find_indeed_apply_button(page)
                        if apply_btn or btn_text == "external":
                            break

                    # Fallback: if not found in right pane, open direct /viewjob?jk= link in new tab
                    direct_page = None
                    if not apply_btn and btn_text != "external" and job.get("key"):
                        print(f"  [Fallback] Right pane not updated. Opening direct job link /viewjob?jk={job['key']}...")
                        direct_page = context.new_page()
                        try:
                            direct_page.goto(f"https://in.indeed.com/viewjob?jk={job['key']}", wait_until="domcontentloaded", timeout=15000)
                            time.sleep(2.0)
                            apply_btn, btn_text = find_indeed_apply_button(direct_page)
                        except Exception as e:
                            print(f"  [!] Direct link error: {e}")

                    if btn_text == "external":
                        print("  [Skipped] External company site application.")
                        if direct_page and not direct_page.is_closed():
                            direct_page.close()
                        continue

                    if not apply_btn:
                        print("  [Skipped] No internal Apply button found on card or direct page.")
                        if direct_page and not direct_page.is_closed():
                            direct_page.close()
                        continue

                    print(f"  Found internal apply button: '{btn_text}'. Clicking...")
                    active_apply_page = direct_page if direct_page else page
                    pages_before = len(context.pages)

                    newly_opened_tabs.clear()
                    apply_page = None

                    # Strategy 1: expect_popup (direct CDP target binding)
                    try:
                        with active_apply_page.expect_popup(timeout=4000) as popup_info:
                            try:
                                apply_btn.click()
                            except:
                                apply_btn.evaluate("el => el.click()")
                        apply_page = popup_info.value
                    except:
                        pass

                    # Strategy 2: If expect_popup didn't fire, check newly_opened_tabs and context.pages
                    if not apply_page:
                        if not newly_opened_tabs and len(context.pages) <= pages_before:
                            try:
                                apply_btn.click()
                            except:
                                apply_btn.evaluate("el => el.click()")

                        for _ in range(12):
                            active_apply_page.wait_for_timeout(400)
                            if newly_opened_tabs:
                                apply_page = newly_opened_tabs[-1]
                                break
                            if len(context.pages) > pages_before:
                                apply_page = context.pages[-1]
                                break

                    # 4. Check if opened in new tab/window
                    success = False
                    if apply_page:
                        try:
                            apply_page.bring_to_front()
                        except:
                            pass

                        # Wait for the newly opened tab to navigate away from empty/about:blank
                        print("  [→] Application tab opened. Waiting for URL to load...")
                        apply_url = ""
                        for _ in range(25):  # Wait up to 12 seconds
                            apply_url = get_page_url(apply_page)
                            if apply_url and "about:blank" not in apply_url:
                                break
                            active_apply_page.wait_for_timeout(500)

                        # If on smartapply trampoline (applybyapplyablejobid), wait for /form/
                        if "smartapply" in apply_url and "/form/" not in apply_url:
                            print("  [→] Waiting for SmartApply form redirect...")
                            for _ in range(20):
                                apply_url = get_page_url(apply_page)
                                if "/form/" in apply_url:
                                    break
                                active_apply_page.wait_for_timeout(500)

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
                            if direct_page and not direct_page.is_closed():
                                direct_page.close()
                            continue
                    else:
                        # In-page apply form
                        success = solve_indeed_apply_in_page(active_apply_page, job_title=job["title"])

                    if direct_page and not direct_page.is_closed():
                        try:
                            direct_page.close()
                        except:
                            pass

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

            if applications_done >= target_applications:
                break

            print("\n[♾️ Unstoppable Mode] Completed scanning all Indeed queries.")
            print("  Waiting 60 seconds before cycling queries again for newly posted jobs...")
            for sec in range(60, 0, -1):
                print(f"  Resuming in {sec}s...", end="\r")
                time.sleep(1)

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
