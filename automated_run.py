# This script must be started using [ .\dev.ps1 ] command typed via terminal for best results!!!
# You can still directly run this script using [ python automated_run.py ] command typed via terminal for step by step process (mostly for debug use)
import subprocess
import sys
import os

PYTHON_VERSION_REQUIRED = "3.10"

def run_command(command, env=None):
    result = subprocess.run(command, shell=True, env=env)
    if result.returncode != 0:
        print(f"❌ Command failed: {command}")
        sys.exit(result.returncode)

def check_python_version():
    if not sys.version.startswith(PYTHON_VERSION_REQUIRED):
        print("❌ This script must be run with Python 3.10.x")
        print(f"Current version: {sys.version}")
        sys.exit(1)

def git_pull():
    print("🔄 Pulling latest changes...")
    run_command("git pull")

def venv_create():
    print("🛠️ Creating Virtual Environment using Python 3.10...")

    if os.name == "nt":
        python_cmd = "py -3.10"
    else:
        python_cmd = "python3.10"

    run_command(f"{python_cmd} -m venv venv")

def venv_activate():
    print("Opening a new terminal with the virtual environment activated...")

    if os.name == "nt":  # Windows
        activate_script = os.path.abspath("venv\\Scripts\\activate.bat")
        subprocess.run(f'start cmd /k "{activate_script}"', shell=True)
    else:  # Linux/macOS
        activate_script = os.path.abspath("venv/bin/activate")
        subprocess.run(f'gnome-terminal -- bash -c "source {activate_script}; exec bash"', shell=True)

    print("✅ New terminal launched with venv activated.")

def dependencies_installation():
    print("📦 Installing requirements using Python 3.10 venv...")

    if os.name == "nt":
        python_path = "venv\\Scripts\\python"
    else:
        python_path = "venv/bin/python"

    run_command(f"{python_path} -m pip install --upgrade pip")
    run_command(f"{python_path} -m pip cache purge")
    run_command(f"{python_path} -m pip install -r requirements.txt")

def prisma_generate():
    print("\n⚙️ Generating Prisma client...\n")

    if os.name == "nt":
        prisma_path = r"venv\Scripts\prisma.exe"
        scripts_path = os.path.abspath(r"venv\Scripts")
    else:
        prisma_path = "venv/bin/prisma"
        scripts_path = os.path.abspath("venv/bin")

    env = os.environ.copy()
    env["PATH"] = scripts_path + os.pathsep + env["PATH"]

    subprocess.run(f"{prisma_path} db pull", shell=True, env=env)
    subprocess.run(f"{prisma_path} generate", shell=True, env=env)

    print("✅ Prisma client generated.")

def run_all():
    print("\n🚀 Running FULL setup automatically...\n")
    git_pull()
    venv_create()
    dependencies_installation()
    prisma_generate()

def exit_program():
    print("\nAutomation finished. Exiting...")
    sys.exit(0)



# def exit_program():
#     print("\nAutomation finished. Launching a VS Code terminal with venv activated...")

#     if os.name == "nt":
#         activate_script = os.path.join(os.getcwd(), "venv", "Scripts", "Activate.ps1")

#         subprocess.Popen([
#             "powershell",
#             "-NoExit",
#             "-ExecutionPolicy", "Bypass",
#             "-Command",
#             f"cd '{os.getcwd()}'; & '{activate_script}'"
#         ])

#     else:
#         subprocess.Popen([
#             "bash",
#             "-c",
#             f"cd '{os.getcwd()}'; source venv/bin/activate; exec bash"
#         ])

#     sys.exit(0)

# def exit_program():
#     print("\nAutomation finished. Opening terminal with venv activated...\n")

#     project_dir = os.getcwd()

#     if os.name == "nt":
#         activate_script = os.path.join(project_dir, "venv", "Scripts", "Activate.ps1")

#         subprocess.Popen([
#             "powershell",
#             "-NoExit",
#             "-ExecutionPolicy", "Bypass",
#             "-File", activate_script
#         ], cwd=project_dir)

#     else:
#         subprocess.Popen([
#             "bash",
#             "-i",
#             "-c",
#             f"cd '{project_dir}'; source venv/bin/activate; exec bash"
#         ])

#     sys.exit(0)

switch = {
    "1": git_pull,
    "2": venv_create,
    "3": venv_activate,
    "4": dependencies_installation,
    "5": prisma_generate,
    "6": run_all,
    "7": exit_program
}

if __name__ == "__main__":
    check_python_version()

    while True:
        print("\n========== Backend Setup Automation ==========")
        print("Choose how you want to run the setup:\n")
    
        print("🔹 Option 1: Run full setup automatically")
        print("   → Select [6] Run Full Setup\n")
    
        print("🔹 Option 2: Run setup manually step-by-step")
        print("   → Follow options [1] → [5]\n")
    
        print("--------------- Menu ---------------")
        print("1. Git Pull")
        print("2. Create Virtual Environment (Python 3.10)")
        print("3. Activate Virtual Environment {script will exit & rerun the automated_run.py in new venv activated terminal}")
        print("4. Install Dependencies")
        print("5. Prisma Generate")
        print("6. Run Full Setup { recommended }")
        print("7. Exit + Activate venv { recommended, will only work if this script was ran via dev.ps1}")
    
        choice = input("\nChoose option (1-7): ").strip()
        action = switch.get(choice)
    
        if action:
            action()
        else:
            print("❌ Invalid option. Try again.")