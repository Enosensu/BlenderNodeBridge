bl_info = {
    "name": "GeoNeural Bridge (v2.5.2 Smart-Frame)",
    "author": "Dev_Nodes_V5",
    "version": (2, 5, 2),
    "blender": (4, 0, 0),
    "location": "Node Editor > Sidebar > GeoNeural",
    "description": "Fixed Frame overlap by auto-calculating centroids for parenting.",
    "category": "Node",
}

import bpy
import json

# ==============================================================================
# 0. Embedded Mapping Database (Updated for Blender 4.0+)
# ==============================================================================
NODE_TRANSLATION_TABLE = {
    "GeometryNodeTree": {
        "ShaderNodeTexNoise": "GeometryNodeInputNoiseTexture",
        "ShaderNodeTexVoronoi": "GeometryNodeInputVoronoiTexture",
        "ShaderNodeTexWave": "GeometryNodeInputWaveTexture",
        "ShaderNodeTexMagic": "GeometryNodeInputMagicTexture",
        "ShaderNodeTexChecker": "GeometryNodeInputCheckerTexture",
        "ShaderNodeTexGradient": "GeometryNodeInputGradientTexture",
        "ShaderNodeTexWhiteNoise": "GeometryNodeInputWhiteNoise",
        "ShaderNodeTexBrick": "GeometryNodeInputBrickTexture",
        "ShaderNodeMath": "ShaderNodeMath",
        "ShaderNodeVectorMath": "ShaderNodeVectorMath",
        "ShaderNodeMix": "ShaderNodeMix",
        "ShaderNodeValToRGB": "GeometryNodeValToRGB",
        "ShaderNodeRGBCurve": "GeometryNodeCurveRGB",
        "ShaderNodeVectorCurve": "GeometryNodeCurveVector",
        "ShaderNodeMapRange": "GeometryNodeMapRange",
        "ShaderNodeClamp": "GeometryNodeClamp",
        "ShaderNodeRGB": "GeometryNodeInputRGB",
        "ShaderNodeValue": "GeometryNodeInputValue",
        "ShaderNodeCombineXYZ": "ShaderNodeCombineXYZ",
        "ShaderNodeSeparateXYZ": "ShaderNodeSeparateXYZ",
        "ShaderNodeCombineRGB": "ShaderNodeCombineRGB",
        "ShaderNodeSeparateRGB": "ShaderNodeSeparateRGB",
        "ShaderNodeCombineColor": "ShaderNodeCombineColor",
        "ShaderNodeSeparateColor": "ShaderNodeSeparateColor",
        "ShaderNodeNewGeometry": "GeometryNodeInputPosition",
        "ShaderNodeUVMap": "GeometryNodeInputNamedAttribute",
        "ShaderNodeObjectInfo": "GeometryNodeObjectInfo",
        "ShaderNodeAttribute": "GeometryNodeInputNamedAttribute",
        "ShaderNodeNormal": "GeometryNodeInputNormal",
        "GeometryNodeEndpointSelection": "GeometryNodeCurveEndpointSelection"
    },
    "ShaderNodeTree": {
        "GeometryNodeInputNoiseTexture": "ShaderNodeTexNoise",
        "GeometryNodeInputVoronoiTexture": "ShaderNodeTexVoronoi",
        "GeometryNodeInputWaveTexture": "ShaderNodeTexWave",
        "GeometryNodeInputMagicTexture": "ShaderNodeTexMagic",
        "GeometryNodeInputCheckerTexture": "ShaderNodeTexChecker",
        "GeometryNodeInputGradientTexture": "ShaderNodeTexGradient",
        "GeometryNodeInputWhiteNoise": "ShaderNodeTexWhiteNoise",
        "GeometryNodeInputBrickTexture": "ShaderNodeTexBrick",
        "GeometryNodeMath": "ShaderNodeMath",
        "GeometryNodeVectorMath": "ShaderNodeVectorMath",
        "GeometryNodeMix": "ShaderNodeMix",
        "GeometryNodeValToRGB": "ShaderNodeValToRGB",
        "GeometryNodeCurveRGB": "ShaderNodeRGBCurve",
        "GeometryNodeCurveVector": "ShaderNodeVectorCurve",
        "GeometryNodeMapRange": "ShaderNodeMapRange",
        "GeometryNodeClamp": "ShaderNodeClamp",
        "GeometryNodeInputRGB": "ShaderNodeRGB",
        "GeometryNodeInputValue": "ShaderNodeValue",
        "FunctionNodeInputBool": "ShaderNodeValue",
        "FunctionNodeInputInt": "ShaderNodeValue",
        "GeometryNodeInputPosition": "ShaderNodeNewGeometry",
        "GeometryNodeInputNormal": "ShaderNodeNewGeometry",
        "GeometryNodeInputTangent": "ShaderNodeNewGeometry",
        "GeometryNodeInputUVMap": "ShaderNodeUVMap",
        "GeometryNodeObjectInfo": "ShaderNodeObjectInfo",
        "GeometryNodeInputNamedAttribute": "ShaderNodeAttribute"
    },
    "CompositorNodeTree": {
        "ShaderNodeMath": "CompositorNodeMath",
        "GeometryNodeMath": "CompositorNodeMath",
        "ShaderNodeVectorMath": "CompositorNodeVectorMath",
        "ShaderNodeMix": "CompositorNodeMixRGB",
        "ShaderNodeValToRGB": "CompositorNodeValToRGB",
        "ShaderNodeRGBCurve": "CompositorNodeCurveRGB",
        "ShaderNodeMapRange": "CompositorNodeMapRange",
        "ShaderNodeValue": "CompositorNodeValue",
        "ShaderNodeRGB": "CompositorNodeRGB",
        "ShaderNodeCombineRGB": "CompositorNodeCombineColor",
        "ShaderNodeSeparateRGB": "CompositorNodeSeparateColor"
    }
}

# ==============================================================================
# 1. Utility: Data Cleaning
# ==============================================================================

def clean_data(value):
    if value is None: return None
    if isinstance(value, bpy.types.ID):
        return value.name
    if isinstance(value, (int, float, str, bool)):
        if isinstance(value, float): return round(value, 4)
        return value
    if hasattr(value, "to_list"): return [clean_data(x) for x in value.to_list()]
    if hasattr(value, "to_tuple"): return [clean_data(x) for x in value.to_tuple()]
    if isinstance(value, (list, tuple)): return [clean_data(x) for x in value]
    if isinstance(value, dict): return {k: clean_data(v) for k, v in value.items()}
    return None

def get_socket_index(node_sockets, target_socket):
    for i, s in enumerate(node_sockets):
        if s == target_socket:
            return i
    return -1

# ==============================================================================
# 2. Core Logic: Serialization
# ==============================================================================

def serialize_interface(node_tree):
    interface_data = []
    if hasattr(node_tree, "interface"):
        for item in node_tree.interface.items_tree:
            if item.item_type == 'SOCKET':
                socket_info = {
                    "name": item.name, "in_out": item.in_out, "socket_type": item.socket_type
                }
                if item.in_out == 'INPUT':
                    try:
                        socket_info["default_value"] = clean_data(item.default_value)
                        socket_info["min_value"] = clean_data(getattr(item, "min_value", None))
                        socket_info["max_value"] = clean_data(getattr(item, "max_value", None))
                    except: pass
                interface_data.append(socket_info)
    return interface_data

def serialize_single_tree(node_tree, nodes_to_process=None, is_compact=False):
    if nodes_to_process is None: nodes_to_process = node_tree.nodes
    data = { "tree_type": node_tree.bl_idname, "nodes": [], "links": [] }
    valid_names = {n.name for n in nodes_to_process}
    GROUP_TYPES = {'GeometryNodeGroup', 'ShaderNodeGroup', 'CompositorNodeGroup'}

    ALWAYS_EXCLUDE = {'rna_type', 'node_tree', 'inputs', 'outputs', 'interface', 'dimensions'}
    COMPACT_EXCLUDE = {
        'name', 'location', 'width', 'height', 'select', 'color', 
        'label', 'hide', 'mute', 'use_custom_color', 'location_absolute', 
        'warning_propagation', 'color_tag', 'parent', 'width_hidden'
    }
    COMPACT_PREFIX_EXCLUDE = ('bl_', 'show_', '_')

    for node in nodes_to_process:
        node_type = node.bl_idname
        node_data = {
            "name": node.name,
            "type": node_type,
            "params": {}, 
            "inputs": {}
        }
        
        if not is_compact:
            if node.parent:
                node_data["parent"] = node.parent.name
            node_data["location"] = [int(node.location.x), int(node.location.y)]
            if node.bl_idname == 'NodeFrame':
                node_data["width"] = node.width
                node_data["height"] = node.height

        if node.bl_idname in GROUP_TYPES and node.node_tree:
            node_data["node_tree_name"] = node.node_tree.name

        for prop in node.bl_rna.properties.keys():
            if prop in ALWAYS_EXCLUDE: continue
            if is_compact:
                if prop in COMPACT_EXCLUDE: continue
                if prop.startswith(COMPACT_PREFIX_EXCLUDE): continue
            
            try:
                safe_val = clean_data(getattr(node, prop))
                if safe_val is not None: 
                    node_data["params"][prop] = safe_val
            except: pass

        for socket in node.inputs:
            if socket.bl_idname in {'NodeSocketGeometry', 'NodeSocketShader', 'NodeSocketVirtual'}: continue
            if not socket.is_linked:
                try:
                    safe_val = clean_data(socket.default_value)
                    if safe_val is not None: node_data["inputs"][socket.name] = safe_val
                except: pass
        data["nodes"].append(node_data)

    for link in node_tree.links:
        if link.from_node.name in valid_names and link.to_node.name in valid_names:
            src_idx = get_socket_index(link.from_node.outputs, link.from_socket)
            dst_idx = get_socket_index(link.to_node.inputs, link.to_socket)
            
            link_data = {
                "src": link.from_node.name, 
                "src_sock": link.from_socket.name,
                "src_index": src_idx,
                "dst": link.to_node.name, 
                "dst_sock": link.to_socket.name,
                "dst_index": dst_idx
            }
            data["links"].append(link_data)
            
    return data

def serialize_recursive(start_tree, selected_only=False, is_compact=False):
    deps = {} 
    GROUP_TYPES = {'GeometryNodeGroup', 'ShaderNodeGroup', 'CompositorNodeGroup'}
    if selected_only: root_nodes = [n for n in start_tree.nodes if n.select]
    else: root_nodes = list(start_tree.nodes)
        
    root_data = serialize_single_tree(start_tree, root_nodes, is_compact=is_compact)
    trees_to_scan = set()
    for n in root_nodes:
        if n.bl_idname in GROUP_TYPES and n.node_tree: trees_to_scan.add(n.node_tree)

    scanned_trees = set()
    while trees_to_scan:
        current_tree = trees_to_scan.pop()
        if current_tree in scanned_trees: continue
        scanned_trees.add(current_tree)
        
        tree_def = serialize_single_tree(current_tree, is_compact=is_compact)
        tree_def["interface"] = serialize_interface(current_tree)
        tree_def["type_id"] = current_tree.bl_idname 
        deps[current_tree.name] = tree_def
        
        for n in current_tree.nodes:
            if n.bl_idname in GROUP_TYPES and n.node_tree:
                if n.node_tree not in scanned_trees: trees_to_scan.add(n.node_tree)

    return { "version": "2.5.2", "compact": is_compact, "root": root_data, "dependencies": deps }

# ==============================================================================
# 3. Core Logic: Smart Build & Auto-Layout
# ==============================================================================

def rebuild_interface(node_tree, interface_data):
    if not interface_data: return
    node_tree.interface.clear()
    for item in interface_data:
        try:
            socket_item = node_tree.interface.new_socket(
                item.get("name", "Socket"), 
                in_out=item.get("in_out", "INPUT"), 
                socket_type=item.get("socket_type", "NodeSocketFloat")
            )
            if item.get("in_out") == 'INPUT':
                def_val = item.get("default_value")
                if def_val is not None:
                    try: socket_item.default_value = def_val
                    except: pass
                if item.get("min_value") is not None: socket_item.min_value = item.get("min_value")
                if item.get("max_value") is not None: socket_item.max_value = item.get("max_value")
        except: pass

def apply_hierarchical_layout(node_tree, new_nodes):
    """ Fallback layout if NO coordinates exist at all. """
    if not new_nodes: return
    node_map = {n.name: n for n in new_nodes}
    children = {n.name: [] for n in new_nodes}
    parents = {n.name: [] for n in new_nodes}
    
    for link in node_tree.links:
        if link.from_node.name in node_map and link.to_node.name in node_map:
            children[link.from_node.name].append(link.to_node.name)
            parents[link.to_node.name].append(link.from_node.name)

    levels = {n.name: 0 for n in new_nodes}
    queue = [name for name, p_list in parents.items() if not p_list]
    if not queue and new_nodes: queue = [new_nodes[0].name]
    visited = set(queue)
    
    while queue:
        current_name = queue.pop(0)
        current_level = levels[current_name]
        for child_name in children[current_name]:
            if levels[child_name] < current_level + 1:
                levels[child_name] = current_level + 1
                if child_name not in visited: queue.append(child_name)
            if levels[child_name] > 200: continue

    level_groups = {}
    for name, lvl in levels.items():
        if lvl not in level_groups: level_groups[lvl] = []
        level_groups[lvl].append(name)
        
    X_STEP = 300
    Y_STEP = -220
    
    for lvl in sorted(level_groups.keys()):
        group = level_groups[lvl]
        def get_parent_avg_y(n_name):
            ps = parents[n_name]
            if not ps: return 0
            y_sum = sum([node_map[p].location.y for p in ps])
            return y_sum / len(ps)
        if lvl > 0: group.sort(key=get_parent_avg_y, reverse=True)
        
        start_y = ((len(group) - 1) * abs(Y_STEP)) / 2
        for i, name in enumerate(group):
            node_map[name].location.x = lvl * X_STEP
            node_map[name].location.y = start_y + (i * Y_STEP)

def build_single_tree(node_tree, data, offset=(0,0), clear=False, conversion_log=None):
    if clear: node_tree.nodes.clear()
    node_map = {}
    created_nodes = []
    has_valid_location = False 
    
    target_tree_type = node_tree.bl_idname
    translation_map = NODE_TRANSLATION_TABLE.get(target_tree_type, {})
    GROUP_TYPES = {'GeometryNodeGroup', 'ShaderNodeGroup', 'CompositorNodeGroup'}

    # 1. Create Nodes
    for n_data in data.get("nodes", []):
        original_type = n_data.get("type")
        target_type = original_type
        n_name = n_data.get("name")
        
        has_mapped = False
        if original_type in translation_map:
            target_type = translation_map[original_type]
            has_mapped = True
        
        node = None
        created_type = None 
        
        if has_mapped:
            try:
                node = node_tree.nodes.new(type=target_type)
                created_type = target_type
                if conversion_log is not None:
                    s_old = original_type.replace("ShaderNode", "").replace("GeometryNode", "").replace("Input", "")
                    s_new = target_type.replace("ShaderNode", "").replace("GeometryNode", "").replace("Input", "")
                    conversion_log.append(f"{n_name}: {s_old}->{s_new}")
            except: pass

        if node is None:
            try:
                node = node_tree.nodes.new(type=original_type)
                created_type = original_type
            except: continue 

        if node:
            node.name = n_name 
            node.select = True
            node_map[n_name] = node 
            created_nodes.append(node)
            
            # Location Extraction
            params_dict = n_data.get("params", {})
            loc = params_dict.get("location_absolute", params_dict.get("location"))
            if not loc: loc = n_data.get("location_absolute", n_data.get("location"))
            
            if loc and isinstance(loc, list) and len(loc) == 2:
                node.location = (loc[0] + offset[0], loc[1] + offset[1])
                if loc[0] != 0 or loc[1] != 0: has_valid_location = True
            else:
                node.location = (0, 0)
            
            if created_type == 'NodeFrame':
                if "width" in n_data: node.width = n_data["width"]
                if "height" in n_data: node.height = n_data["height"]
                if "label" in params_dict: node.label = params_dict["label"]

            for k, v in params_dict.items():
                if k in {"location", "location_absolute"}: continue
                if hasattr(node, k):
                    try: setattr(node, k, v)
                    except: pass
            
            for k, v in n_data.get("inputs", {}).items():
                if k in node.inputs:
                    try: 
                        socket = node.inputs[k]
                        if hasattr(socket, "type") and socket.type == 'OBJECT' and isinstance(v, str):
                            socket.default_value = bpy.data.objects.get(v)
                        elif hasattr(socket, "type") and socket.type == 'COLLECTION' and isinstance(v, str):
                            socket.default_value = bpy.data.collections.get(v)
                        elif hasattr(socket, "type") and socket.type == 'MATERIAL' and isinstance(v, str):
                            socket.default_value = bpy.data.materials.get(v)
                        elif hasattr(socket, "type") and socket.type == 'IMAGE' and isinstance(v, str):
                            socket.default_value = bpy.data.images.get(v)
                        else:
                            node.inputs[k].default_value = v
                    except: pass
            
            if created_type in GROUP_TYPES:
                tree_name = n_data.get("node_tree_name")
                if tree_name and tree_name in bpy.data.node_groups:
                    node.node_tree = bpy.data.node_groups[tree_name]

    # 2. Establish Parenting (Explicit)
    for n_data in data.get("nodes", []):
        child_name = n_data.get("name")
        parent_name = n_data.get("parent")
        if child_name and parent_name:
            child_node = node_map.get(child_name)
            parent_node = node_map.get(parent_name)
            if child_node and parent_node:
                try: child_node.parent = parent_node
                except: pass

    # 3. [NEW] Implicit Parenting & Frame Centering
    # AI often outputs frames as headers (Frame -> Nodes) but misses parent links and frame coordinates.
    current_implicit_frame = None
    frames_with_implicit_children = {} # {frame_node: [children]}

    # Pass A: Infer Parenting from List Order
    for node in created_nodes:
        if node.bl_idname == 'NodeFrame':
            current_implicit_frame = node
            frames_with_implicit_children[node] = []
        elif current_implicit_frame and node.parent is None:
            # If node has no explicit parent, assume it belongs to the preceding frame
            node.parent = current_implicit_frame
            frames_with_implicit_children[current_implicit_frame].append(node)
    
    # Pass B: Reposition Frames to Centroid (Fix Overlap)
    for frame, children in frames_with_implicit_children.items():
        # Only touch frames that are at (0,0) (likely undefined by AI) and have children
        if frame.location.x == 0 and frame.location.y == 0 and children:
            # Calculate Centroid
            avg_x = sum(n.location.x for n in children) / len(children)
            avg_y = sum(n.location.y for n in children) / len(children)
            
            # Move Frame to Center
            frame.location.x = avg_x
            frame.location.y = avg_y
            
            # Important: Compensate children so they don't move visually
            # (Parenting to a moved frame shifts children if local coords aren't updated)
            for child in children:
                child.location.x -= avg_x
                child.location.y -= avg_y

    if hasattr(node_tree, "update_tag"):
        node_tree.update_tag()

    # 4. Relink
    for l in data.get("links", []):
        src = node_map.get(l.get("src"))
        dst = node_map.get(l.get("dst"))
        if src and dst:
            try:
                src_idx = l.get("src_index")
                dst_idx = l.get("dst_index")
                s_sock = None
                d_sock = None

                if src_idx is not None and isinstance(src_idx, int) and 0 <= src_idx < len(src.outputs):
                    s_sock = src.outputs[src_idx]
                else: s_sock = src.outputs.get(l.get("src_sock"))
                
                if dst_idx is not None and isinstance(dst_idx, int) and 0 <= dst_idx < len(dst.inputs):
                    d_sock = dst.inputs[dst_idx]
                else: d_sock = dst.inputs.get(l.get("dst_sock"))

                if not s_sock and src.outputs: s_sock = src.outputs[0]
                if not d_sock and dst.inputs: d_sock = dst.inputs[0]

                if s_sock and d_sock:
                    node_tree.links.new(s_sock, d_sock)
            except Exception as e:
                print(f"Link Error: {e}")

    # 5. Global Auto Layout Trigger
    # Only if absolutely no valid locations were found (e.g. pure logic graph)
    if not has_valid_location and len(created_nodes) > 1:
        apply_hierarchical_layout(node_tree, created_nodes)

def build_full_structure(main_tree, json_content, is_replace=True):
    try: full_data = json.loads(json_content)
    except: return "JSON Format Error"
    
    conversion_log = []
    deps = full_data.get("dependencies", {})
    
    for group_name, group_data in deps.items():
        tree_type = group_data.get("type_id", "GeometryNodeTree") 
        if group_name in bpy.data.node_groups:
            target_group = bpy.data.node_groups[group_name]
            if target_group.bl_idname != tree_type:
                target_group.name = group_name + "_backup"
                target_group = bpy.data.node_groups.new(group_name, tree_type)
            else:
                target_group.clear()
                target_group.interface.clear()
        else:
            target_group = bpy.data.node_groups.new(group_name, tree_type)
        rebuild_interface(target_group, group_data.get("interface", []))
        build_single_tree(target_group, group_data, clear=True)

    root_data = full_data.get("root", {})
    if not is_replace:
        for n in main_tree.nodes: n.select = False
        build_single_tree(main_tree, root_data, offset=(200, -200), clear=False, conversion_log=conversion_log)
    else:
        build_single_tree(main_tree, root_data, clear=True, conversion_log=conversion_log)

    msg = "Build Success"
    if conversion_log:
        unique_logs = list(set(conversion_log))
        details = ", ".join(unique_logs)
        msg += f" | Converted: [{details}]"
    return msg

# ==============================================================================
# UI & Registration
# ==============================================================================

class GN_OT_Serialize(bpy.types.Operator):
    bl_idname = "gn.serialize"
    bl_label = "序列化节点"
    bl_options = {'REGISTER'} 
    mode: bpy.props.EnumProperty(items=[('ALL', "All", ""), ('SELECTED', "Selected", "")], default='ALL') # type: ignore

    def execute(self, context):
        space = context.space_data
        if not space.edit_tree: return {'CANCELLED'}
        is_compact = context.scene.gn_compact_mode
        try:
            json_str = json.dumps(
                serialize_recursive(space.edit_tree, self.mode == 'SELECTED', is_compact=is_compact),
                indent=2, ensure_ascii=False
            )
            context.window_manager.clipboard = json_str
            self.report({'INFO'}, "Copied to Clipboard")
        except Exception as e:
            self.report({'ERROR'}, str(e))
        return {'FINISHED'}

class GN_OT_Build(bpy.types.Operator):
    bl_idname = "gn.build"
    bl_label = "构建节点"
    bl_options = {'REGISTER', 'UNDO'}
    mode: bpy.props.EnumProperty(items=[('REPLACE', "Replace", ""), ('APPEND', "Append", "")], default='REPLACE') # type: ignore

    def execute(self, context):
        space = context.space_data
        if not space.edit_tree: return {'CANCELLED'}
        msg = build_full_structure(space.edit_tree, context.window_manager.clipboard, self.mode == 'REPLACE')
        if "Success" in msg: self.report({'INFO'}, msg)
        else: self.report({'ERROR'}, msg)
        return {'FINISHED'}

class GN_PT_Panel(bpy.types.Panel):
    bl_label = "GeoNeural v2.5.2 (Smart-Frame)"
    bl_idname = "GN_PT_main"
    bl_space_type = 'NODE_EDITOR' 
    bl_region_type = 'UI'
    bl_category = 'GeoNeural'

    def draw(self, context):
        layout = self.layout
        space = context.space_data
        
        if space.edit_tree:
            icon = 'NODETREE'
            if space.edit_tree.bl_idname == 'ShaderNodeTree': icon = 'SHADING_RENDERED'
            elif space.edit_tree.bl_idname == 'GeometryNodeTree': icon = 'GEOMETRY_NODES'
            elif space.edit_tree.bl_idname == 'CompositorNodeTree': icon = 'NODE_COMPOSITING'
            layout.label(text=f"Mode: {space.edit_tree.name}", icon=icon)
        else:
            layout.label(text="Mode: No Tree", icon='ERROR')

        box = layout.box()
        box.label(text="To AI (Copy):")
        box.prop(context.scene, "gn_compact_mode", text="AI Compact Mode")
        row = box.row()
        row.operator("gn.serialize", text="All").mode = 'ALL'
        row.operator("gn.serialize", text="Selected").mode = 'SELECTED'
        
        box2 = layout.box()
        box2.label(text="From AI (Build):")
        row2 = box2.row()
        row2.operator("gn.build", text="Append").mode = 'APPEND'
        row2.operator("gn.build", text="Replace (Auto Layout)").mode = 'REPLACE'

classes = (GN_OT_Serialize, GN_OT_Build, GN_PT_Panel)

def register():
    bpy.types.Scene.gn_compact_mode = bpy.props.BoolProperty(default=False)
    for cls in classes: bpy.utils.register_class(cls)

def unregister():
    for cls in classes: bpy.utils.unregister_class(cls)
    del bpy.types.Scene.gn_compact_mode

if __name__ == "__main__":
    register()