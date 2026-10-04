import os
import subprocess

html = os.path.abspath(os.path.join(".ohmyagent", "design", "v1", "prototype.html"))
out_dir = os.path.abspath(os.path.join(".ohmyagent", "design", "v1", "shots"))
os.makedirs(out_dir, exist_ok=True)
url = "file:///" + html.replace("\\", "/")
chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
if not os.path.exists(chrome):
    chrome = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
frames = [
    ("desktop-1440.png", "1440,900"),
    ("tablet-768.png", "768,1024"),
    ("mobile-390.png", "390,844"),
]
for name, size in frames:
    dest = os.path.join(out_dir, name)
    cmd = [
        chrome, "--headless=new", "--disable-gpu",
        f"--window-size={size}",
        f"--screenshot={dest}",
        url,
    ]
    print("run", name)
    subprocess.run(cmd, check=False)
    print("exists", os.path.exists(dest), dest)
