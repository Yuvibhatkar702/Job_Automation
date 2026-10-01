import os
import json
import time
from playwright.sync_api import Page
from ai_provider import ask_ai, is_ai_available

# Make sure this matches the path where the user stores their resume
RESUME_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume.pdf")

def solve_complex_form_with_ai(page: Page, profile: str, max_pages=5):
    """
    Attempts to autonomously fill out multi-page ATS applications by scanning
    for inputs, asking AI (Mistral/Gemini) for the answers based on the profile, and clicking Next/Submit.
    """
    print("\n    [AI] Initiating Universal Form Filler...")
    
    if not is_ai_available():
        print("    [!] Neither MISTRAL_API_KEY nor GEMINI_API_KEY is set. Cannot auto-fill complex forms.")
        return False

    for page_num in range(max_pages):
        print(f"    [AI] Scanning page {page_num + 1}...")
        page.wait_for_timeout(2000)
        
        if page.is_closed():
            break
            
        # Upload resume if possible
        try:
            file_inputs = page.query_selector_all("input[type='file']")
            for file_in in file_inputs:
                if os.path.exists(RESUME_PATH):
                    print("    [AI] Found file upload, attaching resume.pdf...")
                    file_in.set_input_files(RESUME_PATH)
        except Exception as e:
            print(f"    [!] Error uploading file: {e}")
            
        # Collect all text/select inputs
        inputs = page.query_selector_all("input:not([type='hidden']):not([type='file']):not([type='submit']), textarea, select")
        
        if not inputs:
            print("    [AI] No input fields found on this page.")
        else:
            questions = []
            for idx, el in enumerate(inputs):
                tag_name = el.evaluate("el => el.tagName").lower()
                el_type = el.get_attribute("type") or "text"
                el_id = el.get_attribute("id") or ""
                el_name = el.get_attribute("name") or ""
                placeholder = el.get_attribute("placeholder") or ""
                
                # Try to find a label
                label_text = ""
                if el_id:
                    try:
                        label = page.query_selector(f"label[for='{el_id}']")
                        if label:
                            label_text = label.inner_text().strip()
                    except:
                        pass
                
                # Fallback to nearest text if no formal label exists
                if not label_text:
                    label_text = placeholder or el_name or el_id
                    
                questions.append({
                    "index": idx,
                    "tag": tag_name,
                    "type": el_type,
                    "label": label_text,
                    "id": el_id
                })
                
            if questions:
                print(f"    [AI] Found {len(questions)} inputs. Consulting Gemini...")
                prompt = f"""
You are an AI assistant helping a candidate apply for a job.
Candidate Profile:
{profile}

The application form has the following input fields:
{json.dumps(questions, indent=2)}

INSTRUCTIONS:
- You MUST provide an answer for EVERY SINGLE field listed above.
- If a question asks about years of experience, notice period, location, salary expectations, or willingness to relocate, provide positive & realistic answers matching a fresh graduate (e.g. 0-1 years exp, Immediate joiner, willing to relocate, standard CTC).
- Respond ONLY with a valid JSON array of objects.

Each object must have:
- "index": the index of the field
- "value": the text to type, OR for checkboxes/radios, a boolean true/false, OR for select options, the option text.
"""
                try:
                    res_text = ask_ai(prompt, system_prompt="You are an AI assistant helping a candidate fill job applications.")
                    text = res_text.replace('```json', '').replace('```', '').strip()
                    answers = json.loads(text)
                    
                    for ans in answers:
                        idx = ans.get("index")
                        val = ans.get("value")
                        if idx is not None and idx < len(inputs):
                            el = inputs[idx]
                            q = questions[idx]
                            
                            try:
                                if q["type"] in ["checkbox", "radio"]:
                                    if val:
                                        # Try clicking label first, then input directly
                                        label = page.query_selector(f"label[for='{q['id']}']") if q['id'] else None
                                        if label:
                                            label.click(force=True)
                                        else:
                                            parent_label = el.evaluate_handle("el => el.closest('label')")
                                            if parent_label:
                                                parent_label.click(force=True)
                                            else:
                                                el.click(force=True)
                                elif q["tag"] == "select":
                                    el.select_option(label=str(val))
                                else:
                                    el.fill(str(val))
                            except Exception as e:
                                print(f"    [!] Error filling field {q['label']}: {e}")
                except Exception as e:
                    print(f"    [!] AI Generation Error: {e}")
                    
                # Fallback pass: ensure any remaining empty text inputs are filled
                for idx, el in enumerate(inputs):
                    try:
                        q = questions[idx]
                        if q["tag"] in ["input", "textarea"] and q["type"] not in ["checkbox", "radio", "hidden", "file"]:
                            if not el.input_value():
                                default_val = "Immediate joiner / 0-1 years relevant experience."
                                if "salary" in q["label"].lower() or "ctc" in q["label"].lower():
                                    default_val = "As per industry standard"
                                elif "notice" in q["label"].lower():
                                    default_val = "Immediate"
                                elif "city" in q["label"].lower() or "location" in q["label"].lower():
                                    default_val = "Flexible / Open to relocation"
                                el.fill(default_val)
                    except:
                        pass
        
        # Look for a Next or Submit button
        submit_btn = None
        selectors = [
            "button:has-text('Submit')", "button:has-text('Apply')", 
            "button:has-text('Next')", "button:has-text('Continue')",
            "input[type='submit']", "a:has-text('Submit Application')"
        ]
        
        for sel in selectors:
            try:
                submit_btn = page.query_selector(sel)
                if submit_btn and submit_btn.is_visible():
                    break
            except:
                pass
                
        if submit_btn:
            btn_text = submit_btn.inner_text().strip() or submit_btn.get_attribute("value") or "Submit"
            print(f"    [AI] Clicking '{btn_text}'...")
            submit_btn.click(force=True)
            page.wait_for_timeout(4000) # Wait for page load or validation errors
            
            # Check for generic failure messages on the page
            try:
                if page.query_selector("text='Oops! Your application was not accepted', text='incomplete information'"):
                    print("    [!] 'Incomplete information' error detected! Form submission failed.")
                    return False
            except:
                pass
            
            # If the URL implies success or we closed the tab, we are done
            if page.is_closed():
                print("    [AI] Tab closed. Assuming success.")
                return True
                
            if "success" in page.url.lower() or "thank" in page.url.lower() or "applied" in page.url.lower():
                print("    [AI] Success URL detected!")
                return True
        else:
            print("    [AI] No obvious Next/Submit button found. Stopping form traversal.")
            break
            
    print("    [AI] Form traversal completed or max pages reached.")
    return True
