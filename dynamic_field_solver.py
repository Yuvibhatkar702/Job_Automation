import re
from playwright.sync_api import Page, ElementHandle
from qa_engine import answer_hr_question

def sanitize_number(text: str, default: int = 0) -> str:
    match = re.search(r'\d+', text)
    return match.group(0) if match else str(default)

def match_dropdown_option(select_el: ElementHandle, target_text: str) -> str:
    try:
        options = select_el.query_selector_all("option")
        option_map = []
        for opt in options:
            val = opt.get_attribute("value") or ""
            txt = opt.inner_text().strip()
            if txt and txt.lower() not in ["select", "choose", "--select--"]:
                option_map.append((val, txt))

        if not option_map:
            return ""

        target_norm = target_text.lower().strip()

        # 1. Exact or substring match on option text
        for val, txt in option_map:
            if target_norm in txt.lower() or txt.lower() in target_norm:
                return val or txt

        # 2. Keyword matching for common HR fields
        if "immediate" in target_norm or "0" in target_norm:
            for val, txt in option_map:
                if any(w in txt.lower() for w in ["immediate", "0", "15 days", "1 month", "fresher"]):
                    return val or txt

        return option_map[0][0] or option_map[0][1]
    except Exception as e:
        print(f"  [!] Dropdown Match Error: {e}")
        return ""

def fill_element_dynamically(page: Page, element: ElementHandle, question_label: str) -> bool:
    try:
        tag_name = element.evaluate("el => el.tagName").lower()
        el_type = element.get_attribute("type") or "text"

        if el_type in ["hidden", "file", "submit", "image", "reset"]:
            return False

        # Generate answer using QA Engine
        answer = answer_hr_question(question_label)

        if tag_name == "select":
            selected_val = match_dropdown_option(element, answer)
            if selected_val:
                try:
                    element.select_option(value=selected_val)
                except:
                    element.select_option(label=selected_val)
                return True

        elif el_type in ["checkbox", "radio"]:
            should_check = any(w in answer.lower() for w in ["yes", "true", "1", "immediate", "fresher"]) or bool(answer)
            if should_check:
                try:
                    element.evaluate("el => { const l = el.closest('label') || el; l.click(); }")
                except:
                    element.click(force=True)
            return True

        elif tag_name in ["input", "textarea"]:
            # Format text based on input characteristics
            if "number" in el_type or "exp" in question_label.lower() or "notice" in question_label.lower():
                final_val = sanitize_number(answer, default=0)
            else:
                final_val = answer

            element.fill(final_val)
            return True

    except Exception as e:
        print(f"  [!] Dynamic Field Fill Error for '{question_label}': {e}")

    return False
