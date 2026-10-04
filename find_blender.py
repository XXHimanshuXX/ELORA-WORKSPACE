import os, subprocess

def find_blender():
    # Common install paths including typical secondary drives for Steam
    search_paths = [
        os.environ.get('ProgramW6432', 'C:\\Program Files'),
        os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs'),
        'C:\\SteamLibrary\\steamapps\\common',
        'D:\\SteamLibrary\\steamapps\\common',
        'D:\\Program Files',
        'D:\\Steam\\steamapps\\common',
        'C:\\Program Files (x86)\\Steam\\steamapps\\common'
    ]
    
    for base in search_paths:
        if not base or not os.path.exists(base):
            continue
        for root, dirs, files in os.walk(base):
            # Optimization: prune dirs that clearly aren't relevant to speed up walk
            dirs[:] = [d for d in dirs if 'blender' in d.lower() or 'steam' in d.lower() or 'foundation' in d.lower() or root == base]
            for f in files:
                if f.lower() == 'blender.exe':
                    return os.path.join(root, f)
    return None

blender_path = find_blender()
if blender_path:
    print(f'FOUND: {blender_path}')
    # Build the bridge using the previously generated script
    script_path = r'D:\Coding\ELORA-Workspace\build_bridge.py'
    subprocess.run([blender_path, '--background', '--python', script_path])
else:
    print('NOT_FOUND')
