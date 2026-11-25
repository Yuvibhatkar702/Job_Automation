import os
import json
import time
import sys
import random
import argparse
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
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
    """Select the best matching option in a <select> dropdown and trigger change event."""
    try:
        options = select_el.query_selector_all("option")
        target_lower = target_text.lower().strip()
        placeholder_terms = ["select", "select an option", "choose", "--", "", "month", "year", "day"]

        # First: exact match
        for opt in options:
            opt_text = opt.inner_text().strip()
            opt_val = opt.get_attribute("value") or ""
            if opt_text.lower() == target_lower:
                select_el.select_option(value=opt_val) if opt_val else select_el.select_option(label=opt_text)
                select_el.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))")
                return True

        # Second: substring match
        for opt in options:
            opt_text = opt.inner_text().strip()
            opt_val = opt.get_attribute("value") or ""
            if not opt_text or opt_text.lower() in placeholder_terms:
                continue
            if target_lower in opt_text.lower() or opt_text.lower() in target_lower:
                select_el.select_option(value=opt_val) if opt_val else select_el.select_option(label=opt_text)
                select_el.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))")
                return True
        
        # Third: first non-placeholder option as fallback
        for opt in options:
            opt_text = opt.inner_text().strip()
            opt_val = opt.get_attribute("value") or ""
            if opt_text and opt_text.lower() not in placeholder_terms:
                select_el.select_option(value=opt_val) if opt_val else select_el.select_option(label=opt_text)
                select_el.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))")
                return True
    except Exception as e:
        print(f"    [!] Dropdown selection error: {e}")
    return False

def _fill_select_dropdown(sel, label="", profile_data=None):
    """Fills a <select> element intelligently handling placeholders, dates, ratings, and profile fields."""
    try:
        curr = sel.evaluate("el => el.options[el.selectedIndex]?.text || ''").strip()
        opts = [opt.inner_text().strip() for opt in sel.query_selector_all("option")]
        
        placeholder_terms = [
            "select", "select an option", "choose", "--", "", 
            "month", "year", "day", "select month", "select year", "please select"
        ]
        if curr and curr.lower() not in placeholder_terms:
            return True  # Already filled with a valid choice

        if not opts:
            return False

        label_lower = (label or _get_field_label(sel)).lower()
        
        # 1. Month dropdown (Work Experience / Education start/end dates)
        if "month" in label_lower or any(m in [o.lower() for o in opts] for m in ["january", "february", "june"]):
            target_month = "January"
            for o in opts:
                if o.lower() in ["january", "june", "august"]:
                    target_month = o
                    break
            _select_dropdown_best_match(sel, target_month)
            print(f"    [Date Select] {label_lower[:30]} → {target_month}")
            return True

        # 2. Year dropdown (Work Experience / Education start/end dates)
        if "year" in label_lower or any(y in opts for y in ["2023", "2024", "2025", "2026"]):
            target_year = "2024"
            for y_opt in ["2024", "2025", "2023", "2026"]:
                if any(y_opt == o.strip() for o in opts):
                    target_year = y_opt
                    break
            _select_dropdown_best_match(sel, target_year)
            print(f"    [Date Select] {label_lower[:30]} → {target_year}")
            return True

        # 3. Proficiency / Skill level
        if any(k in label_lower for k in ["proficiency", "skill level", "competency"]):
            for pref in ["Professional", "Proficient", "Advanced", "Intermediate", "Expert"]:
                if _select_dropdown_best_match(sel, pref):
                    print(f"    [Proficiency Select] {label_lower[:30]} → {pref}")
                    return True

        # 4. Known profile field
        if _is_profile_field(label_lower):
            val = _get_profile_value_for_field(label_lower, profile_data or {})
            if val and _select_dropdown_best_match(sel, val):
                print(f"    [Profile Select] {label_lower[:30]} → {val}")
                return True

        # 5. General screening question with options
        valid_opts = [o for o in opts if o.lower() not in placeholder_terms]
        if valid_opts:
            ans_idx = answer_hr_question(label_lower, valid_opts)
            idx = int(ans_idx) if ans_idx.isdigit() and int(ans_idx) < len(valid_opts) else 0
            chosen = valid_opts[idx]
            _select_dropdown_best_match(sel, chosen)
            print(f"    [AI Select] {label_lower[:30]} → {chosen}")
            return True
            
    except Exception as e:
        print(f"    [!] Error filling select dropdown: {e}")
    return False

def determine_field_answer(label, context_text="", inp_type="text", profile_data=None):
    """Deterministically resolves the correct answer for text/number/textarea fields.
    Guarantees that numbers and ratings never receive 'Yes' or text."""
    txt = f"{label} {context_text}".lower()
    
    # 1. City / Location
    if any(k in txt for k in ["city", "location", "town"]):
        return "Pune"
    if "state" in txt:
        return "Maharashtra"
    if "country" in txt:
        return "India"
    if any(k in txt for k in ["postal", "zip", "pin code", "pincode"]):
        return "411001"
    if "address" in txt:
        return "Pune, Maharashtra, India"

    # 2. Days / Notice period / Availability
    if any(k in txt for k in ["(days)", "in days", "how soon", "np in days", "official np", "serving notice in days"]):
        return "0"
    if any(k in txt for k in ["lwd", "last working day"]):
        return "0" if inp_type == "number" else "Immediate"
    if any(k in txt for k in ["notice", "availability", "join"]):
        return "0"

    # 3. Ratings & Scales
    if any(k in txt for k in ["out of 5", "/5", "scale of 1 to 5", "rating out of 5", "rate your", "rate yourself"]):
        if "english" in txt or "communication" in txt:
            return "5"
        return "4"
    if any(k in txt for k in ["out of 10", "/10", "scale of 1 to 10"]):
        return "8"
    if any(k in txt for k in ["rating", "rate"]):
        return "4"

    # 4. Years / Experience
    if any(k in txt for k in ["how many years", "years of", "total experience", "relevant experience", "experience in years"]):
        return "0"
    if any(k in txt for k in ["experience", "years", "year", "exp"]) and inp_type == "number":
        return "0"

    # 5. CTC / Salary
    if any(k in txt for k in ["current ctc", "current salary", "present ctc"]):
        return "0"
    if any(k in txt for k in ["expected ctc", "expected salary", "desired salary", "package"]):
        return "350000"

    # 6. Graduation / Degree / Profile
    if any(k in txt for k in ["passing", "year of grad", "graduation year", "batch"]):
        return "2026"
    if any(k in txt for k in ["gpa", "cgpa", "percentage", "marks"]):
        return "8.5"
    if any(k in txt for k in ["degree", "qualification"]):
        return "B.Tech Information Technology"
    if any(k in txt for k in ["university", "college", "institute", "school"]):
        return "Savitribai Phule Pune University"
    if any(k in txt for k in ["company", "employer"]):
        return "Tech Solutions"
    if any(k in txt for k in ["job title", "title"]) and "mr" not in txt and "ms" not in txt:
        return "Software Developer"

    # 7. Known profile contact fields
    if profile_data and _is_profile_field(label):
        val = _get_profile_value_for_field(label, profile_data)
        if val:
            return val

    # 8. AI Engine consultation
    ai_ans = answer_hr_question(context_text or label)

    # 9. Strict Numeric Sanitization
    if inp_type == "number" or any(num_kw in txt for num_kw in ["(days)", "in days", "how many", "number of", "rate", "rating", "years", "score"]):
        digits = "".join([c for c in ai_ans if c.isdigit()])
        if digits:
            return digits
        if any(k in txt for k in ["days", "notice", "experience", "years"]):
            return "0"
        if any(k in txt for k in ["5", "rate", "rating"]):
            return "4"
        if any(k in txt for k in ["10"]):
            return "8"
        return "0"

    # If AI returned Yes/No on a non-boolean field
    if ai_ans.lower() in ["yes", "no"]:
        if any(k in txt for k in ["days", "notice"]):
            return "0"
        if any(k in txt for k in ["city", "location"]):
            return "Pune"
        if any(k in txt for k in ["salary", "ctc"]):
            return "350000"
            
    return ai_ans or "Yes"

def find_easy_apply_modal(page):
    """Finds the open LinkedIn Easy Apply modal dialog across modern <dialog> and Artdeco variations."""
    selectors = [
        "div[data-test-modal-id='easy-apply-modal']",
        "div.jobs-easy-apply-modal",
        "div.jobs-easy-apply-content",
        "div[role='dialog'][aria-labelledby*='easy-apply']",
        "dialog[open]",
        "div.artdeco-modal[role='dialog']",
        "#artdeco-modal-outlet div.artdeco-modal",
        "div.artdeco-modal",
        "[role='dialog']"
    ]
    for sel in selectors:
        try:
            modals = page.query_selector_all(sel)
            for m in modals:
                if m and m.is_visible():
                    is_msg = page.evaluate("el => el.closest('.msg-overlay-container, .msg-overlay-list-bubble, #msg-overlay') !== null", m)
                    if not is_msg:
                        has_apply_controls = page.evaluate("""el => {
                            return Boolean(
                                el.querySelector('.jobs-easy-apply-content') ||
                                el.querySelector('button[aria-label*=\"Easy Apply\"]') ||
                                el.querySelector('button[aria-label*=\"Submit\"]') ||
                                el.querySelector('button[aria-label*=\"Next\"]') ||
                                el.querySelector('button[aria-label*=\"Review\"]') ||
                                el.querySelector('button[aria-label*=\"Dismiss\"]') ||
                                el.querySelector('[data-test-modal-close-btn]') ||
                                el.querySelector('h3, h2, h1')
                            );
                        }""", m)
                        if has_apply_controls:
                            return m
        except:
            pass
    return None

def solve_linkedin_easy_apply(page, profile):
    print("  [AI] Initiating LinkedIn Easy Apply Solver...")
    from profile_manager import load_profile_data
    profile_data = load_profile_data()

    for step in range(12):  # Max 12 steps in modal
        time.sleep(1.5)
        
        modal = find_easy_apply_modal(page)
        if not modal:
            # Give it 2 seconds to appear in case of slow animation
            time.sleep(2)
            modal = find_easy_apply_modal(page)

        if not modal:
            # Check if successful (modal closed and success banner present)
            success_msg = page.query_selector(
                "h3:has-text('Application sent'), "
                "div:has-text('Application submitted'), "
                "span:has-text('Your application was sent'), "
                "div:has-text('Your application was sent'), "
                ".artdeco-inline-feedback--success, "
                "span:has-text('applied')"
            )
            return bool(success_msg)
            
        # ── Step 0: Ensure Resume Selection (if on resume step) ────────────
        try:
            resume_radios = modal.query_selector_all("input[type='radio']")
            if resume_radios and not any(r.is_checked() for r in resume_radios):
                modal_text = modal.inner_text().lower()
                if "resume" in modal_text:
                    resume_radios[0].check(force=True)
                    print("    [Resume] Selected primary uploaded resume.")
        except:
            pass
            
        # ── Step 1: Radio Buttons (Screening Questions & Groups) ───────────
        try:
            all_radios = modal.query_selector_all("input[type='radio']")
            radio_groups = {}
            for r in all_radios:
                r_name = r.get_attribute("name") or "default_group"
                if r_name not in radio_groups:
                    radio_groups[r_name] = []
                radio_groups[r_name].append(r)

            for group_name, radios in radio_groups.items():
                try:
                    if any(r.is_checked() for r in radios):
                        continue

                    first_r = radios[0]
                    q_text = page.evaluate("""(r) => {
                        let el = r.parentElement;
                        while (el && el.tagName !== 'DIALOG' && !el.classList.contains('artdeco-modal')) {
                            const lines = (el.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
                            for (const line of lines) {
                                if (line.includes('?') || line.includes('*') || line.toLowerCase().includes('experience') || line.toLowerCase().includes('comfortable') || line.toLowerCase().includes('proficient') || line.toLowerCase().includes('setting') || line.toLowerCase().includes('onsite') || line.toLowerCase().includes('remote')) {
                                    return line;
                                }
                            }
                            el = el.parentElement;
                        }
                        return '';
                    }""", first_r)

                    option_labels = []
                    for r in radios:
                        lbl_text = page.evaluate("""(r) => {
                            const lbl = document.querySelector(`label[for='${r.id}']`) || r.closest('label');
                            if (lbl) return lbl.innerText.trim();
                            const p = r.parentElement;
                            return p ? p.innerText.trim() : (r.value || '');
                        }""", r)
                        option_labels.append(lbl_text)

                    ans_idx = 0
                    if q_text:
                        ans_idx_str = answer_hr_question(q_text, option_labels)
                        if ans_idx_str.isdigit() and int(ans_idx_str) < len(radios):
                            ans_idx = int(ans_idx_str)
                    else:
                        for i, opt in enumerate(option_labels):
                            if "yes" in opt.lower():
                                ans_idx = i
                                break

                    chosen_radio = radios[ans_idx]
                    chosen_radio.scroll_into_view_if_needed()
                    try:
                        r_id = chosen_radio.get_attribute("id")
                        label_el = modal.query_selector(f"label[for='{r_id}']") if r_id else None
                        if label_el and label_el.is_visible():
                            label_el.click(force=True)
                        else:
                            chosen_radio.click(force=True)
                    except:
                        pass

                    chosen_radio.evaluate("""(r) => {
                        const lbl = document.querySelector(`label[for='${r.id}']`) || r.closest('label');
                        if (lbl) lbl.click();
                        r.checked = true;
                        r.dispatchEvent(new Event('input', { bubbles: true }));
                        r.dispatchEvent(new Event('change', { bubbles: true }));
                    }""")
                    
                    disp_label = option_labels[ans_idx] if ans_idx < len(option_labels) else 'Selected'
                    print(f"    [AI Radio] {q_text[:40] if q_text else 'Question'} → {disp_label}")
                except Exception as e:
                    pass
        except Exception as e:
            pass

        # ── Step 2: Dropdowns (<select>) ────────────────────────────────────
        try:
            selects = modal.query_selector_all("select")
            for sel in selects:
                _fill_select_dropdown(sel, _get_field_label(sel), profile_data)
        except Exception as e:
            pass

        # ── Step 3: Text & Number Inputs, Textareas ────────────────────────
        try:
            inputs = modal.query_selector_all("input:not([type='hidden']):not([type='file']):not([type='radio']):not([type='checkbox']), textarea")
            for inp in inputs:
                try:
                    val = inp.input_value().strip()
                    label = _get_field_label(inp)
                    inp_type = inp.get_attribute("type") or "text"
                    
                    # Detect if currently holding invalid value like 'Yes' on numeric/date/location field
                    is_invalid = False
                    if inp_type == "number" and not val.isdigit():
                        is_invalid = True
                    if val.lower() in ["yes", "no"] and any(k in label for k in ["(days)", "in days", "city", "location", "rate", "out of 5", "years", "experience", "ctc", "salary"]):
                        is_invalid = True

                    if val and not is_invalid:
                        continue

                    # Special handling for City / Location with typeahead support
                    if "city" in label or "location" in label:
                        city_val = _get_profile_value_for_field(label, profile_data) or "Pune"
                        try:
                            inp.click()
                            inp.fill("")
                            inp.type(city_val, delay=80)
                            time.sleep(1.0)
                            # First try selecting from dropdown portal
                            opt = page.query_selector("div[role='listbox'] div[role='option'], .basic-typeahead__selectable-list li, .typeahead-results li, div[class*='typeahead'] li, li[role='option']")
                            if opt and opt.is_visible():
                                opt.click(force=True)
                                time.sleep(0.3)
                            else:
                                inp.press("ArrowDown")
                                time.sleep(0.3)
                                inp.press("Enter")
                        except:
                            inp.fill(city_val)
                        print(f"    [Profile Fill] {label[:40]} → {city_val}")
                        continue

                    parent = inp.evaluate_handle("el => el.closest('.jobs-easy-apply-form-section__grouping, fieldset, .fb-dash-form-element, .pb4, div.mt2, div')")
                    context_text = parent.inner_text().strip() if parent else label
                    
                    ans_to_fill = determine_field_answer(label, context_text, inp_type=inp_type, profile_data=profile_data)
                    
                    inp.fill(ans_to_fill)
                    inp.evaluate("""(el, v) => {
                        el.value = v;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }""", ans_to_fill)
                    print(f"    [AI Fill] {label[:40]} → {ans_to_fill}")
                except:
                    pass
        except Exception as e:
            pass

        # ── Step 4: Consent / Work Experience Checkboxes ───────────────────
        try:
            # Check "I currently work here" if present to avoid requiring End Date dropdowns
            curr_work_cb = modal.query_selector(
                "input[type='checkbox'][id*='currently-work'], "
                "input[type='checkbox'][name*='currently-work'], "
                "input[type='checkbox'][id*='current-role']"
            )
            if not curr_work_cb:
                for cb in modal.query_selector_all("input[type='checkbox']"):
                    lbl_txt = _get_field_label(cb)
                    if any(x in lbl_txt for x in ["currently work", "current role", "currently in this role"]):
                        curr_work_cb = cb
                        break
            if curr_work_cb and not curr_work_cb.is_checked():
                curr_work_cb.check(force=True)
                print("    [Work Experience] Checked 'I currently work here'.")

            checkboxes = modal.query_selector_all("input[type='checkbox']")
            for cb in checkboxes:
                try:
                    cb_id = (cb.get_attribute("id") or "").lower()
                    if "follow" in cb_id:
                        if cb.is_checked():
                            cb.uncheck()
                        continue
                    if not cb.is_checked():
                        cb.check(force=True)
                except:
                    pass
        except Exception as e:
            pass

        # ── Step 5: Click Submit or Next/Review ─────────────────────────────
        submit_btn = modal.query_selector(
            "button[aria-label*='Submit'], "
            "button:has-text('Submit application'), "
            "button span:has-text('Submit application'), "
            "button:has-text('Submit'), "
            "button span:has-text('Submit'), "
            "footer button.artdeco-button--primary:has-text('Submit')"
        )
        if submit_btn and submit_btn.is_visible():
            print("  [AI] Submitting application...")
            try:
                follow_box = modal.query_selector("input#follow-company-checkbox, input[name*='follow']")
                if follow_box and follow_box.is_checked():
                    follow_box.uncheck()
            except:
                pass
            submit_btn.click(force=True)
            time.sleep(3)
            # Dismiss post-submission confirmation
            for _ in range(3):
                done_btn = page.query_selector("button[aria-label='Dismiss'], button:has-text('Done'), .artdeco-modal__dismiss")
                if done_btn and done_btn.is_visible():
                    done_btn.click(force=True)
                    time.sleep(1)
                    break
                time.sleep(1)
            return True

        next_btn = modal.query_selector(
            "button[aria-label*='Continue to next step'], "
            "button[aria-label*='Review your application'], "
            "button[aria-label*='Next'], "
            "button[aria-label*='Review'], "
            "button span:has-text('Next'), "
            "button span:has-text('Review'), "
            "button:has-text('Next'), "
            "button:has-text('Review'), "
            "footer button.artdeco-button--primary"
        )
        if next_btn and next_btn.is_visible():
            next_btn.click(force=True)
            time.sleep(2)
            
            # Check for validation errors and resolve automatically
            err = modal.query_selector(
                ".artdeco-inline-feedback--error, .fb-dash-form-element__error-field, "
                "div[class*='error'], p:has-text('This field is required'), "
                "span:has-text('This field is required'), p:has-text('Invalid input'), "
                "span:has-text('Invalid input')"
            )
            if err and err.is_visible():
                err_text = err.inner_text().strip()
                print(f"  [!] Validation error detected: {err_text}. Applying auto-resolutions...")
                
                # 1. Resolve Work Experience 'I currently work here' checkbox if unselected
                try:
                    curr_cb = modal.query_selector("input[type='checkbox'][id*='currently-work'], input[type='checkbox'][name*='currently-work']")
                    if curr_cb and not curr_cb.is_checked():
                        curr_cb.check(force=True)
                        print("    [Auto-Resolve] Checked 'I currently work here'.")
                except:
                    pass

                # 2. Resolve all dropdowns (<select>)
                try:
                    for sel in modal.query_selector_all("select"):
                        _fill_select_dropdown(sel, _get_field_label(sel), profile_data)
                except:
                    pass

                # 3. Resolve any remaining unchecked radio buttons (prefer Yes)
                rem_radios = modal.query_selector_all("input[type='radio']")
                rem_groups = {}
                for r in rem_radios:
                    name = r.get_attribute("name") or "rem_grp"
                    if name not in rem_groups:
                        rem_groups[name] = []
                    rem_groups[name].append(r)
                for name, grp in rem_groups.items():
                    if not any(r.is_checked() for r in grp):
                        yes_r = None
                        for r in grp:
                            lbl = page.evaluate("el => (document.querySelector(`label[for='${el.id}']`) || el.closest('label') || el.parentElement || {}).innerText || ''", r).lower()
                            if "yes" in lbl:
                                yes_r = r
                                break
                        target = yes_r or grp[0]
                        target.evaluate("""(r) => {
                            const lbl = document.querySelector(`label[for='${r.id}']`) || r.closest('label');
                            if (lbl) lbl.click();
                            r.checked = true;
                            r.dispatchEvent(new Event('input', { bubbles: true }));
                            r.dispatchEvent(new Event('change', { bubbles: true }));
                        }""")
                        print(f"    [Auto-Resolve Radio] Checked affirmative option.")
                
                # 4. Resolve empty or invalid text/number fields
                empty_inputs = modal.query_selector_all("input:not([type='hidden']):not([type='file']):not([type='radio']):not([type='checkbox']), textarea")
                for inp in empty_inputs:
                    try:
                        val = inp.input_value().strip()
                        lbl = _get_field_label(inp)
                        inp_type = inp.get_attribute("type") or "text"
                        is_invalid = False
                        if inp_type == "number" and not val.isdigit():
                            is_invalid = True
                        if val.lower() in ["yes", "no"] and any(x in lbl for x in ["(days)", "in days", "city", "location", "rate", "out of 5", "years", "experience", "ctc", "salary"]):
                            is_invalid = True

                        if not val or is_invalid:
                            if "city" in lbl or "location" in lbl:
                                city_val = _get_profile_value_for_field(lbl, profile_data) or "Pune"
                                try:
                                    inp.click()
                                    inp.fill("")
                                    inp.type(city_val, delay=80)
                                    time.sleep(1.0)
                                    opt = page.query_selector("div[role='listbox'] div[role='option'], .basic-typeahead__selectable-list li, .typeahead-results li, div[class*='typeahead'] li, li[role='option']")
                                    if opt and opt.is_visible():
                                        opt.click(force=True)
                                        time.sleep(0.3)
                                    else:
                                        inp.press("ArrowDown")
                                        time.sleep(0.2)
                                        inp.press("Enter")
                                except:
                                    inp.fill(city_val)
                                print(f"    [Auto-Resolve City] {lbl[:30]} → {city_val}")
                                continue

                            parent = inp.evaluate_handle("el => el.closest('.jobs-easy-apply-form-section__grouping, fieldset, .fb-dash-form-element, .pb4, div.mt2, div')")
                            context_text = parent.inner_text().strip() if parent else lbl
                            corr_val = determine_field_answer(lbl, context_text, inp_type=inp_type, profile_data=profile_data)
                            inp.fill(corr_val)
                            inp.evaluate("""(el, v) => {
                                el.value = v;
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                            }""", corr_val)
                            print(f"    [Auto-Resolve Fill] {lbl[:30]} → {corr_val}")
                    except:
                        pass
                
                time.sleep(1)
                try:
                    next_btn.click(force=True)
                    time.sleep(2)
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

applied_urls = set()
for job in applied_jobs:
    if job.get("url"):
        applied_urls.add(job["url"])
    if job.get("id"):
        applied_urls.add(job["id"])

def run_linkedin():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Run without actually clicking submit.")
    parser.add_argument("--target", type=int, default=999999, help="Target number of applications to submit.")
    parser.add_argument("--unlimited", action="store_true", default=True, help="Run continuously without stopping.")
    args = parser.parse_args()

    while True:
        try:
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
                
                # Step 1: Wait for user to set filters manually
                print("\n=======================================================")
                print("1. Please apply any filters you want (Location, Experience, etc).")
                print("2. Wait for the page to load your filtered jobs.")
                print("3. Press ENTER in this terminal when you are ready!")
                print("=======================================================\n")
                
                # Navigate to the base search URL with Easy Apply and Fresher filters
                base_search_url = "https://www.linkedin.com/jobs/search/?keywords=software%20developer&f_AL=true&f_E=1%2C2&sortBy=DD"
                page.goto(base_search_url)
                
                print("\n>>> You have 60 seconds to log in and set your filters in the browser window! <<<")
                for i in range(60, 0, -1):
                    print(f"Waiting... {i} seconds remaining.", end="\r")
                    time.sleep(1)
                print("\n\nTime's up! Proceeding with the search results currently on screen...\n")
                
                search_url = page.url
                # If user navigated or kept page, preserve &f_AL=true so Easy Apply is active
                if "f_AL=true" not in search_url and ("jobs/search" in search_url or "jobs/search-results" in search_url):
                    sep = "&" if "?" in search_url else "?"
                    search_url = f"{search_url}{sep}f_AL=true"
                    print(f"[+] Re-enforcing Easy Apply filter: {search_url}")
                    page.goto(search_url)
                    page.wait_for_timeout(3000)
                    
                print(f"\n[+] Starting automated application loop on: {search_url}")
                
                target_applications = getattr(args, 'target', 999999)
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
                
                empty_page_count = 0
                visited_urls = set()

                # Determine starting page from current browser URL
                parsed_init = urlparse(page.url)
                qs_init = parse_qs(parsed_init.query)
                initial_start = int(qs_init.get('start', [0])[0]) if qs_init.get('start') else 0
                current_page = (initial_start // 25) + 1
                
                while applications_done < target_applications:
                    print(f"\n=======================================================")
                    print(f"📄 SCANNING PAGE {current_page} ({applications_done}/{target_applications} applied)")
                    print(f"=======================================================")
                    
                    # Hide LinkedIn messaging overlay to avoid click interception
                    try:
                        page.evaluate("""() => {
                            const msg = document.querySelector('.msg-overlay-container, #msg-overlay, .msg-overlay-bubble-header');
                            if (msg) msg.style.display = 'none';
                        }""")
                    except:
                        pass

                    # Step 1: Scroll left list container progressively to load all 25 jobs on current page
                    print("  Loading all job cards on current page...")
                    for _ in range(4):
                        try:
                            page.evaluate("""() => {
                                const list = document.querySelector('.jobs-search-results-list, .jobs-search-results-display, .scaffold-layout__list, main');
                                if (list) list.scrollTop += 1200;
                            }""")
                        except:
                            pass
                        page.wait_for_timeout(1000)

                    # Scroll back to the top so cards are evaluated in clean sequence
                    try:
                        page.evaluate("""() => {
                            const list = document.querySelector('.jobs-search-results-list, .jobs-search-results-display, .scaffold-layout__list, main');
                            if (list) list.scrollTop = 0;
                        }""")
                    except:
                        pass
                    page.wait_for_timeout(1000)
                    
                    # Step 2: Query job cards
                    dom_cards = page.query_selector_all(
                        "li.scaffold-layout__list-item, "
                        "li.jobs-search-results__list-item, "
                        "div[data-job-id], "
                        "div.job-card-container, "
                        "div.jobs-search-results-list__list-item"
                    )
                    
                    job_cards = []
                    seen_card_ids = set()
                    
                    if dom_cards:
                        for c in dom_cards:
                            try:
                                c_id = c.get_attribute("data-job-id") or c.get_attribute("data-occurs-id") or ""
                                link_el = c.query_selector("a[href*='/jobs/view/'], a.job-card-container__link, a.job-card-list__title")
                                href = link_el.get_attribute("href") if link_el else ""
                                if not c_id and href:
                                    import re
                                    m = re.search(r'/jobs/view/(\d+)', href) or re.search(r'currentJobId=(\d+)', href)
                                    if m:
                                        c_id = m.group(1)
                                
                                title_el = c.query_selector("a.job-card-list__title, a.job-card-container__link, strong, .artdeco-entity-lockup__title, span[aria-hidden='true']")
                                title = title_el.inner_text().strip() if title_el else ""
                                
                                dedup_key = c_id if c_id else (href.split('?')[0] if href else title)
                                if dedup_key and dedup_key in seen_card_ids:
                                    continue
                                if dedup_key:
                                    seen_card_ids.add(dedup_key)
                                    
                                job_cards.append({
                                    "card": c,
                                    "card_id": c_id,
                                    "href": href,
                                    "title": title
                                })
                            except Exception:
                                continue

                    # Fallback if no container cards matched
                    if not job_cards:
                        link_cards = page.query_selector_all("a.job-card-container__link, a.job-card-list__title, a[href*='/jobs/view/']")
                        for lc in link_cards:
                            try:
                                href = lc.get_attribute("href") or ""
                                title = lc.inner_text().strip()
                                import re
                                m = re.search(r'/jobs/view/(\d+)', href) or re.search(r'currentJobId=(\d+)', href)
                                c_id = m.group(1) if m else ""
                                dedup_key = c_id if c_id else href.split('?')[0]
                                if dedup_key and dedup_key in seen_card_ids:
                                    continue
                                if dedup_key:
                                    seen_card_ids.add(dedup_key)
                                job_cards.append({
                                    "card": lc,
                                    "card_id": c_id,
                                    "href": href,
                                    "title": title
                                })
                            except Exception:
                                pass

                    print(f"  Found {len(job_cards)} job cards on Page {current_page}.")

                    if not job_cards:
                        empty_page_count += 1
                        print(f"  [!] No job cards detected on Page {current_page} (Attempt {empty_page_count}/3).")
                        if empty_page_count >= 3:
                            print("\n[♾️ Unstoppable Mode] Reached the end of available job listings.")
                            print("  Waiting 60 seconds before cycling back to Page 1 for newly posted jobs...")
                            for sec in range(60, 0, -1):
                                print(f"  Resuming in {sec}s...", end="\r")
                                time.sleep(1)
                            print("\n  Refreshing job list from Page 1...")
                            empty_page_count = 0
                            current_page = 1
                            try:
                                parsed = urlparse(search_url)
                                qs = parse_qs(parsed.query)
                                qs['start'] = ['0']
                                if 'currentJobId' in qs:
                                    del qs['currentJobId']
                                new_query = urlencode(qs, doseq=True)
                                reset_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
                                page.goto(reset_url, wait_until="domcontentloaded")
                                page.wait_for_timeout(4000)
                            except Exception:
                                pass
                            continue
                        else:
                            next_page_num = current_page + 1
                            expected_start = (next_page_num - 1) * 25
                            print(f"  Advancing to Page {next_page_num} to look for more jobs...")
                            try:
                                parsed = urlparse(page.url)
                                qs = parse_qs(parsed.query)
                                qs['start'] = [str(expected_start)]
                                new_query = urlencode(qs, doseq=True)
                                next_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
                                page.goto(next_url, wait_until="domcontentloaded")
                                page.wait_for_timeout(3500)
                            except Exception:
                                pass
                            current_page = next_page_num
                            continue
                    else:
                        empty_page_count = 0

                    # Step 3: Process cards on current page
                    for idx_card, item in enumerate(job_cards):
                        if applications_done >= target_applications:
                            break
                            
                        try:
                            card = item["card"]
                            card_id = item["card_id"]
                            href = item["href"]
                            job_title = item["title"]
                            
                            clean_url = href.split("?")[0] if href else (f"https://www.linkedin.com/jobs/view/{card_id}" if card_id.isdigit() else card_id)
                            if clean_url and not clean_url.startswith("http"):
                                clean_url = f"https://www.linkedin.com{clean_url}"

                            # Skip if already visited or applied
                            if card_id and (card_id in applied_urls or card_id in visited_urls):
                                continue
                            if clean_url and (clean_url in applied_urls or clean_url in visited_urls):
                                continue
                            if job_title and (job_title in applied_urls or job_title in visited_urls):
                                continue

                            # Anti-keyword check on card title
                            if job_title and any(anti in job_title.lower() for anti in anti_keywords):
                                print(f"  [Skipped] Non-fresher/Senior role: '{job_title}'")
                                if card_id: visited_urls.add(card_id)
                                continue

                            if card_id: visited_urls.add(card_id)
                            if clean_url: visited_urls.add(clean_url)
                            if job_title: visited_urls.add(job_title)

                            # Click card to open detail pane
                            try:
                                card.scroll_into_view_if_needed()
                                clickable = card.query_selector("a.job-card-list__title, a.job-card-container__link, strong") or card
                                clickable.click(force=True)
                            except Exception:
                                try:
                                    page.evaluate("el => el.click()", card)
                                except Exception:
                                    pass
                                    
                            human_delay(2.0, 3.0)

                            # Extract detail pane title
                            title_el = page.query_selector(".jobs-unified-top-card__job-title, .job-details-jobs-unified-top-card__job-title, h1.t-24, h1")
                            if title_el:
                                d_title = title_el.inner_text().strip()
                                if d_title:
                                    job_title = d_title
                            if not job_title:
                                job_title = "Software Developer"
                                
                            print(f"\n[Job]: {job_title}")
                            
                            # Check anti-keywords on full job title
                            if any(anti in job_title.lower() for anti in anti_keywords):
                                print(f"  [Skipped] Non-fresher/Senior role: '{job_title}'")
                                continue

                            # Check if detail pane shows already applied
                            applied_badge = page.query_selector(".jobs-s-apply__application-badge, .artdeco-inline-feedback--success, span:has-text('Applied')")
                            if applied_badge and applied_badge.is_visible():
                                print(f"  Already applied to {job_title}. Skipping.")
                                if card_id: applied_urls.add(card_id)
                                continue

                            # Search for Easy Apply button
                            apply_btn = None
                            selectors = [
                                "button[aria-label='Easy Apply to this job']",
                                "button.jobs-apply-button",
                                "div.jobs-apply-button--top-card button",
                                ".jobs-s-apply button",
                                "button:not(.artdeco-pill):not([id*='searchFilter']):has-text('Easy Apply')",
                                "button[aria-label*='Easy Apply']:not(.artdeco-pill):not([id*='searchFilter'])"
                            ]
                            
                            for _ in range(6):
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
                                print(f"  [Skipped] No active 'Easy Apply' button found for '{job_title}' (external or already applied).")
                                continue
                                
                            btn_text = apply_btn.inner_text().strip()
                            
                            if "Applied" in btn_text:
                                print(f"  Already applied ('{btn_text}'). Skipping.")
                                if card_id: applied_urls.add(card_id)
                                continue
                            
                            print(f"  Found Apply button: '{btn_text}'. Clicking...")
                            
                            pages_before = len(context.pages)
                            try:
                                apply_btn.scroll_into_view_if_needed()
                                apply_btn.click(force=True)
                            except:
                                page.evaluate("el => el.click()", apply_btn)
                                
                            human_delay(2.0, 3.0)
                            
                            # Check if external site opened in new tab
                            if len(context.pages) > pages_before:
                                print("  [Skipped] External company site redirect detected (new tab). Skipping as requested.")
                                ext_page = context.pages[-1]
                                if not ext_page.is_closed():
                                    ext_page.close()
                                continue
                            
                            # Check if the current URL left LinkedIn
                            current_url = page.url.lower()
                            if "linkedin.com" not in current_url:
                                print(f"  [Skipped] Navigated away from LinkedIn ({current_url}). Going back...")
                                page.go_back()
                                time.sleep(2)
                                continue
                                
                            # Check if Easy Apply modal opened
                            modal = find_easy_apply_modal(page)
                            if not modal:
                                try:
                                    page.evaluate("el => el.click()", apply_btn)
                                except:
                                    pass
                                time.sleep(2)
                                modal = find_easy_apply_modal(page)
                            
                            if modal:
                                success = solve_linkedin_easy_apply(page, MCANDIDATE_PROFILE)
                                if success:
                                    print("  ✅ Success! Applied to job via LinkedIn Apply.")
                                    applied_jobs.append({
                                        "id": card_id,
                                        "url": clean_url,
                                        "title": job_title,
                                        "status": "Applied via AI",
                                        "applied_at": time.strftime("%Y-%m-%d %H:%M:%S")
                                    })
                                    if card_id: applied_urls.add(card_id)
                                    if clean_url: applied_urls.add(clean_url)
                                    applied_urls.add(job_title)
                                    save_json(APPLIED_JOBS_FILE, applied_jobs)
                                    applications_done += 1
                                else:
                                    print("  LinkedIn Apply was not completed.")
                                    dismiss_btn = page.query_selector("button[aria-label='Dismiss'], button[data-test-modal-close-btn], .artdeco-modal__dismiss")
                                    if dismiss_btn:
                                        try:
                                            dismiss_btn.click(force=True)
                                            time.sleep(1)
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

                    # Check if target applications met
                    if applications_done >= target_applications:
                        print(f"\n🎉 Target of {target_applications} applications reached!")
                        break

                    # Step 4: Advance to Next Page (Page 2, 3, 4, etc.)
                    next_page_num = current_page + 1
                    expected_start = (next_page_num - 1) * 25
                    print(f"\n[+] Finished scanning Page {current_page}. Advancing to Page {next_page_num}...")

                    # Scroll to bottom of list container so pagination buttons load into view
                    try:
                        page.evaluate("""() => {
                            const list = document.querySelector('.jobs-search-results-list, .jobs-search-results-display, .scaffold-layout__list, main');
                            if (list) list.scrollTop = list.scrollHeight;
                        }""")
                    except:
                        pass
                    page.wait_for_timeout(1500)

                    # Try clicking UI pagination buttons first
                    ui_nav_success = False
                    pagination_selectors = [
                        f"button[aria-label='Page {next_page_num}']",
                        f"li[data-test-pagination-page-btn='{next_page_num}'] button",
                        "button[aria-label='View next page']",
                        "button[aria-label='Next']",
                        "button.artdeco-pagination__button--next",
                        "li.artdeco-pagination__indicator--number.active + li button",
                        "li.artdeco-pagination__indicator--number.selected + li button",
                        ".artdeco-pagination button:has-text('Next')"
                    ]

                    for sel in pagination_selectors:
                        try:
                            p_btn = page.query_selector(sel)
                            if p_btn and p_btn.is_visible() and p_btn.is_enabled():
                                print(f"  Clicking pagination button: '{sel}'...")
                                p_btn.scroll_into_view_if_needed()
                                p_btn.click(force=True)
                                page.wait_for_timeout(3500)
                                if f"start={expected_start}" in page.url or page.query_selector(f"li.active button[aria-label='Page {next_page_num}']"):
                                    ui_nav_success = True
                                    print(f"  Successfully advanced to Page {next_page_num} via UI click.")
                                    break
                        except Exception:
                            pass

                    # Guaranteed URL fallback if UI click did not advance
                    if not ui_nav_success:
                        print(f"  Advancing to Page {next_page_num} (start={expected_start}) via direct URL navigation...")
                        try:
                            parsed = urlparse(page.url)
                            qs = parse_qs(parsed.query)
                            qs['start'] = [str(expected_start)]
                            if 'currentJobId' in qs:
                                del qs['currentJobId']
                            if 'f_AL' not in qs:
                                qs['f_AL'] = ['true']
                            new_query = urlencode(qs, doseq=True)
                            next_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
                            page.goto(next_url, wait_until="domcontentloaded")
                            page.wait_for_timeout(3500)
                        except Exception as err:
                            print(f"  [!] URL navigation error: {err}")

                    current_page = next_page_num
                    human_delay(2.0, 3.0)
                
                print(f"\n[+] Finished session. Total applied in this session: {applications_done} jobs.")
                
                # Generate Report safely without KeyError: 'url'
                report_path = os.path.join(BASE_DIR, "linkedin_final_report.md")
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(f"# LinkedIn Automated Application Report\n\n")
                    f.write(f"**Total Applications:** {applications_done}\n\n")
                    f.write("### Successfully Applied:\n")
                    if applications_done > 0:
                        for job in applied_jobs[-applications_done:]:
                            link = job.get('url') or job.get('id') or '#'
                            title = job.get('title', 'Software Developer')
                            f.write(f"- {title} ([Link]({link}))\n")
                    else:
                        f.write("No new applications submitted during this session.\n")
                    
                print(f"Report saved to: {report_path}")

                if not getattr(args, 'unlimited', True):
                    break
        
        except KeyboardInterrupt:
            print("\n[!] LinkedIn Automation stopped by user.")
            break
        except Exception as err:
            print(f"\n[!] Session encountered unexpected error: {err}")
            print("  Auto-restarting in 10 seconds (Unstoppable Mode)...")
            time.sleep(10)

if __name__ == "__main__":
    run_linkedin()
