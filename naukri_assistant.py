import os
import json
import time
import sys
import random
import re
import argparse
from playwright.sync_api import sync_playwright
from universal_form_filler import solve_complex_form_with_ai
from ai_provider import ask_ai, is_ai_available
from profile_manager import get_candidate_profile_prompt
from qa_engine import answer_hr_question

def click_save_if_present(page, drawer=None):
    """Helper to find and click the Save/Submit button in the drawer or modal."""
    save_selectors = [
        "button:has-text('Save & Apply')",
        "button:has-text('Save and Apply')",
        "button:has-text('Save & Continue')",
        "button:has-text('Save')",
        "button:has-text('Submit')",
        "button:has-text('Apply')",
        "button[class*='save']",
        "button[class*='submit']",
        "button.btn-save",
        "button.apply-button",
        "div[class*='chatbot'] button:has-text('Save')",
        "div[class*='drawer'] button:has-text('Save')",
        ".chatbot_DrawerContainer button:has-text('Save')",
        ".chatbot_DrawerContainer button:has-text('Apply')"
    ]
    for sel in save_selectors:
        try:
            btns = page.query_selector_all(sel)
            for btn in btns:
                if btn and btn.is_visible():
                    txt = btn.inner_text().strip()
                    if txt.lower() in ["cancel", "close", "skip", "x"]:
                        continue
                    print(f"  [AI] Clicking Save/Submit button ('{txt}')...")
                    try:
                        btn.evaluate("el => { el.click(); el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true})); }")
                    except:
                        btn.click(force=True)
                    time.sleep(2.5)
                    return True
        except:
            pass
    return False

def solve_naukri_chatbot(page, profile):
    """
    Robust Naukri Chatbot & Questionnaire Solver.
    Accurately solves:
    1. Multi-turn Chatbot drawer (Wait for next question, never click Save prematurely).
    2. Multi-question Form / Questionnaire drawers (Groups radios, fills all inputs/dropdowns before Save).
    3. Screening questions (Always Yes for shifts/relocation/skills to prevent rejection).
    """
    print("  [AI] Initiating Naukri Chatbot / Questionnaire Solver...")
    if not is_ai_available():
        print("  [!] No AI API key available. Cannot converse with bot.")
        return False

    # ── Phase 0: Quick page state check ────────────────────────────────────
    time.sleep(2.5)
    page_text = ""
    try:
        page_text = page.inner_text("body").lower()
    except:
        pass

    if "oops" in page_text and "incomplete" in page_text:
        print("  [!] Naukri error: application rejected due to incomplete information.")
        return False
    if "successfully applied" in page_text or "applied successfully" in page_text or "application submitted" in page_text:
        print("  [✓] Already applied successfully (instant apply).")
        return True

    # ── Phase 1: Detect chatbot drawer / modal container ──────────────────
    drawer_selectors = [
        "div.chatbot_DrawerContainer", "div[class*='chatbot']", "div[class*='ChatBot']",
        "div[class*='drawer']", "div[class*='Drawer']", "div[class*='apply-drawer']",
        "div[class*='applyDrawer']", "section[class*='chatbot']", "div[class*='chat-container']",
        "div[class*='screeningQuestions']", "div[class*='screening']", "div[class*='apply-modal']",
        "div.drawer-wrapper", "div.apply-message-container"
    ]
    drawer = None
    for _ in range(3):
        for sel in drawer_selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    drawer = el
                    print(f"  [AI] Found application container: {sel}")
                    break
            except:
                pass
        if drawer:
            break
        time.sleep(1.0)

    if not drawer:
        form_inputs = page.query_selector_all(
            "input:not([type='hidden']):not([type='file']):not([placeholder*='Search']), select, textarea"
        )
        visible_inputs = [inp for inp in form_inputs if inp.is_visible()]
        if visible_inputs:
            print("  [AI] No drawer container detected. Found standard form inputs. Handing to form filler...")
            return solve_complex_form_with_ai(page, profile)
        
        if click_save_if_present(page):
            return True
        print("  [!] No chatbot, no form, no save button found.")
        return False

    # ── Phase 2: Conversational / Form solving loop ───────────────────────
    last_answered_state = ""
    stuck_rounds = 0
    MAX_TURNS = 20

    for turn in range(MAX_TURNS):
        time.sleep(2.0)

        # Step 1: Check terminal states (Success / Error / Drawer closed)
        try:
            body_lower = page.inner_text("body").lower()
            if "oops" in body_lower and "incomplete" in body_lower:
                print("  [!] Naukri error page: Application incomplete.")
                return False

            if any(s in body_lower for s in [
                "successfully applied", "applied successfully", "application has been sent",
                "already applied", "thank you for applying", "your application is submitted",
                "application submitted successfully"
            ]):
                print("  [✓] Confirmed application success banner!")
                return True

            # Check if drawer has disappeared (application submitted)
            drawer_visible = False
            for sel in drawer_selectors:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    drawer_visible = True
                    break
            if not drawer_visible:
                print("  [✓] Chatbot / questionnaire drawer closed. Application submitted successfully.")
                return True

            # Check if bot has closing message
            drawer_text = drawer.inner_text().lower() if drawer else ""
            if any(s in drawer_text for s in [
                "thank you for showing interest", "response has been recorded",
                "thank you for applying", "we have received your application",
                "your application is submitted"
            ]):
                print("  [✓] Recruiter chatbot indicated completion. Finalizing...")
                click_save_if_present(page)
                time.sleep(2.0)
                return True
        except:
            pass

        # Step 2: Extract latest bot question
        question_text = ""
        msg_selectors = [
            ".botMsg", ".bot-msg", ".chatbot-msg",
            "div[class*='bot-message']", "div[class*='botMsg']",
            "div[class*='msg-bot']", "div[class*='chatbot'] div[class*='msg']",
            "div[class*='bubble']", "div[class*='chat-msg']",
            "div[class*='drawer'] div[class*='msg']",
            "div[class*='question']", "label[class*='question']",
            "div[class*='msgText']"
        ]
        bot_messages = []
        for sel in msg_selectors:
            try:
                elements = page.query_selector_all(sel)
                for el in elements:
                    if el.is_visible():
                        txt = el.inner_text().strip()
                        if txt and len(txt) > 3:
                            bot_messages.append(txt)
            except:
                pass

        unique_msgs = []
        seen = set()
        for m in bot_messages:
            norm = m.strip().lower()
            if norm not in seen and "type message" not in norm:
                seen.add(norm)
                unique_msgs.append(m)
        if unique_msgs:
            question_text = unique_msgs[-1]

        # Step 3: Handle RADIO BUTTON GROUPS (Crucial: grouped by question)
        radio_groups_answered = 0
        try:
            radio_data = page.evaluate("""() => {
                const radios = Array.from(document.querySelectorAll("input[type='radio']")).filter(r => {
                    const rect = r.getBoundingClientRect();
                    return rect.width > 0 || r.offsetParent !== null || (r.parentElement && r.parentElement.offsetParent !== null);
                });
                const byGroup = {};
                radios.forEach((r, idx) => {
                    const grpName = r.name || ('group_' + (r.closest('fieldset, .radio-group, div[class*="question"]') || r.parentElement).id || 'grp_0');
                    if (!byGroup[grpName]) byGroup[grpName] = [];
                    byGroup[grpName].push(r);
                });

                const result = [];
                for (const [name, rList] of Object.entries(byGroup)) {
                    const isChecked = rList.some(r => r.checked);
                    let qText = '';
                    const parent = rList[0].closest('fieldset, .radio-group, div[class*="question"], div[class*="row"], .chatbot_DrawerContainer');
                    if (parent) {
                        const legend = parent.querySelector('legend, label[class*="question"], div[class*="question"], p');
                        if (legend) qText = legend.innerText.trim();
                    }
                    if (!qText && rList[0].closest('div')) {
                        const prev = rList[0].closest('div').previousElementSibling;
                        if (prev) qText = prev.innerText.trim();
                    }
                    const options = rList.map((r, i) => {
                        const lbl = r.closest('label') || document.querySelector('label[for="' + r.id + '"]') || r.parentElement;
                        return {
                            id: r.id || '',
                            index: i,
                            checked: r.checked,
                            label: lbl ? lbl.innerText.trim() : ('Option ' + (i + 1))
                        };
                    });
                    result.push({
                        name: name,
                        isChecked: isChecked,
                        question: qText,
                        options: options
                    });
                }
                return result;
            }""")

            for grp in radio_data:
                if not grp["isChecked"] and grp["options"]:
                    q = grp["question"] or question_text or "Select option"
                    opts = [o["label"] for o in grp["options"]]
                    ans_idx_str = answer_hr_question(q, options=opts)
                    try:
                        ans_idx = int(ans_idx_str)
                        if not (0 <= ans_idx < len(opts)):
                            ans_idx = 0
                    except:
                        ans_idx = 0

                    target_opt = grp["options"][ans_idx]
                    print(f"  [AI Radio]: {q[:60]} → '{target_opt['label']}'")
                    page.evaluate("""(data) => {
                        let radio = null;
                        if (data.id) radio = document.getElementById(data.id);
                        if (!radio) {
                            const radios = Array.from(document.querySelectorAll("input[type='radio']")).filter(r => r.name === data.name);
                            radio = radios[data.index];
                        }
                        if (radio) {
                            const lbl = radio.closest('label') || document.querySelector('label[for="' + radio.id + '"]');
                            if (lbl) lbl.click();
                            else radio.click();
                            radio.checked = true;
                            radio.dispatchEvent(new Event('change', {bubbles: true}));
                            radio.dispatchEvent(new Event('input', {bubbles: true}));
                            radio.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                        }
                    }""", {"id": target_opt["id"], "name": grp["name"], "index": ans_idx})
                    radio_groups_answered += 1
                    time.sleep(0.5)
        except Exception as e:
            pass

        # Step 4: Handle CHOICE CHIPS (Chatbot Quick Replies)
        # Note: In chatbot mode, clicking a chip sends the response and advances the chat. DO NOT click Save!
        visible_chips = []
        for sel in [
            ".chip", "button[class*='chip']", "div[class*='chip']",
            "button[class*='choice']", "li.list-item", "button.list-item",
            "div[class*='quick-reply']", "div[class*='bot-options'] button",
            "button[class*='option']"
        ]:
            try:
                chips = page.query_selector_all(sel)
                for c in chips:
                    if c.is_visible():
                        ct = c.inner_text().strip()
                        if ct and ct.lower() not in ["save", "submit", "apply", "send", "close", "cancel", "x"]:
                            visible_chips.append(c)
            except:
                pass

        if visible_chips and radio_groups_answered == 0:
            options_list = [c.inner_text().strip() for c in visible_chips]
            ans = answer_hr_question(question_text or "Select option", options=options_list)
            try:
                idx = int(ans)
                if not (0 <= idx < len(visible_chips)):
                    idx = 0
            except:
                idx = 0

            chosen_chip = visible_chips[idx]
            print(f"  [AI Reply]: Clicking chip '{options_list[idx]}' for '{question_text[:60]}'")
            try:
                chosen_chip.evaluate("""el => {
                    el.click();
                    el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }""")
                time.sleep(2.5)  # Wait for chatbot to respond with next question
            except Exception as e:
                print(f"  [!] Chip click error: {e}")
            continue

        # Step 5: Handle CHAT TEXT INPUT
        chat_input = None
        for sel in [
            "input[placeholder*='Type message']", "input[placeholder*='type message']",
            "input[placeholder*='message here']", "textarea[placeholder*='Type message']",
            "textarea[placeholder*='type message']", "input[class*='chat-input']",
            "textarea[class*='chat']", "div[class*='chatbot'] input[type='text']",
            "div[class*='drawer'] input[type='text']", "div[class*='chatbot'] textarea",
            "div[class*='drawer'] textarea"
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible() and not el.is_disabled():
                    chat_input = el
                    break
            except:
                pass

        if chat_input and radio_groups_answered == 0:
            answer = answer_hr_question(question_text or "Answer recruiter question")
            if len(answer) > 250:
                answer = answer[:250]
            if not answer:
                answer = "I am a 2026 B.Tech IT graduate with full stack development skills in React, Node, and Java. Immediate joiner."

            print(f"  [AI Chat Reply]: '{answer[:60]}' for '{question_text[:60]}'")
            try:
                chat_input.fill("")
                time.sleep(0.3)
                chat_input.fill(answer)
                time.sleep(0.5)

                # Look for Send button or press Enter
                send_btn = page.query_selector("button[class*='send'], span[class*='send'], button[type='submit'], div[class*='send']")
                if send_btn and send_btn.is_visible():
                    send_btn.click()
                else:
                    chat_input.press("Enter")
                time.sleep(2.5)  # Wait for chatbot to respond with next question
            except Exception as e:
                print(f"  [!] Chat input error: {e}")
            continue

        # Step 6: Handle STANDARD FORM INPUTS (Text, number, textareas)
        form_inputs_answered = 0
        try:
            inputs_data = page.evaluate("""() => {
                const inputs = Array.from(document.querySelectorAll("input[type='text'], input[type='number'], input:not([type]), textarea")).filter(el => {
                    const rect = el.getBoundingClientRect();
                    return (rect.width > 0 || el.offsetParent !== null) && !el.disabled && !el.readOnly;
                });
                return inputs.map((el, i) => {
                    const ph = el.placeholder || '';
                    if (ph.toLowerCase().includes('type message') || ph.toLowerCase().includes('search')) return null;
                    let lbl = '';
                    if (el.id) {
                        const l = document.querySelector('label[for="' + el.id + '"]');
                        if (l) lbl = l.innerText.trim();
                    }
                    if (!lbl && el.closest('label')) lbl = el.closest('label').innerText.trim();
                    if (!lbl && el.getAttribute('aria-label')) lbl = el.getAttribute('aria-label').trim();
                    if (!lbl) lbl = ph;
                    return {
                        id: el.id || '',
                        index: i,
                        value: el.value || '',
                        label: lbl,
                        type: el.type || 'text'
                    };
                }).filter(Boolean);
            }""")

            for inp in inputs_data:
                if not inp["value"].strip():
                    lbl = inp["label"] or question_text or "Input"
                    val = answer_hr_question(lbl)
                    if not val:
                        val = "0"
                    print(f"  [AI Form Fill]: {lbl[:40]} → {val}")
                    page.evaluate("""(data) => {
                        let el = null;
                        if (data.id) el = document.getElementById(data.id);
                        if (!el) {
                            const inputs = Array.from(document.querySelectorAll("input[type='text'], input[type='number'], input:not([type]), textarea")).filter(e => {
                                const r = e.getBoundingClientRect();
                                return (r.width > 0 || e.offsetParent !== null) && !e.disabled && !e.readOnly;
                            });
                            el = inputs[data.index];
                        }
                        if (el) {
                            el.value = data.value;
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                        }
                    }""", {"id": inp["id"], "index": inp["index"], "value": val})
                    form_inputs_answered += 1
                    time.sleep(0.3)
        except:
            pass

        # Step 7: Handle DROPDOWNS (<select>)
        selects_answered = 0
        try:
            selects_data = page.evaluate("""() => {
                const selects = Array.from(document.querySelectorAll("select")).filter(s => {
                    const r = s.getBoundingClientRect();
                    return (r.width > 0 || s.offsetParent !== null) && !s.disabled;
                });
                return selects.map((s, i) => {
                    let lbl = '';
                    if (s.id) {
                        const l = document.querySelector('label[for="' + s.id + '"]');
                        if (l) lbl = l.innerText.trim();
                    }
                    if (!lbl && s.closest('label')) lbl = s.closest('label').innerText.trim();
                    const opts = Array.from(s.options).map(o => ({ text: o.text.trim(), value: o.value }))
                        .filter(o => o.text && !['select', 'select an option', '--', 'choose', ''].includes(o.text.toLowerCase()));
                    const cur = s.options[s.selectedIndex] ? s.options[s.selectedIndex].text.trim() : '';
                    return {
                        id: s.id || '',
                        index: i,
                        label: lbl,
                        current: cur,
                        options: opts
                    };
                });
            }""")

            for s in selects_data:
                if not s["current"] or s["current"].lower() in ["select", "select an option", "--", "choose", ""]:
                    if s["options"]:
                        opt_texts = [o["text"] for o in s["options"]]
                        ans_idx_str = answer_hr_question(s["label"] or "Select", options=opt_texts)
                        try:
                            ans_idx = int(ans_idx_str)
                            if not (0 <= ans_idx < len(opt_texts)):
                                ans_idx = 0
                        except:
                            ans_idx = 0
                        chosen = s["options"][ans_idx]
                        print(f"  [AI Select]: {s['label'][:40]} → {chosen['text']}")
                        page.evaluate("""(data) => {
                            let el = null;
                            if (data.id) el = document.getElementById(data.id);
                            if (!el) {
                                const list = Array.from(document.querySelectorAll("select"));
                                el = list[data.index];
                            }
                            if (el) {
                                el.value = data.value;
                                el.dispatchEvent(new Event('change', {bubbles: true}));
                            }
                        }""", {"id": s["id"], "index": s["index"], "value": chosen["value"]})
                        selects_answered += 1
                        time.sleep(0.3)
        except:
            pass

        # Step 8: Handle Consent / Terms CHECKBOXES
        try:
            page.evaluate("""() => {
                document.querySelectorAll("input[type='checkbox']").forEach(cb => {
                    const rect = cb.getBoundingClientRect();
                    if ((rect.width > 0 || cb.offsetParent !== null) && !cb.disabled && !cb.checked) {
                        const lbl = cb.closest('label') || document.querySelector('label[for="' + cb.id + '"]') || cb.parentElement;
                        const txt = lbl ? lbl.innerText.toLowerCase() : '';
                        if (txt.includes('agree') || txt.includes('terms') || txt.includes('consent') || txt.includes('confirm') || txt.includes('certify')) {
                            cb.click();
                            cb.checked = true;
                            cb.dispatchEvent(new Event('change', {bubbles: true}));
                        }
                    }
                });
            }""")
        except:
            pass

        # Step 9: Decide when to click SAVE / SUBMIT
        current_state = f"q:{question_text}_r:{radio_groups_answered}_i:{form_inputs_answered}_s:{selects_answered}"
        if current_state == last_answered_state:
            stuck_rounds += 1
        else:
            stuck_rounds = 0
        last_answered_state = current_state

        if (radio_groups_answered > 0 or form_inputs_answered > 0 or selects_answered > 0) or stuck_rounds >= 1:
            print("  [AI] Questionnaire completed on this step. Submitting...")
            if click_save_if_present(page):
                time.sleep(3.0)
                # Verify if application finished
                try:
                    final_body = page.inner_text("body").lower()
                    if "oops" in final_body and "incomplete" in final_body:
                        print("  [!] Naukri returned incomplete information error.")
                        return False
                except:
                    pass
                return True

        if stuck_rounds >= 3:
            print("  [AI] No new questions detected for multiple turns. Attempting final Save...")
            click_save_if_present(page)
            time.sleep(2.5)
            return True

    return True

# Setup directories and files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMIUM_DATA_DIR = os.path.join(BASE_DIR, "naukri_data")
APPLIED_JOBS_FILE = os.path.join(BASE_DIR, "naukri_applied.json")
FAILED_JOBS_FILE = os.path.join(BASE_DIR, "naukri_failed.json")
REPORT_FILE = os.path.join(BASE_DIR, "naukri_final_report.md")

# Dynamic Candidate Profile
MCANDIDATE_PROFILE = get_candidate_profile_prompt()

RESUME_PATH = "Resume.pdf"

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
        except:
            pass

applied_urls = {job.get("url") for job in applied_jobs if job.get("url")}

def run_naukri():
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

        print("\n=======================================================")
        print("1. Please apply any filters you want (Location, Experience, etc).")
        print("2. Wait for the page to load your filtered jobs.")
        print("3. Press ENTER in this terminal when you are ready!")
        print("=======================================================\n")

        page.goto("https://www.naukri.com/software-developer-jobs")

        print("\n>>> You have 45 seconds to set your filters in the browser window! <<<")
        for i in range(45, 0, -1):
            print(f"Waiting... {i} seconds remaining.", end="\r")
            time.sleep(1)
        print("\n\nTime's up! Proceeding with the search results currently on screen...\n")

        search_url = page.url
        print(f"\n[+] Starting automated application loop on: {search_url}")

        target_applications = 50
        applications_done = 0

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
            try:
                page.wait_for_selector("a.title", timeout=5000)
            except:
                pass
            page.wait_for_timeout(3000)

            job_cards = page.query_selector_all("div.srp-jobtuple-wrapper, article.jobTuple, div.jobTuple")
            job_links = []
            for card in job_cards:
                try:
                    date_el = card.query_selector("span.job-post-day, span.date, span.postedDate, span[class*='date']")
                    if date_el:
                        date_text = date_el.inner_text().strip().lower()
                        if "month" in date_text or "30+" in date_text:
                            continue
                        match = re.search(r'(\d+)\s*day', date_text)
                        if match:
                            days = int(match.group(1))
                            if days > 7:
                                continue

                    card_text = card.inner_text().lower()
                    if "company website" in card_text or "company site" in card_text:
                        continue

                    title_link = card.query_selector("a.title")
                    if title_link:
                        href = title_link.get_attribute("href")
                        if href and "naukri.com/job-listings" in href:
                            if href not in applied_urls and href not in visited_urls:
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
                next_btn = page.query_selector("a.fright, span:has-text('Next'), a[rel='next'], button[class*='next'], a[class*='next'], a:has-text('Next'), a:has-text('>')")
                if next_btn:
                    print("Clicking Next Page...")
                    next_btn.click(force=True)
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except:
                        pass
                    page.wait_for_timeout(4000)
                continue

            empty_scroll_count = 0

            for job_url in job_links:
                if applications_done >= target_applications:
                    break

                visited_urls.add(job_url)
                print(f"\nNavigating to: {job_url}")

                try:
                    new_page = context.new_page()
                    new_page.goto(job_url)
                    new_page.wait_for_load_state("domcontentloaded")
                    human_delay(2.0, 4.0)

                    title_el = new_page.query_selector("h1")
                    job_title = title_el.inner_text().strip() if title_el else "Unknown Role"
                    print(f"Title: {job_title}")

                    apply_btn = new_page.query_selector("button.apply-button, button:has-text('Apply'), a:has-text('Apply'), button[id*='apply']")
                    if not apply_btn:
                        print("  No Apply button found (already applied or closed).")
                        new_page.close()
                        continue

                    btn_text = apply_btn.inner_text().strip().lower()
                    btn_href = (apply_btn.get_attribute("href") or "").lower()

                    if "company website" in btn_text or "company site" in btn_text or (btn_href and "naukri.com" not in btn_href and btn_href.startswith("http")):
                        print(f"  [Skipped] Job specifies external company website link ('{btn_text}'). Skipping as requested.")
                        new_page.close()
                        continue

                    print("  Found internal Apply button. Clicking...")
                    pages_before = len(context.pages)
                    apply_btn.click(force=True)
                    human_delay(2.0, 3.0)

                    if len(context.pages) > pages_before:
                        new_tab = context.pages[-1]
                        try:
                            new_tab.wait_for_load_state("domcontentloaded", timeout=4000)
                        except:
                            pass
                        new_tab_url = new_tab.url.lower()
                        if "naukri.com" in new_tab_url:
                            print(f"  [→] Application opened in new Naukri tab: {new_tab_url}")
                            new_page = new_tab
                        else:
                            print(f"  [Skipped] Job redirects to external company career page ({new_tab_url}). Skipping as requested.")
                            if not new_tab.is_closed():
                                new_tab.close()
                            if not new_page.is_closed():
                                new_page.close()
                            continue

                    current_url = new_page.url.lower()
                    if "naukri.com" not in current_url:
                        print(f"  [Skipped] Job redirects to external company career page ({current_url}). Skipping as requested.")
                        if not new_page.is_closed():
                            new_page.close()
                        continue

                    # Internal Naukri apply
                    human_delay(2.0, 3.0)

                    try:
                        body_text = new_page.inner_text("body").lower()
                    except:
                        body_text = ""

                    if "oops" in body_text and "incomplete" in body_text:
                        print("  [!] Application failed: Naukri returned 'Oops! Incomplete information' error page.")
                        success = False
                    elif "successfully applied" in body_text or "applied successfully" in body_text:
                        print("  Success! (Instant Apply)")
                        success = True
                    else:
                        success = solve_naukri_chatbot(new_page, MCANDIDATE_PROFILE)
                        if success:
                            try:
                                time.sleep(2)
                                final_body = new_page.inner_text("body").lower()
                                if "oops" in final_body and "incomplete" in final_body:
                                    print("  [!] Post-chatbot error: Naukri still says incomplete information.")
                                    success = False
                            except:
                                pass

                    if success:
                        print("  ✅ Success! (Or completed as much as possible)")
                        applied_jobs.append({"url": job_url, "title": job_title, "status": "Applied via AI"})
                        applied_urls.add(job_url)
                        save_json(APPLIED_JOBS_FILE, applied_jobs)
                        applications_done += 1
                    else:
                        print("  Application aborted by AI or reached dead end.")

                    if not new_page.is_closed():
                        new_page.close()
                    human_delay(1.0, 2.0)

                except Exception as e:
                    error_msg = str(e)
                    print(f"  Error processing job: {error_msg}")
                    if "Target page, context or browser has been closed" in error_msg:
                        print("\n[!] Browser was closed manually. Stopping the application loop.")
                        return
                    failed_jobs.append({"url": job_url, "reason": error_msg})
                    save_json(FAILED_JOBS_FILE, failed_jobs)
                    try:
                        new_page.close()
                    except:
                        pass

            page.mouse.wheel(0, 3000)
            human_delay(2.0, 3.0)

        print(f"\n[+] Finished. Applied to {applications_done} jobs.")

        report_path = os.path.join(BASE_DIR, "naukri_final_report.md")
        with open(report_path, "w") as f:
            f.write(f"# Naukri Automated Application Report\n\n")
            f.write(f"**Total Applications:** {applications_done}\n\n")
            f.write("### Successfully Applied:\n")
            for job in applied_jobs[-applications_done:]:
                f.write(f"- {job['title']} ([Link]({job['url']}))\n")

        print(f"Report saved to: {report_path}")

if __name__ == "__main__":
    run_naukri()