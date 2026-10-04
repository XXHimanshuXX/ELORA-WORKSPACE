import os
import shutil

src = os.path.join(".ohmyagent", "design", "v1", "template-previews", "orbital-rings.png")
dst_dir = os.path.join(".ohmyagent", "design", "v1", "directions")
os.makedirs(dst_dir, exist_ok=True)
shutil.copyfile(src, os.path.join(dst_dir, "orbital-rings.png"))
print("copied")
