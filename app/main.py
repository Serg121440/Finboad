import subprocess
import sys
import os

if __name__ == "__main__":
    port = os.environ.get("PORT", "8501")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        os.path.join(root, "dashboard", "app.py"),
        "--server.port", port,
        "--server.address", "0.0.0.0",
        "--server.headless", "true",
    ])
