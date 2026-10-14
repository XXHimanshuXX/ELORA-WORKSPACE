import urllib.request
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

repos = [
    'fokrulanthro16-eng/eidolon-os',
    'paulholland511/eidetic-os',
    'deathbyknowledge/gsv',
    'Nolane-x/forge-os',
    'fiatrete/OpenDAN-Personal-AI-OS',
    'aniketkrs/aura-os',
    'agentverse-os/AgentVerse-OS'
]

req_headers = {'User-Agent': 'Mozilla/5.0'}

for r in repos:
    try:
        url = f'https://api.github.com/repos/{r}'
        req = urllib.request.Request(url, headers=req_headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
            branch = data.get("default_branch")
            stars = data.get("stargazers_count")
            desc = data.get("description")
            print(f"[{r}] branch={branch} stars={stars}\n  desc: {desc}")
    except Exception as e:
        print(f"[{r}] ERROR: {e}")
