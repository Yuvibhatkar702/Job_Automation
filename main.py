import os
import sys
import json
import subprocess
from ai_provider import is_ai_available
from profile_manager import load_profile_data, get_candidate_profile_prompt
from qa_engine import load_qa_memory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_banner():
    print("=" * 65)
    print("      🚀 AUTONOMOUS DYNAMIC AI JOB APPLICATION SUITE 🚀")
    print("=" * 65)
    
    # Status Indicators
    ai_status = "✅ Mistral/Gemini Active" if is_ai_available() else "❌ AI API Key Missing (Check config.json)"
    profile = load_profile_data()
    name = profile.get("personal_info", {}).get("full_name", "Yuvraj Bhatkar")
    qa_count = len(load_qa_memory())

    print(f" Candidate: {name}")
    print(f" AI Engine: {ai_status}")
    print(f" QA Memory: {qa_count} Cached Recruiter Answers")
    print("=" * 65)

def run_script(script_name: str):
    script_path = os.path.join(BASE_DIR, script_name)
    if not os.path.exists(script_path):
        print(f"[!] Script not found: {script_name}")
        return
    print(f"\n[+] Launching {script_name}...\n")
    try:
        subprocess.run([sys.executable, script_path], cwd=BASE_DIR)
    except KeyboardInterrupt:
        print(f"\n[!] Stopped {script_name}.")
    except Exception as e:
        print(f"\n[!] Error running {script_name}: {e}")

def view_profile_summary():
    clear_screen()
    print("=" * 65)
    print("                📄 CANDIDATE PROFILE SUMMARY")
    print("=" * 65)
    print(get_candidate_profile_prompt())
    print("=" * 65)
    input("\nPress ENTER to return to main menu...")

def view_qa_memory_summary():
    clear_screen()
    print("=" * 65)
    print("             🧠 QA MEMORY KNOWLEDGE BASE")
    print("=" * 65)
    memory = load_qa_memory()
    if not memory:
        print(" No cached recruiter answers yet. Run an assistant to start learning!")
    else:
        print(f" Total Cached Q&A Pairs: {len(memory)}\n")
        for idx, (q, a) in enumerate(memory.items(), 1):
            print(f" [{idx}] Q: {q}")
            print(f"     A: {a}\n")
    print("=" * 65)
    input("\nPress ENTER to return to main menu...")

def main_menu():
    while True:
        clear_screen()
        print_banner()
        print("""
 Select an option:

 [1] 🟢 Run Naukri Assistant (Instant Apply + Chatbot Solver)
 [2] 💼 Run LinkedIn Assistant (Easy Apply Solver)
 [3] 🌐 Run Hirist Assistant
 [4] 🔍 Run Indeed Assistant (Easily Apply Solver)
 [5] 🔄 Run All Platforms Sequentially
 [6] 📄 View Candidate Profile
 [7] 🧠 View Cached QA Memory
 [8] ❌ Exit
""")
        choice = input("Enter choice [1-8]: ").strip()

        if choice == "1":
            run_script("naukri_assistant.py")
            input("\nApplication run finished. Press ENTER to return to menu...")
        elif choice == "2":
            run_script("linkedin_assistant.py")
            input("\nApplication run finished. Press ENTER to return to menu...")
        elif choice == "3":
            run_script("hirist_assistant.py")
            input("\nApplication run finished. Press ENTER to return to menu...")
        elif choice == "4":
            run_script("indeed_assistant.py")
            input("\nApplication run finished. Press ENTER to return to menu...")
        elif choice == "5":
            print("\n[+] Starting Full Suite Application Run...")
            run_script("naukri_assistant.py")
            run_script("linkedin_assistant.py")
            run_script("indeed_assistant.py")
            input("\nFull Suite finished. Press ENTER to return to menu...")
        elif choice == "6":
            view_profile_summary()
        elif choice == "7":
            view_qa_memory_summary()
        elif choice == "8":
            print("\nExiting. Good luck with your job search! 🚀")
            break
        else:
            print("[!] Invalid choice. Try again.")

if __name__ == "__main__":
    main_menu()
