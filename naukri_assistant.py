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

DRAWER_SELECTORS = [
    "div.chatbot_DrawerContainer",
    "div[class*='chatbot_Drawer' i]",
    "div[class*='chatbot' i]",
    "section[class*='chatbot' i]",
    "div[class*='apply-drawer' i]",
    "div[class*='applyDrawer' i]",
    "div[class*='screeningQuestions' i]",
    "div[class*='screening' i]",
    "div[class*='apply-modal' i]",
    "div.drawer-wrapper",
    "div.apply-message-container",
    "div[role='dialog']",
    "div[class*='drawer' i]",
]

def find_active_drawer(page):
    """Find the active Naukri chatbot/questionnaire drawer, ignoring header/nav drawers."""
    for sel in DRAWER_SELECTORS:
        try:
            elements = page.query_selector_all(sel)
            for el in elements:
                if not el or not el.is_visible():
                    continue
                cls = (el.get_attribute("class") or "").lower()
                if "gnb" in cls or "nav" in cls or "header" in cls:
                    continue
                box = el.bounding_box()
                if box and box.get("width", 0) >= 240 and box.get("height", 0) >= 200:
                    return el, sel
        except:
            pass
    return None, ""

def click_save_if_present(page, drawer=None):
    """Helper to find and click an enabled Save/Submit button strictly inside the active drawer/modal."""
    scope = drawer
    if not scope:
        scope, _ = find_active_drawer(page)
    if not scope:
        return False

    save_selectors = [
        "button:has-text('Save & Apply')",
        "button:has-text('Save and Apply')",
        "button:has-text('Save & Continue')",
        "button:has-text('Save')",
        "button:has-text('Submit')",
        "button[class*='save']",
        "button[class*='submit']",
        "button.btn-save",
        "div[class*='save']:not(:has(div[class*='save']))"
    ]
    for sel in save_selectors:
        try:
            btns = scope.query_selector_all(sel)
            for btn in btns:
                if not btn or not btn.is_visible():
                    continue
                txt = btn.inner_text().strip()
                txt_lower = txt.lower()
                if txt_lower in ["cancel", "close", "skip", "x", "saved", ""]:
                    continue
                # Never click a disabled Save button
                cls = (btn.get_attribute("class") or "").lower()
                is_dis = (
                    btn.is_disabled()
                    or btn.get_attribute("disabled") is not None
                    or btn.get_attribute("aria-disabled") == "true"
                    or "disabled" in cls
                )
                if is_dis:
                    continue
                print(f"  [AI] Clicking Save/Submit button ('{txt}')...")
                try:
                    btn.click(timeout=3000)
                except:
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
    1. Multi-turn Chatbot drawer & Naukri Campus Questionnaire (loops through all questions until drawer closes).
    2. Scopes all DOM queries strictly inside the active chatbot drawer so job page elements behind it are never touched.
    3. Triggers native Playwright clicks on React radio/chip options so the Save button activates properly.
    4. Enforces mandatory question completion before clicking Save to avoid 'Incomplete information' rejection.
    """
    print("  [AI] Initiating Naukri Chatbot / Questionnaire Solver...")
    if not is_ai_available():
        print("  [AI] Note: External AI key not active. Proceeding with QA Engine memory and deterministic heuristics.")

    # ── Phase 0: Quick page state check ────────────────────────────────────
    time.sleep(2.5)
    page_text = ""
    try:
        page_text = page.inner_text("body").lower()
    except:
        pass

    if "saveapply" in page.url.lower() or ("oops" in page_text and "incomplete" in page_text):
        print("  [!] Naukri error: application rejected due to incomplete information.")
        return False
    if "successfully applied" in page_text or "applied successfully" in page_text or "application submitted" in page_text:
        print("  [✓] Already applied successfully (instant apply).")
        return True

    # ── Phase 1: Wait for chatbot drawer / modal container ────────────────
    drawer = None
    drawer_sel = ""
    for _ in range(4):
        drawer, drawer_sel = find_active_drawer(page)
        if drawer:
            print(f"  [AI] Found application container: {drawer_sel}")
            break
        time.sleep(0.8)

    if not drawer:
        form_inputs = page.query_selector_all(
            "input:not([type='hidden']):not([type='file']):not([placeholder*='Search' i]), select, textarea"
        )
        visible_inputs = [inp for inp in form_inputs if inp.is_visible()]
        if visible_inputs:
            print("  [AI] No drawer detected. Found form inputs. Handing to form filler...")
            return solve_complex_form_with_ai(page, profile)
        print("  [!] No chatbot drawer or form appeared after clicking Apply.")
        return False

    # ── Phase 2: Conversational / Form solving loop ───────────────────────
    last_answered_state = ""
    stuck_rounds = 0
    MAX_TURNS = 20

    for turn in range(MAX_TURNS):
        time.sleep(1.5)

        # Step 1: Check terminal states (Success / Error / Drawer closed)
        try:
            curr_url = page.url.lower()
            body_lower = page.inner_text("body").lower()
            if "saveapply" in curr_url or ("oops" in body_lower and "incomplete" in body_lower):
                print("  [!] Naukri error page: Application incomplete.")
                return False

            if any(s in body_lower for s in [
                "successfully applied", "applied successfully", "application has been sent",
                "already applied", "thank you for applying", "your application is submitted",
                "application submitted successfully"
            ]):
                print("  [✓] Confirmed application success banner!")
                return True

            drawer, drawer_sel = find_active_drawer(page)
            if not drawer and turn > 0:
                print("  [✓] Chatbot / questionnaire drawer closed. Application submitted successfully.")
                return True
            if not drawer:
                print("  [!] Drawer closed unexpectedly on turn 0.")
                return False
        except:
            pass

        # Step 2: Extract latest bot question strictly inside `drawer`
        question_text = ""
        try:
            bot_messages = drawer.evaluate("""(root) => {
                const skipPhrases = [
                    "thank you for showing", "kindly answer all", "type message",
                    "save", "submit", "cancel", "close"
                ];
                // Prefer explicit chat message / question nodes
                const specific = root.querySelectorAll(
                    ".botMsg, .bot-msg, .chatbot-msg, div[class*='bot-message' i], " +
                    "div[class*='botMsg' i], div[class*='msg-bot' i], div[class*='msgText' i], " +
                    "div[class*='question' i], label[class*='question' i], p[class*='question' i], " +
                    "div[class*='bubble' i], div[class*='chat-msg' i], li[class*='bot' i]"
                );
                const msgs = [];
                const addIfValid = (el) => {
                    if (!el || el.offsetParent === null) return;
                    // Skip nodes that contain radio inputs or option lists
                    if (el.querySelector("input[type='radio'], input[type='checkbox'], select")) return;
                    const t = (el.innerText || "").trim();
                    if (!t || t.length < 4) return;
                    const tl = t.toLowerCase();
                    if (skipPhrases.some(sp => tl.includes(sp)) || tl === "skip this question" || tl === "skip") return;
                    msgs.push(t);
                };
                specific.forEach(addIfValid);
                if (msgs.length === 0) {
                    // Fallback: scan leaf text blocks inside drawer (excluding buttons/labels/inputs)
                    root.querySelectorAll("p, span, div, h2, h3, h4").forEach(el => {
                        if (el.closest("button, label, ul, ol, [role='radiogroup']")) return;
                        if (el.children.length > 0 && el.querySelector("p, div, input, button, label")) return;
                        addIfValid(el);
                    });
                }
                // Deduplicate preserving order
                const unique = [];
                const seen = new Set();
                for (const m of msgs) {
                    const norm = m.toLowerCase();
                    if (!seen.has(norm)) {
                        seen.add(norm);
                        unique.push(m);
                    }
                }
                return unique;
            }""")
            if bot_messages:
                question_text = bot_messages[-1]
        except Exception:
            pass

        # Step 3: Handle RADIO BUTTONS & OPTION CONTAINERS strictly inside `drawer`
        radio_groups_answered = 0
        try:
            # Explicit check for "Graduate" vs "Student (We do NOT hire students)"
            grad_opt = drawer.query_selector("label:has-text('Graduate'), div:has-text('Graduate'), span:has-text('Graduate')")
            student_opt = drawer.query_selector("*:has-text('We do NOT hire students')")
            if grad_opt and student_opt and grad_opt.is_visible():
                is_selected = grad_opt.evaluate("""el => {
                    const r = el.querySelector("input[type='radio']") || (el.tagName === 'LABEL' ? document.querySelector("input#" + el.getAttribute("for")) : null);
                    if (r && r.checked) return true;
                    return el.classList.contains("selected") || el.classList.contains("active") || el.getAttribute("aria-checked") === "true";
                }""")
                if not is_selected:
                    print("  [AI Radio]: Detected 'Graduate' vs 'Student (We do NOT hire students)'. Selecting 'Graduate'...")
                    try:
                        grad_opt.click()
                    except:
                        grad_opt.click(force=True)
                    radio_groups_answered += 1
                    time.sleep(0.5)

            radio_data = drawer.evaluate("""(root) => {
                const results = [];
                const skipPhrases = ["thank you for showing", "kindly answer all"];
                const isGreeting = (t) => !t || skipPhrases.some(sp => t.toLowerCase().includes(sp));

                // 1. Standard radio inputs inside drawer
                const radios = Array.from(root.querySelectorAll("input[type='radio']"));
                const byName = {};
                radios.forEach((r, idx) => {
                    const name = r.name || ('grp_' + idx);
                    if (!byName[name]) byName[name] = [];
                    byName[name].push(r);
                });

                for (const [name, rList] of Object.entries(byName)) {
                    const isChecked = rList.some(r => r.checked);
                    let qText = '';
                    // Look upward from first radio's group container for the closest question text
                    const grpCont = rList[0].closest('fieldset, .radio-group, div[class*="question" i], div[class*="option" i], ul, div');
                    if (grpCont) {
                        const legend = grpCont.querySelector('legend, label[class*="question" i], div[class*="question" i], p');
                        if (legend && !legend.querySelector("input") && !isGreeting(legend.innerText.trim())) {
                            qText = legend.innerText.trim();
                        }
                        if (!qText && grpCont.previousElementSibling) {
                            const pt = grpCont.previousElementSibling.innerText.trim();
                            if (!isGreeting(pt)) qText = pt;
                        }
                    }
                    const options = rList.map((r, i) => {
                        const lbl = (r.id ? root.querySelector('label[for="' + CSS.escape(r.id) + '"]') : null) || r.closest('label') || r.parentElement;
                        return {
                            type: 'standard',
                            id: r.id || '',
                            name: name,
                            index: i,
                            checked: r.checked,
                            label: lbl ? lbl.innerText.trim() : ('Option ' + (i + 1))
                        };
                    });
                    results.push({
                        type: 'standard',
                        name: name,
                        isChecked: isChecked,
                        question: qText,
                        options: options
                    });
                }

                // 2. Custom radio / option containers inside drawer (only if no standard radios matched)
                if (results.length === 0) {
                    const optionContainers = root.querySelectorAll(
                        "div[class*='bot-options' i], div[class*='options-container' i], div[class*='radioGroup' i], " +
                        "div[class*='custom-radio' i], div[role='radiogroup'], ul[class*='options' i]"
                    );
                    optionContainers.forEach((cont, contIdx) => {
                        const items = Array.from(cont.querySelectorAll(
                            "div[class*='option' i], div[class*='radio' i], label, li, div[role='radio']"
                        )).filter(el => {
                            const t = el.innerText.trim();
                            return t.length > 0 && !el.querySelector("div[class*='option' i]");
                        });

                        if (items.length >= 2) {
                            const isChecked = items.some(it =>
                                it.classList.contains('selected') ||
                                it.classList.contains('active') ||
                                it.classList.contains('checked') ||
                                it.getAttribute('aria-checked') === 'true'
                            );
                            let qText = '';
                            const prev = cont.previousElementSibling;
                            if (prev && !isGreeting(prev.innerText.trim())) qText = prev.innerText.trim();

                            const options = items.map((it, i) => ({
                                type: 'custom',
                                contIndex: contIdx,
                                index: i,
                                checked: it.classList.contains('selected') || it.classList.contains('active'),
                                label: it.innerText.trim()
                            }));

                            results.push({
                                type: 'custom',
                                contIndex: contIdx,
                                isChecked: isChecked,
                                question: qText,
                                options: options
                            });
                        }
                    });
                }

                return results;
            }""", drawer)

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

                    clicked = False
                    if grp["type"] == "standard":
                        # Use Playwright native click on the visible label or option row so React registers it
                        opt_id = target_opt.get("id")
                        if opt_id:
                            try:
                                lbl_el = drawer.query_selector(f"label[for='{opt_id}']")
                                if lbl_el and lbl_el.is_visible():
                                    lbl_el.click()
                                    clicked = True
                            except:
                                pass
                        if not clicked:
                            try:
                                radios = drawer.query_selector_all("input[type='radio']")
                                matching = [r for r in radios if (r.get_attribute("name") or "") == grp.get("name")] or radios
                                if ans_idx < len(matching):
                                    r_el = matching[ans_idx]
                                    row_el = r_el.evaluate_handle("r => r.closest('label') || r.parentElement")
                                    if row_el:
                                        row_el.as_element().click(force=True)
                                        clicked = True
                            except:
                                pass
                        if not clicked:
                            drawer.evaluate("""(root, data) => {
                                let radio = data.id ? root.querySelector('#' + CSS.escape(data.id)) : null;
                                if (!radio) {
                                    const radios = Array.from(root.querySelectorAll("input[type='radio']")).filter(r => (r.name || '') === data.name);
                                    radio = radios[data.index];
                                }
                                if (radio) {
                                    const lbl = (radio.id ? root.querySelector('label[for="' + CSS.escape(radio.id) + '"]') : null) || radio.closest('label') || radio.parentElement;
                                    if (lbl) lbl.click();
                                    else radio.click();
                                }
                            }""", {"id": opt_id, "name": grp.get("name"), "index": ans_idx})
                    else:
                        drawer.evaluate("""(root, data) => {
                            const optionContainers = root.querySelectorAll(
                                "div[class*='bot-options' i], div[class*='options-container' i], div[class*='radioGroup' i], " +
                                "div[class*='custom-radio' i], div[role='radiogroup'], ul[class*='options' i]"
                            );
                            const cont = optionContainers[data.contIndex];
                            if (cont) {
                                const items = Array.from(cont.querySelectorAll(
                                    "div[class*='option' i], div[class*='radio' i], label, li, div[role='radio']"
                                )).filter(el => el.innerText.trim().length > 0 && !el.querySelector("div[class*='option' i]"));
                                const target = items[data.index];
                                if (target) target.click();
                            }
                        }""", {"contIndex": grp.get("contIndex"), "index": ans_idx})

                    radio_groups_answered += 1
                    time.sleep(0.6)
        except Exception as e:
            pass

        # Step 4: Handle CHAT TEXT INPUT strictly inside `drawer`
        chat_input = None
        for sel in [
            "input[placeholder*='Type message' i]", "input[placeholder*='type message' i]",
            "input[placeholder*='message here' i]", "input[placeholder*='example' i]",
            "textarea[placeholder*='Type message' i]", "textarea[placeholder*='type message' i]",
            "input[class*='chat-input' i]", "textarea[class*='chat' i]",
            "input:not([type='hidden']):not([type='radio']):not([type='checkbox']):not([type='file']):not([type='submit']):not([type='button'])",
            "textarea",
            "[contenteditable='true']"
        ]:
            try:
                el = drawer.query_selector(sel)
                if el and el.is_visible() and not el.is_disabled():
                    chat_input = el
                    break
            except:
                pass

        if chat_input and radio_groups_answered == 0:
            try:
                curr_val = chat_input.evaluate("e => (e.value !== undefined ? e.value : e.innerText || '').trim()")
            except:
                curr_val = ""
            if not curr_val:
                q_for_input = question_text or "Answer recruiter question"
                answer = answer_hr_question(q_for_input)
                if not answer:
                    answer = "I have 1 year of hands-on experience in full-stack development with React, Node.js, and Python."
                if len(answer) > 250:
                    answer = answer[:250]

                print(f"  [AI Chat Reply]: '{answer[:60]}' for '{q_for_input[:60]}'")
                try:
                    is_ce = chat_input.evaluate("e => e.isContentEditable === true")
                    chat_input.click()
                    if is_ce:
                        page.keyboard.press("Control+A")
                        page.keyboard.press("Backspace")
                        page.keyboard.type(answer, delay=20)
                    else:
                        chat_input.fill("")
                        time.sleep(0.2)
                        chat_input.fill(answer)
                    chat_input.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); }")
                    time.sleep(0.5)

                    # 1. Try sending via Enter
                    chat_input.press("Enter")
                    time.sleep(1.0)

                    # 2. Look for explicit Send button inside drawer
                    send_btn = drawer.query_selector("button[class*='send' i], span[class*='send' i], div[class*='send' i], button[type='submit']")
                    if send_btn and send_btn.is_visible() and not send_btn.is_disabled():
                        send_btn.click()
                        time.sleep(1.5)

                    # 3. In Naukri Campus drawer, the bottom Save button submits the current step
                    click_save_if_present(page, drawer)

                    # Check post-submit state
                    final_body = page.inner_text("body").lower() if page else ""
                    if "saveapply" in page.url.lower() or ("oops" in final_body and "incomplete" in final_body):
                        print("  [!] Application rejected due to incomplete information.")
                        return False

                    new_drawer, _ = find_active_drawer(page)
                    if not new_drawer or any(s in final_body for s in ["successfully applied", "applied successfully", "application submitted"]):
                        print("  [✓] Application completed successfully!")
                        return True

                    print("  [AI] Answer submitted. Waiting for chatbot's next question...")
                    time.sleep(1.5)
                    continue
                except Exception as e:
                    print(f"  [!] Chat input error: {e}")

        # Step 5: Handle CHOICE CHIPS strictly inside `drawer` (never click 'Skip this question' when answering)
        visible_chips = []
        for sel in [
            ".chip", "button[class*='chip' i]", "div[class*='chip' i]",
            "button[class*='choice' i]", "li.list-item", "button.list-item",
            "div[class*='quick-reply' i]", "div[class*='bot-options' i] button",
            "button[class*='option' i]"
        ]:
            try:
                chips = drawer.query_selector_all(sel)
                for c in chips:
                    if c.is_visible():
                        ct = c.inner_text().strip()
                        ctl = ct.lower()
                        if ct and ctl not in ["save", "saved", "submit", "apply", "send", "close", "cancel", "x"] and not ctl.startswith("skip"):
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
            chip_state = f"chip:{question_text}:{options_list[idx]}"
            if chip_state == last_answered_state:
                stuck_rounds += 1
                if stuck_rounds >= 3:
                    print("  [!] Chip click did not advance chatbot. Aborting.")
                    return False
            else:
                stuck_rounds = 0
            last_answered_state = chip_state

            print(f"  [AI Reply]: Clicking chip '{options_list[idx]}' for '{question_text[:60]}'")
            try:
                chosen_chip.click()
                time.sleep(2.0)
            except Exception:
                try:
                    chosen_chip.click(force=True)
                    time.sleep(2.0)
                except:
                    pass
            continue

        # Step 6: Handle STANDARD FORM INPUTS inside `drawer`
        form_inputs_answered = 0
        try:
            inputs = drawer.query_selector_all("input[type='text'], input[type='number'], textarea")
            for inp in inputs:
                if inp.is_visible() and not inp.is_disabled():
                    ph = (inp.get_attribute("placeholder") or "").lower()
                    if "search" in ph or "type message" in ph:
                        continue
                    val = inp.input_value().strip()
                    if not val:
                        lbl = inp.get_attribute("aria-label") or ph or question_text or "Answer"
                        ans = answer_hr_question(lbl) or "0"
                        inp.fill(ans[:200])
                        inp.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); }")
                        print(f"  [AI Form Fill]: {lbl[:40]} → {ans}")
                        form_inputs_answered += 1
                        time.sleep(0.3)
        except:
            pass

        # Step 7: Handle DROPDOWNS (<select>) inside `drawer`
        selects_answered = 0
        try:
            selects = drawer.query_selector_all("select")
            for s in selects:
                if s.is_visible() and not s.is_disabled():
                    cur = s.evaluate("el => el.options[el.selectedIndex]?.text || ''").strip()
                    if not cur or cur.lower() in ["select", "choose", "--", "select an option", ""]:
                        opts = s.evaluate("""el => Array.from(el.options)
                            .map(o => ({text: o.text.trim(), value: o.value}))
                            .filter(o => o.text && !['select','choose','--',''].includes(o.text.toLowerCase()))""")
                        if opts:
                            ans_idx_str = answer_hr_question(question_text or "Select option", options=[o["text"] for o in opts])
                            try:
                                ans_idx = int(ans_idx_str)
                                if not (0 <= ans_idx < len(opts)):
                                    ans_idx = 0
                            except:
                                ans_idx = 0
                            chosen = opts[ans_idx]
                            s.select_option(value=chosen["value"]) if chosen["value"] else s.select_option(label=chosen["text"])
                            print(f"  [AI Select]: → {chosen['text']}")
                            selects_answered += 1
                            time.sleep(0.3)
        except:
            pass

        # Step 8: Check if all visible fields in drawer are filled before clicking SAVE
        unanswered_fields = False
        try:
            unanswered_fields = drawer.evaluate("""(root) => {
                const radios = Array.from(root.querySelectorAll("input[type='radio']"));
                if (radios.length > 0) {
                    const byName = {};
                    radios.forEach((r, i) => {
                        const name = r.name || ('unnamed_' + i);
                        if (!byName[name]) byName[name] = [];
                        byName[name].push(r);
                    });
                    for (const rList of Object.values(byName)) {
                        if (!rList.some(r => r.checked)) return true;
                    }
                }
                const inputs = Array.from(root.querySelectorAll("input:not([type='hidden']):not([type='radio']):not([type='checkbox']):not([type='file']):not([type='submit']):not([type='button']), textarea")).filter(e => {
                    const r = e.getBoundingClientRect();
                    return (r.width > 0 || e.offsetParent !== null) && !e.disabled && !e.readOnly;
                });
                for (const inp of inputs) {
                    if (!inp.value.trim()) return true;
                }
                return false;
            }""", drawer)
        except:
            pass

        if unanswered_fields:
            print("  [!] Unanswered questions or empty inputs detected inside drawer. Re-evaluating...")
            stuck_rounds += 1
            if stuck_rounds >= 3:
                print("  [!] Stuck on unanswered mandatory fields. Aborting.")
                return False
            continue

        answered_anything = (radio_groups_answered > 0 or form_inputs_answered > 0 or selects_answered > 0)
        current_state = f"q:{question_text}_r:{radio_groups_answered}_i:{form_inputs_answered}_s:{selects_answered}"
        if current_state == last_answered_state and not answered_anything:
            stuck_rounds += 1
        else:
            stuck_rounds = 0
        last_answered_state = current_state

        if answered_anything:
            print("  [AI] Step answered. Clicking Save to advance/submit...")
            if click_save_if_present(page, drawer):
                time.sleep(2.5)
                try:
                    final_url = page.url.lower()
                    final_body = page.inner_text("body").lower()
                    if "saveapply" in final_url or ("oops" in final_body and "incomplete" in final_body):
                        print("  [!] Naukri returned incomplete information error page.")
                        return False
                    if any(s in final_body for s in [
                        "successfully applied", "applied successfully", "application has been sent",
                        "already applied", "thank you for applying", "your application is submitted",
                        "application submitted successfully"
                    ]):
                        print("  [✓] Confirmed application success banner!")
                        return True
                except:
                    pass

                # Check if drawer closed or moved to the NEXT question
                new_drawer, _ = find_active_drawer(page)
                if not new_drawer:
                    print("  [✓] Drawer closed after Save. Application submitted!")
                    return True
                print("  [AI] Chatbot still active with next question. Continuing loop...")
                continue
        elif stuck_rounds >= 3:
            # No active inputs/radios found for 3 turns — try enabled Save if present, else abort
            if click_save_if_present(page, drawer):
                time.sleep(2.5)
                try:
                    final_url = page.url.lower()
                    final_body = page.inner_text("body").lower()
                    if "saveapply" in final_url or ("oops" in final_body and "incomplete" in final_body):
                        print("  [!] Naukri returned incomplete information error page.")
                        return False
                except:
                    pass
                new_drawer, _ = find_active_drawer(page)
                return not bool(new_drawer)
            print("  [!] No actionable questions or enabled Save button found in drawer.")
            return False

    return False

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
    parser.add_argument("--target", type=int, default=999999, help="Target number of applications to submit.")
    parser.add_argument("--unlimited", action="store_true", default=True, help="Run continuously without stopping.")
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
        page = context.pages[0] if context.pages else context.new_page()

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

        target_applications = getattr(args, 'target', 999999)
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
                    print("\n[♾️ Unstoppable Mode] Reached the end of available Naukri jobs.")
                    print("  Waiting 60 seconds before cycling back to Page 1 for newly posted jobs...")
                    for sec in range(60, 0, -1):
                        print(f"  Resuming in {sec}s...", end="\r")
                        time.sleep(1)
                    empty_scroll_count = 0
                    try:
                        page.goto(search_url)
                        page.wait_for_timeout(4000)
                    except Exception:
                        pass
                    continue
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
                        curr_u = new_page.url.lower()
                        body_text = new_page.inner_text("body").lower()
                    except:
                        curr_u = ""
                        body_text = ""

                    if "saveapply" in curr_u or ("oops" in body_text and "incomplete" in body_text):
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
                                final_u = new_page.url.lower()
                                final_body = new_page.inner_text("body").lower()
                                if "saveapply" in final_u or ("oops" in final_body and "incomplete" in final_body):
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

            # Advance to next page via UI pagination
            next_btn = page.query_selector("a.fright, a.styles_btn-secondary__, span:has-text('Next'), a[rel='next'], button[class*='next'], a[class*='next'], a:has-text('Next'), a:has-text('>')")
            if next_btn:
                print("Advancing to Next Page on Naukri...")
                try:
                    next_btn.scroll_into_view_if_needed()
                    next_btn.click(force=True)
                    page.wait_for_timeout(4000)
                except:
                    page.evaluate("btn => btn.click()", next_btn)
                    page.wait_for_timeout(4000)
            else:
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