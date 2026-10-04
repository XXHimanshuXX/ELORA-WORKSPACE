import os
import sys

p = os.path.join("D:\\Coding\\ELORA Workspace", ".ohmyagent", "design", "v1")
try:
    os.makedirs(p)
except FileExistsError:
    print("exists", p)
    sys.exit(1)
print("created", p)
