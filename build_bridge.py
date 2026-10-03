import os

import bpy

root = os.getcwd()
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

bpy.ops.mesh.primitive_cube_add(size=1, location=(-10, 0, 10))
bpy.context.active_object.scale = (4, 4, 20)
bpy.ops.mesh.primitive_cube_add(size=1, location=(10, 0, 10))
bpy.context.active_object.scale = (4, 4, 20)
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 5))
bpy.context.active_object.scale = (30, 4, 1)
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 16))
bpy.context.active_object.scale = (20, 2, 1)

out = os.path.join(root, "london_bridge.blend")
bpy.ops.wm.save_as_mainfile(filepath=out)
print("saved", out)
