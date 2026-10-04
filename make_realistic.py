import bpy
bpy.ops.wm.open_mainfile(filepath='D:/Coding/ELORA-Workspace/london_bridge.blend')
bpy.context.scene.render.engine = 'CYCLES'

stone = bpy.data.materials.new('Stone')
stone.use_nodes = True
ns = stone.node_tree.nodes
if 'Principled BSDF' in ns:
    ns['Principled BSDF'].inputs['Base Color'].default_value = (0.4, 0.35, 0.32, 1.0)
    ns['Principled BSDF'].inputs['Roughness'].default_value = 0.85

for obj in bpy.data.objects:
    if obj.type == 'MESH':
        if len(obj.data.materials) == 0:
            obj.data.materials.append(stone)
        else:
            obj.data.materials[0] = stone

bpy.ops.mesh.primitive_plane_add(size=500, location=(0, 0, -1.5))
water = bpy.context.active_object
water.name = 'RiverThames'
water_mat = bpy.data.materials.new('Water')
water_mat.use_nodes = True
wns = water_mat.node_tree.nodes
if 'Principled BSDF' in wns:
    wns['Principled BSDF'].inputs['Base Color'].default_value = (0.05, 0.12, 0.20, 1.0)
    wns['Principled BSDF'].inputs['Metallic'].default_value = 0.8
    wns['Principled BSDF'].inputs['Roughness'].default_value = 0.1
water.data.materials.append(water_mat)

bpy.ops.wm.save_as_mainfile(filepath='D:/Coding/ELORA-Workspace/london_bridge_realistic.blend')
print('\n\n--- REALISTIC BRIDGE SAVED ---\n\n')
