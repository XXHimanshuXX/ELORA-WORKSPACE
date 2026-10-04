import subprocess
try:
    exe = r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
    res = subprocess.run([exe, '-b', '-P', r'D:\Coding\ELORA-Workspace\make_realistic.py'], capture_output=True, text=True)
    with open(r'D:\Coding\ELORA-Workspace\b_debug.txt', 'w') as f:
        f.write(f'STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}\nRETURNCODE: {res.returncode}')
except Exception as e:
    with open(r'D:\Coding\ELORA-Workspace\b_debug.txt', 'w') as f:
        f.write(f'EXCEPTION:\n{str(e)}')
