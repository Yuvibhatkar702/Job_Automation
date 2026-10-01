import time
from playwright.sync_api import sync_playwright

def test():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings?keywords=Software%20Developer%20fresher&location=Pune&start=0"
        print(f"Navigating to {url}...")
        page.goto(url)
        page.wait_for_load_state("networkidle")
        
        print("Page URL after load:", page.url)
        print("Page title:", page.title())
        
        # Save HTML
        html_content = page.content()
        with open("C:/Users/Admin/.gemini/antigravity/scratch/job_assistant/debug.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        print("Saved debug.html")
        
        # Take screenshot
        page.screenshot(path="C:/Users/Admin/.gemini/antigravity/scratch/job_assistant/debug.png")
        print("Saved debug.png")
        
        browser.close()

if __name__ == "__main__":
    test()
