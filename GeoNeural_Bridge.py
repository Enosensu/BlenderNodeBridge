bl_info = {
    "name": "GeoNeural Bridge (v2.1.0)",
    "author": "Dev_Nodes_V5",
    "version": (2, 1, 0),
    "blender": (5, 0, 0),
    "location": "Node Editor > Sidebar > GeoNeural",
    "description": "Single-file edition: Smart AI Bridge with embedded mappings",
    "category": "Node",
}

import bpy
import json

# ==============================================================================
# 0. 内嵌映射数据库 (Embedded Mapping Database)
# ==============================================================================
# 这里包含了 Blender 5.0 常用节点的跨上下文转换规则。
# 由于是 Python 字典，你可以直接在这里修改或添加新的映射。

NODE_TRANSLATION_TABLE = {
    "GeometryNodeTree": {
        # --- Shader -> GeoNodes ---
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
        "ShaderNodeUVMap": "GeometryNodeInputNamedAttribute", # 通常用于UV
        "ShaderNodeObjectInfo": "GeometryNodeObjectInfo",
        "ShaderNodeAttribute": "GeometryNodeInputNamedAttribute",
        "ShaderNodeNormal": "GeometryNodeInputNormal"
    },
    
    "ShaderNodeTree": {
        # --- GeoNodes -> Shader ---
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
        # --- Universal -> Compositor ---
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
# 1. 工具：通用数据清洗
# ==============================================================================

def clean_data(value):
    """白名单清洗，确保 JSON 安全"""
    if value is None: return None
    if isinstance(value, (int, float, str, bool)):
        if isinstance(value, float): return round(value, 3)
        return value
    if hasattr(value, "to_list"): return [round(x, 3) for x in value.to_list()]
    if hasattr(value, "to_tuple"): return [round(x, 3) for x in value.to_tuple()]
    if isinstance(value, (list, tuple)): return [clean_data(x) for x in value]
    if isinstance(value, dict): return {k: clean_data(v) for k, v in value.items()}
    return None

# ==============================================================================
# 2. 核心逻辑：序列化
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

def serialize_single_tree(node_tree, nodes_to_process=None):
    if nodes_to_process is None: nodes_to_process = node_tree.nodes
    data = { "tree_type": node_tree.bl_idname, "nodes": [], "links": [] }
    valid_names = {n.name for n in nodes_to_process}
    GROUP_TYPES = {'GeometryNodeGroup', 'ShaderNodeGroup', 'CompositorNodeGroup'}

    for node in nodes_to_process:
        if node.bl_idname == 'NodeFrame': continue
        node_data = {
            "name": node.name,
            "type": node.bl_idname,
            "location": [int(node.location.x), int(node.location.y)],
            "params": {}, "inputs": {}
        }
        if node.bl_idname in GROUP_TYPES and node.node_tree:
            node_data["node_tree_name"] = node.node_tree.name

        for prop in node.bl_rna.properties.keys():
            if prop in {'rna_type', 'name', 'location', 'width', 'height', 'select', 'dimensions', 'color', 'inputs', 'outputs', 'node_tree'}: continue
            try:
                safe_val = clean_data(getattr(node, prop))
                if safe_val is not None: node_data["params"][prop] = safe_val
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
            data["links"].append({
                "src": link.from_node.name, "src_sock": link.from_socket.name,
                "dst": link.to_node.name, "dst_sock": link.to_socket.name
            })
    return data

def serialize_recursive(start_tree, selected_only=False):
    deps = {} 
    GROUP_TYPES = {'GeometryNodeGroup', 'ShaderNodeGroup', 'CompositorNodeGroup'}
    if selected_only: root_nodes = [n for n in start_tree.nodes if n.select]
    else: root_nodes = list(start_tree.nodes)
        
    root_data = serialize_single_tree(start_tree, root_nodes)
    trees_to_scan = set()
    for n in root_nodes:
        if n.bl_idname in GROUP_TYPES and n.node_tree: trees_to_scan.add(n.node_tree)

    scanned_trees = set()
    while trees_to_scan:
        current_tree = trees_to_scan.pop()
        if current_tree in scanned_trees: continue
        scanned_trees.add(current_tree)
        
        tree_def = serialize_single_tree(current_tree)
        tree_def["interface"] = serialize_interface(current_tree)
        tree_def["type_id"] = current_tree.bl_idname 
        deps[current_tree.name] = tree_def
        
        for n in current_tree.nodes:
            if n.bl_idname in GROUP_TYPES and n.node_tree:
                if n.node_tree not in scanned_trees: trees_to_scan.add(n.node_tree)

    return { "version": "2.1.0", "root": root_data, "dependencies": deps }

# ==============================================================================
# 3. 核心逻辑：智能构建 (双重尝试 + Undo)
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

def build_single_tree(node_tree, data, offset=(0,0), clear=False, conversion_log=None):
    if clear: node_tree.nodes.clear()
    node_map = {}
    cursor_x, cursor_y = offset
    
    target_tree_type = node_tree.bl_idname
    # 直接使用内嵌的字典
    translation_map = NODE_TRANSLATION_TABLE.get(target_tree_type, {})
    GROUP_TYPES = {'GeometryNodeGroup', 'ShaderNodeGroup', 'CompositorNodeGroup'}

    for n_data in data.get("nodes", []):
        original_type = n_data.get("type")
        target_type = original_type
        n_name = n_data.get("name")
        
        # 1. Check Mapping
        has_mapped = False
        if original_type in translation_map:
            target_type = translation_map[original_type]
            has_mapped = True
        
        # 2. Double-Try Strategy
        node = None
        created_type = None 
        
        # Try A: Mapped Type
        if has_mapped:
            try:
                node = node_tree.nodes.new(type=target_type)
                created_type = target_type
                if conversion_log is not None:
                    # 简化日志显示
                    s_old = original_type.replace("ShaderNode", "").replace("GeometryNode", "").replace("Input", "")
                    s_new = target_type.replace("ShaderNode", "").replace("GeometryNode", "").replace("Input", "")
                    conversion_log.append(f"{n_name}: {s_old}->{s_new}")
            except: pass

        # Try B: Original Type (Fallback)
        if node is None:
            try:
                node = node_tree.nodes.new(type=original_type)
                created_type = original_type
            except Exception as e:
                # print(f"Failed node {n_name}: {e}")
                continue 

        # 3. Setup
        if node:
            node.name = n_name
            node.select = True
            
            if created_type in GROUP_TYPES:
                tree_name = n_data.get("node_tree_name")
                if tree_name and tree_name in bpy.data.node_groups:
                    node.node_tree = bpy.data.node_groups[tree_name]

            loc = n_data.get("location", [0, 0])
            if loc == [0, 0]:
                node.location = (cursor_x, cursor_y)
                cursor_x += 250
                if cursor_x > 1000: cursor_x, cursor_y = 0, cursor_y - 200
            else:
                node.location = (loc[0] + offset[0], loc[1] + offset[1])

            for k, v in n_data.get("params", {}).items():
                if hasattr(node, k):
                    try: setattr(node, k, v)
                    except: pass
            
            for k, v in n_data.get("inputs", {}).items():
                if k in node.inputs:
                    try: node.inputs[k].default_value = v
                    except: pass
            
            node_map[node.name] = node

    # 4. Relink
    for l in data.get("links", []):
        src = node_map.get(l.get("src"))
        dst = node_map.get(l.get("dst"))
        if src and dst:
            try:
                s_sock = src.outputs.get(l.get("src_sock")) or (src.outputs[0] if src.outputs else None)
                d_sock = dst.inputs.get(l.get("dst_sock")) or (dst.inputs[0] if dst.inputs else None)
                if s_sock and d_sock: node_tree.links.new(s_sock, d_sock)
            except: pass

def build_full_structure(main_tree, json_content, is_replace=True):
    try:
        full_data = json.loads(json_content)
    except: return "JSON 格式错误"
    
    conversion_log = []

    deps = full_data.get("dependencies", {})
    for group_name, group_data in deps.items():
        if not bpy.data.node_groups.get(group_name):
            tree_type = group_data.get("type_id", "GeometryNodeTree") 
            new_group = bpy.data.node_groups.new(group_name, tree_type)
            rebuild_interface(new_group, group_data.get("interface", []))
            build_single_tree(new_group, group_data, clear=True)

    root_data = full_data.get("root", {})
    
    if not is_replace:
        for n in main_tree.nodes: n.select = False
        build_single_tree(main_tree, root_data, offset=(200, -200), clear=False, conversion_log=conversion_log)
    else:
        build_single_tree(main_tree, root_data, clear=True, conversion_log=conversion_log)

    msg = "构建成功"
    if conversion_log:
        unique_logs = list(set(conversion_log))
        details = ", ".join(unique_logs)
        msg += f" | 转换: [{details}]"
    return msg

# ==============================================================================
# UI & 注册
# ==============================================================================

class GN_OT_Serialize(bpy.types.Operator):
    bl_idname = "gn.serialize"
    bl_label = "序列化节点"
    bl_options = {'REGISTER'} 
    mode: bpy.props.EnumProperty(items=[('ALL', "All", ""), ('SELECTED', "Selected", "")], default='ALL') # type: ignore

    def execute(self, context):
        space = context.space_data
        if not space.edit_tree: return {'CANCELLED'}
        try:
            json_str = json.dumps(
                serialize_recursive(space.edit_tree, self.mode == 'SELECTED'),
                indent=2, ensure_ascii=False
            )
            context.window_manager.clipboard = json_str
            self.report({'INFO'}, f"数据已复制 (v2.1.0)")
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
        if "成功" in msg: self.report({'INFO'}, msg)
        else: self.report({'ERROR'}, msg)
        return {'FINISHED'}

class GN_PT_Panel(bpy.types.Panel):
    bl_label = "GeoNeural v2.1"
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
        box.label(text="To AI (复制):")
        row = box.row()
        row.operator("gn.serialize", text="全部", icon='COPYDOWN').mode = 'ALL'
        row.operator("gn.serialize", text="选中", icon='RESTRICT_SELECT_OFF').mode = 'SELECTED'
        
        box2 = layout.box()
        box2.label(text="From AI (构建):")
        row2 = box2.row()
        row2.operator("gn.build", text="追加", icon='ADD').mode = 'APPEND'
        row2.operator("gn.build", text="覆盖", icon='TRASH').mode = 'REPLACE'

classes = (GN_OT_Serialize, GN_OT_Build, GN_PT_Panel)

def register():
    for cls in classes: bpy.utils.register_class(cls)
def unregister():
    for cls in classes: bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()