import subprocess
import sys
import os

def run_command(command):
    result = subprocess.run(command, shell=True)
    if result.returncode != 0:
        print(f"❌ Command failed: {command}")

def git_pull():
    print("🔄 Pulling latest changes...")
    run_command("git pull")

def venv_create():
    print("🛠️ Creating fresh Virtual Environment...")
    run_command("python -m venv venv")

def venv_activate():
    print("Activating Virtual Environment...")
    
    if os.name == "nt":  # Windows
        activate_cmd = "venv\\Scripts\\activate"
    else:  # macOS/Linux
        activate_cmd = "source venv/bin/activate"

    # Opens a new shell with venv activated
    subprocess.run(f"cmd /k {activate_cmd}" if os.name == "nt" else activate_cmd, shell=True)

def dependencies_installation():
    print("Installing requirements...")
    print("Run pip cache purge (recommended)")

    
    if os.name == "nt":
        pip_path = "venv\\Scripts\\pip"
    else:
        pip_path = "venv/bin/pip"

    run_command("python.exe -m pip install --upgrade pip")
    run_command(f"{pip_path} cache purge")
    run_command(f"{pip_path} install -r requirements.txt")

def prisma_generate():
    print("Generating Prisma client...")
    run_command("prisma db pull")
    run_command("prisma generate")

def run_all():
    git_pull()
    venv_create()
    dependencies_installation()
    prisma_generate()

def exit_program():
    print("Exiting automation tool...")
    sys.exit(0)

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
    while True:
        print("\n===== Automation Menu =====")
        print("1. Git Pull")
        print("2. Create Virtual Environment")
        print("3. Activate Virtual Environment")
        print("4. Install Dependencies")
        print("5. Prisma Generate")
        print("6. Run Full Setup")
        print("7. Exit")

        choice = input("Choose option (1-7): ").strip()
        action = switch.get(choice)

        if action:
            action()
        else:
            print("❌ Invalid option. Try again.")