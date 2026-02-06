bl_info = {
    "name": "GeoNeural Bridge (v4.0.3 ID Shift Fix)",
    "author": "Dev_Nodes_V5",
    "version": (4, 0, 3),
    "blender": (4, 0, 0),
    "location": "Node Editor > Sidebar > GeoNeural",
    "description": "修复重复区域中因删除接口导致的ID漂移(ID Shift)引发的连线错乱问题。",
    "category": "Node",
}

import bpy
import json
import re
import os

try:
    from . import node_mappings
except ImportError:
    pass

# ==============================================================================
# 1. 通用工具
# ==============================================================================

def clean_data(value):
    """深度清理数据"""
    if value is None: return None
    if isinstance(value, bpy.types.ID): return value.name
    if isinstance(value, (int, float, str, bool)):
        if isinstance(value, float): return round(value, 4)
        return value
    if hasattr(value, "to_list"): return [clean_data(x) for x in value.to_list()]
    if hasattr(value, "to_tuple"): return [clean_data(x) for x in value.to_tuple()]
    if hasattr(value, "__len__") and not isinstance(value, (str, dict)):
        return [clean_data(x) for x in value]
    if isinstance(value, dict): return {k: clean_data(v) for k, v in value.items()}
    return None

def extract_and_clean_json(text):
    if not text: return "{}"
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1: text = text[start : end + 1]
    pattern = r'("[^"\\]*(?:\\.[^"\\]*)*")|(\/\/.*|\/\*[\s\S]*?\*\/)'
    text = re.sub(pattern, lambda m: "" if m.group(2) else m.group(1), text)
    return re.sub(r',\s*([\]}])', r'\1', text)

# ==============================================================================
# 2. 复杂数据序列化
# ==============================================================================

def serialize_color_ramp(ramp):
    if not ramp: return None
    return {
        "color_mode": ramp.color_mode,
        "hue_interpolation": ramp.hue_interpolation,
        "interpolation": ramp.interpolation,
        "elements": [{"alpha": round(e.alpha, 4), "position": round(e.position, 4), "color": [round(c, 4) for c in e.color]} for e in ramp.elements]
    }

def build_color_ramp(ramp_obj, data):
    if not data or not ramp_obj: return
    try:
        ramp_obj.color_mode = data.get("color_mode", "RGB")
        ramp_obj.hue_interpolation = data.get("hue_interpolation", "NEAR")
        ramp_obj.interpolation = data.get("interpolation", "LINEAR")
        elems = data.get("elements", [])
        while len(ramp_obj.elements) < len(elems): ramp_obj.elements.new(1.0)
        while len(ramp_obj.elements) > len(elems): ramp_obj.elements.remove(ramp_obj.elements[-1])
        for i, e in enumerate(elems):
            ramp_obj.elements[i].alpha = e.get("alpha", 1.0)
            ramp_obj.elements[i].position = e.get("position", 0.0)
            ramp_obj.elements[i].color = e.get("color", (1,1,1,1))
    except: pass

def serialize_curve_mapping(curve):
    if not curve: return None
    data = {"curves": []}
    for c in curve.curves:
        pts = [{"location": [round(p.location[0], 4), round(p.location[1], 4)], "handle_type": p.handle_type} for p in c.points]
        data["curves"].append({"points": pts})
    return data

def build_curve_mapping(curve_obj, data):
    if not data or not curve_obj: return
    try:
        for i, c_data in enumerate(data.get("curves", [])):
            if i >= len(curve_obj.curves): break
            curve = curve_obj.curves[i]
            pts = c_data.get("points", [])
            for j, p_data in enumerate(pts):
                if j < len(curve.points):
                    p = curve.points[j]
                    if "location" in p_data: p.location = p_data["location"]
                    p.handle_type = p_data.get("handle_type", 'AUTO')
            curve.update()
    except: pass

def serialize_image_user(img_user):
    if not img_user: return None
    return {
        "frame_duration": img_user.frame_duration,
        "frame_start": img_user.frame_start,
        "frame_offset": img_user.frame_offset,
        "use_cyclic": img_user.use_cyclic,
        "use_auto_refresh": img_user.use_auto_refresh
    }

def build_image_user(img_user_obj, data):
    if not data or not img_user_obj: return
    try:
        img_user_obj.frame_duration = data.get("frame_duration", 1)
        img_user_obj.frame_start = data.get("frame_start", 1)
        img_user_obj.frame_offset = data.get("frame_offset", 0)
        img_user_obj.use_cyclic = data.get("use_cyclic", False)
        img_user_obj.use_auto_refresh = data.get("use_auto_refresh", True)
    except: pass

# ==============================================================================
# 3. 核心：接口过滤与管理
# ==============================================================================

ZONE_INPUT_TYPES = {'GeometryNodeRepeatInput', 'GeometryNodeSimulationInput', 'GeometryNodeForeachGeometryElementInput'}
ZONE_TYPES = ZONE_INPUT_TYPES.union({'GeometryNodeRepeatOutput', 'GeometryNodeSimulationOutput', 'GeometryNodeForeachGeometryElementOutput', 'GeometryNodeRepeat', 'GeometryNodeSimulation'})

# 定义不需要序列化的内置端口名称
BUILTIN_SOCKETS = {
    "Geometry", "几何数据", 
    "Iteration", "Iterations", 
    "Delta Time"
}

def serialize_interface(node_tree_or_node):
    interface_data = []
    
    # 场景 A: 普通节点组
    if hasattr(node_tree_or_node, "interface") and hasattr(node_tree_or_node.interface, "items_tree"):
        for item in node_tree_or_node.interface.items_tree:
            if item.item_type == 'SOCKET':
                socket_info = {
                    "name": item.name,
                    "in_out": item.in_out,
                    "socket_type": item.socket_type,
                }
                if item.in_out == 'INPUT':
                    try:
                        if hasattr(item, "default_value"): socket_info["default_value"] = clean_data(item.default_value)
                        if hasattr(item, "min_value"): socket_info["min_value"] = clean_data(item.min_value)
                        if hasattr(item, "max_value"): socket_info["max_value"] = clean_data(item.max_value)
                    except: pass
                interface_data.append(socket_info)
                
    # 场景 B: 区域输入节点
    elif node_tree_or_node.bl_idname in ZONE_INPUT_TYPES:
        for socket in node_tree_or_node.outputs:
            if socket.bl_idname == "NodeSocketVirtual": continue
            if socket.name in BUILTIN_SOCKETS: continue

            socket_info = {
                "name": socket.name,
                "in_out": "INPUT",
                "socket_type": socket.bl_idname,
                "default_value": None
            }
            if socket.name in node_tree_or_node.inputs:
                inp = node_tree_or_node.inputs[socket.name]
                if hasattr(inp, "default_value"):
                    try: socket_info["default_value"] = clean_data(inp.default_value)
                    except: pass
            interface_data.append(socket_info)
            
        if node_tree_or_node.bl_idname == 'GeometryNodeRepeatInput':
             if 'Iterations' in node_tree_or_node.inputs:
                 inp = node_tree_or_node.inputs['Iterations']
                 interface_data.append({
                     "name": "Iterations",
                     "in_out": "SPECIAL_INPUT",
                     "socket_type": "NodeSocketInt",
                     "default_value": clean_data(inp.default_value)
                 })
    return interface_data

def rebuild_interface_for_group(target_group, interface_data):
    if not interface_data or not hasattr(target_group, "interface"): return
    target_group.interface.clear()
    type_map = node_mappings.get_socket_type_map()
    for item in interface_data:
        try:
            name = item.get("name", "Socket")
            raw_type = item.get("bl_socket_type", item.get("socket_type", "NodeSocketFloat"))
            sType = type_map.get(raw_type, raw_type)
            if "NodeSocket" not in sType: sType = "NodeSocketFloat"
            io = item.get("in_out", "INPUT")
            socket_item = target_group.interface.new_socket(name, in_out=io, socket_type=sType)
            if io == 'INPUT' and "default_value" in item and item["default_value"] is not None: 
                try: socket_item.default_value = item["default_value"]
                except: pass
        except: pass

def rebuild_zone_items(input_node, output_node, interface_data):
    """使用 Data API 重建 Zone 接口 (v4.0.3 保持不变)"""
    if not interface_data: return
    target_collection = None
    if hasattr(output_node, "repeat_items"): target_collection = output_node.repeat_items
    elif hasattr(output_node, "state_items"): target_collection = output_node.state_items
    
    if target_collection is None: return

    for item in interface_data:
        name = item.get("name")
        in_out = item.get("in_out")
        
        if name == "Iterations" or in_out == "SPECIAL_INPUT":
            if item.get("default_value") is not None and "Iterations" in input_node.inputs:
                try: input_node.inputs["Iterations"].default_value = item["default_value"]
                except: pass
            continue
            
        if name in BUILTIN_SOCKETS: continue 
        
        exists = any(r_item.name == name for r_item in target_collection)
        if exists: continue

        raw_type = item.get("bl_socket_type", item.get("socket_type", "NodeSocketFloat"))
        enum_type = node_mappings.get_zone_api_type(raw_type)

        try:
            new_item = target_collection.new(enum_type, name)
            if new_item.name != name: new_item.name = name
        except: pass

    if output_node.id_data: output_node.id_data.update_tag()
    
    for item in interface_data:
        name = item.get("name")
        val = item.get("default_value")
        if name not in BUILTIN_SOCKETS and val is not None and name in input_node.inputs:
            try: input_node.inputs[name].default_value = val
            except: pass

def auto_pair_and_rebuild_zones(node_map, data):
    ZONE_PAIRS = [
        ('GeometryNodeRepeatInput', 'GeometryNodeRepeatOutput'),
        ('GeometryNodeSimulationInput', 'GeometryNodeSimulationOutput'),
        ('GeometryNodeForeachGeometryElementInput', 'GeometryNodeForeachGeometryElementOutput'),
    ]
    for in_type, out_type in ZONE_PAIRS:
        inputs = [n for n in node_map.values() if n.bl_idname == in_type]
        outputs = [n for n in node_map.values() if n.bl_idname == out_type]
        if len(inputs) == 1 and len(outputs) == 1:
            input_node = inputs[0]
            output_node = outputs[0]
            try: input_node.pair_with_output(output_node)
            except: pass
            original_json_name = None
            for key, val in node_map.items():
                if val == input_node: original_json_name = key; break
            if original_json_name:
                n_data = next((n for n in data.get("nodes", []) if n.get("name") == original_json_name), None)
                if n_data and "zone_interface" in n_data:
                    rebuild_zone_items(input_node, output_node, n_data["zone_interface"])

# ==============================================================================
# 4. 自动布局
# ==============================================================================
def apply_hierarchical_layout(node_tree, new_nodes):
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
        current = queue.pop(0)
        for child in children[current]:
            if levels[child] < levels[current] + 1:
                levels[child] = levels[current] + 1
                if child not in visited: queue.append(child)
            if levels[child] > 200: continue
    level_groups = {}
    for name, lvl in levels.items():
        if lvl not in level_groups: level_groups[lvl] = []
        level_groups[lvl].append(name)
    X_STEP, Y_STEP = 300, -220
    for lvl in sorted(level_groups.keys()):
        group = level_groups[lvl]
        if lvl > 0: group.sort(key=lambda n: sum(node_map[p].location.y for p in parents[n]) / len(parents[n]) if parents[n] else 0, reverse=True)
        start_y = ((len(group) - 1) * abs(Y_STEP)) / 2
        for i, name in enumerate(group):
            node_map[name].location = (lvl * X_STEP, start_y + (i * Y_STEP))

# ==============================================================================
# 5. 核心序列化与构建
# ==============================================================================

def serialize_single_tree(node_tree, nodes_to_process=None, is_compact=False):
    if nodes_to_process is None: nodes_to_process = node_tree.nodes
    data = {"tree_type": node_tree.bl_idname, "nodes": [], "links": []}
    valid_names = {n.name for n in nodes_to_process}
    ALWAYS_EXCLUDE = {'rna_type', 'node_tree', 'inputs', 'outputs', 'interface', 'dimensions', 'is_active_output'}
    COMPACT_EXCLUDE = {'name', 'location', 'width', 'height', 'select', 'location_absolute', 'warning_propagation', 'color_tag', 'width_hidden', 'internal_links', 'color', 'use_custom_color'}
    NO_DEFAULT_VALUE_SOCKETS = {'NodeSocketGeometry', 'NodeSocketShader', 'NodeSocketVirtual'}

    for node in nodes_to_process:
        node_data = {
            "name": node.name,
            "type": node.bl_idname,
            "params": {}, 
            "inputs": {}
        }
        for prop in node.bl_rna.properties.keys():
            if prop in ALWAYS_EXCLUDE: continue
            if prop == 'internal_links': continue 
            if is_compact:
                if prop in COMPACT_EXCLUDE: continue
                if prop.startswith(('bl_', 'show_', '_')): continue
                if prop not in ['label', 'mute'] and prop not in node_mappings.get_node_info(node.bl_idname).get("rna_properties", {}): pass
            try:
                val = getattr(node, prop, None)
                if isinstance(val, bpy.types.ColorRamp): node_data["params"][prop] = {"__type__": "ColorRamp", "data": serialize_color_ramp(val)}
                elif isinstance(val, bpy.types.CurveMapping): node_data["params"][prop] = {"__type__": "CurveMapping", "data": serialize_curve_mapping(val)}
                elif isinstance(val, bpy.types.ImageUser): node_data["params"][prop] = {"__type__": "ImageUser", "data": serialize_image_user(val)}
                else:
                    safe_val = clean_data(val)
                    if safe_val is not None: node_data["params"][prop] = safe_val
            except: pass

        if node.bl_idname == 'GeometryNodeRepeat':
            node_data["is_zone"] = True
            node_data["zone_interface"] = serialize_interface(node)
            if node.node_tree: node_data["internal_tree"] = serialize_single_tree(node.node_tree, None, is_compact)
        elif node.bl_idname in ZONE_INPUT_TYPES:
            node_data["is_zone"] = True
            node_data["zone_interface"] = serialize_interface(node)

        if not is_compact: node_data["socket_props"] = {}
        for s in node.inputs:
            if not is_compact:
                s_props = {}
                if s.hide: s_props["hide"] = True
                if s.hide_value: s_props["hide_value"] = True
                if s_props: 
                    key = s.identifier if hasattr(s, "identifier") else s.name
                    node_data["socket_props"][key] = s_props
            if s.bl_idname in NO_DEFAULT_VALUE_SOCKETS: continue
            if hasattr(s, "enabled") and not s.enabled: continue
            if not s.is_linked:
                try:
                    if hasattr(s, "default_value"):
                        val = clean_data(s.default_value)
                        if val is not None:
                            key = s.identifier if hasattr(s, "identifier") else s.name
                            node_data["inputs"][key] = val
                except: pass
        
        if node.parent: node_data["parent"] = node.parent.name
        if not is_compact:
            node_data["location"] = [int(node.location.x), int(node.location.y)]
            if node.bl_idname == 'NodeFrame':
                node_data["width"] = node.width
                node_data["height"] = node.height
        if hasattr(node, "node_tree") and node.node_tree: node_data["node_tree_name"] = node.node_tree.name
        data["nodes"].append(node_data)

    for link in node_tree.links:
        if link.from_node.name in valid_names and link.to_node.name in valid_names:
            link_data = {
                "src": link.from_node.name, "src_sock": link.from_socket.name, "src_sock_id": link.from_socket.identifier,
                "dst": link.to_node.name, "dst_sock": link.to_socket.name, "dst_sock_id": link.to_socket.identifier
            }
            data["links"].append(link_data)
    return data

def serialize_recursive(start_tree, selected_only=False, is_compact=False):
    deps = {} 
    if selected_only: root_nodes = [n for n in start_tree.nodes if n.select]
    else: root_nodes = list(start_tree.nodes)
    root_data = serialize_single_tree(start_tree, root_nodes, is_compact=is_compact)
    trees_to_scan = set()
    for n in root_nodes:
        if hasattr(n, "node_tree") and n.node_tree: trees_to_scan.add(n.node_tree)
    scanned_trees = set()
    while trees_to_scan:
        current = trees_to_scan.pop()
        if current in scanned_trees: continue
        scanned_trees.add(current)
        t_data = serialize_single_tree(current, is_compact=is_compact)
        t_data["interface"] = serialize_interface(current)
        t_data["type_id"] = current.bl_idname 
        deps[current.name] = t_data
        for n in current.nodes:
            if hasattr(n, "node_tree") and n.node_tree and n.node_tree not in scanned_trees:
                trees_to_scan.add(n.node_tree)
    return { "version": "4.0.3", "compact": is_compact, "root": root_data, "dependencies": deps }

def smart_get_socket(node, name, identifier, is_output=False):
    """
    [v4.0.3] 智能端口查找
    解决 Repeat Zone 等节点 ID 漂移 (ID Shift) 导致连线错误的问题。
    """
    collection = node.outputs if is_output else node.inputs
    
    # 策略 1: 针对动态节点 (Zone/Group)，强制名称优先
    # 因为在 rebuild_zone_items 中我们是按名称重建的，而 ID (Item_x) 会根据 Blender 内部逻辑重排。
    # 如果源数据有 Item_0, Item_3 (Item_1/2被删)，重建后会变成 Item_0, Item_1。此时信 ID 必死。
    if node.bl_idname in ZONE_TYPES or node.bl_idname == 'GeometryNodeGroup':
        if name in collection: 
            return collection[name]
        # 如果名称找不到，再尝试 ID (防止改名情况，虽然在重建场景下名称应该匹配)
        for s in collection:
            if s.identifier == identifier: return s
    
    # 策略 2: 针对普通节点 (Math, Object Info)，ID 优先
    # 普通节点可能有相同名称的端口 (如某些 Addon 节点)，或者名称被用户改过，ID (如 "Value") 最稳。
    else:
        # 先试 ID
        for s in collection:
            if s.identifier == identifier: return s
        # 再试 Name
        if name in collection: 
            return collection[name]
            
    return None

def build_single_tree(node_tree, data, offset=(0,0), clear=False):
    if clear: node_tree.nodes.clear()
    node_map = {}
    created_nodes = []
    has_valid_location = False
    
    # PHASE 1: 创建节点
    for n_data in data.get("nodes", []):
        raw_type = n_data.get("type")
        n_name = n_data.get("name")
        n_type = node_mappings.resolve_node_id(raw_type)
        try: node = node_tree.nodes.new(type=n_type)
        except:
            try: node = node_tree.nodes.new(type=raw_type)
            except: print(f"Skip: {n_name}"); continue 

        node.name = n_name 
        node.select = True
        node_map[n_name] = node 
        created_nodes.append(node)
        
        params = n_data.get("params", {})
        loc = n_data.get("location_absolute", n_data.get("location", params.get("location")))
        if loc and isinstance(loc, list) and len(loc) == 2:
            node.location = (loc[0] + offset[0], loc[1] + offset[1])
            if loc[0] != 0 or loc[1] != 0: has_valid_location = True
        
        if node.bl_idname == 'NodeFrame':
            node.width = n_data.get("width", 100)
            node.height = n_data.get("height", 100)
            if "label" in params: node.label = params["label"]

        if n_data.get("is_zone") and "zone_interface" in n_data and node.bl_idname == 'GeometryNodeRepeat':
            rebuild_interface_for_group(node, n_data["zone_interface"])
            if "internal_tree" in n_data and node.node_tree:
                build_single_tree(node.node_tree, n_data["internal_tree"], clear=True)

    # PHASE 1.5: 修复 Zone 接口
    auto_pair_and_rebuild_zones(node_map, data)

    # PHASE 2: 属性
    for n_data in data.get("nodes", []):
        node = node_map.get(n_data.get("name"))
        if not node: continue
        node_info = node_mappings.get_node_info(node.bl_idname)
        schema_props = node_info.get("rna_properties", {})
        params = n_data.get("params", {})
        inputs_data = n_data.get("inputs", {})

        for k, v in params.items():
            if k in {"location", "width", "height"}: continue
            if isinstance(v, dict) and "__type__" in v:
                if v["__type__"] == "ColorRamp" and hasattr(node, k): build_color_ramp(getattr(node, k), v["data"])
                elif v["__type__"] == "CurveMapping" and hasattr(node, k): build_curve_mapping(getattr(node, k), v["data"])
                elif v["__type__"] == "ImageUser" and hasattr(node, k): build_image_user(getattr(node, k), v["data"])
                continue
            if hasattr(node, k):
                prop_def = schema_props.get(k)
                if prop_def and prop_def["type"] == "ENUM" and isinstance(v, str):
                    if node_mappings.validate_enum(k, v, prop_def):
                        try: setattr(node, k, v)
                        except: setattr(node, k, v.upper())
                    elif node_mappings.validate_enum(k, v.upper(), prop_def):
                        try: setattr(node, k, v.upper())
                        except: pass
                else:
                    try: setattr(node, k, v)
                    except: pass
            else:
                if k not in inputs_data: inputs_data[k] = v
        
        sock_map = {s.identifier: s for s in node.inputs}
        sock_map.update({s.name: s for s in node.inputs})

        for k, v in inputs_data.items():
            if k in sock_map:
                t = sock_map[k]
                try: 
                    if hasattr(t, "type") and t.type in {'OBJECT', 'COLLECTION', 'MATERIAL', 'IMAGE'} and isinstance(v, str):
                        if t.type == 'OBJECT': t.default_value = bpy.data.objects.get(v)
                        elif t.type == 'COLLECTION': t.default_value = bpy.data.collections.get(v)
                        elif t.type == 'MATERIAL': t.default_value = bpy.data.materials.get(v)
                        elif t.type == 'IMAGE': t.default_value = bpy.data.images.get(v)
                    else: t.default_value = v
                except: pass
        
        socket_props = n_data.get("socket_props", {})
        for k, props in socket_props.items():
            if k in sock_map:
                s = sock_map[k]
                if "hide" in props: s.hide = props["hide"]
                if "hide_value" in props: s.hide_value = props["hide_value"]

        if hasattr(node, "node_tree") and "node_tree_name" in n_data:
            nt = bpy.data.node_groups.get(n_data["node_tree_name"])
            if nt: node.node_tree = nt

    # PHASE 4: 连线 (v4.0.3 核心修复)
    for n_data in data.get("nodes", []):
        if "parent" in n_data and n_data["parent"] in node_map:
            node_map[n_data["name"]].parent = node_map[n_data["parent"]]
    if hasattr(node_tree, "update_tag"): node_tree.update_tag()

    for l in data.get("links", []):
        src = node_map.get(l.get("src"))
        dst = node_map.get(l.get("dst"))
        if src and dst:
            try:
                # 使用智能查找替代旧的 ID 优先逻辑
                src_sock = smart_get_socket(src, l.get("src_sock"), l.get("src_sock_id"), is_output=True)
                dst_sock = smart_get_socket(dst, l.get("dst_sock"), l.get("dst_sock_id"), is_output=False)
                
                if src_sock and dst_sock:
                    node_tree.links.new(src_sock, dst_sock)
            except: pass

    if not has_valid_location and len(created_nodes) > 1:
        apply_hierarchical_layout(node_tree, created_nodes)

def build_full_structure(main_tree, json_str, replace=True):
    try: data = json.loads(extract_and_clean_json(json_str))
    except Exception as e: return f"JSON 错误: {e}"
    for g_name, g_data in data.get("dependencies", {}).items():
        t_type = g_data.get("type_id", "GeometryNodeTree")
        grp = bpy.data.node_groups.get(g_name)
        if not grp: grp = bpy.data.node_groups.new(g_name, t_type)
        else: grp.clear()
        rebuild_interface_for_group(grp, g_data.get("interface", []))
        build_single_tree(grp, g_data, clear=True)
    root = data.get("root", data if "nodes" in data else {})
    if not replace:
        for n in main_tree.nodes: n.select = False
        build_single_tree(main_tree, root, offset=(200, -200), clear=False)
    else: build_single_tree(main_tree, root, clear=True)
    return "成功构建"

# ==============================================================================
# UI 注册
# ==============================================================================
class GN_OT_Serialize(bpy.types.Operator):
    bl_idname = "gn.serialize"
    bl_label = "序列化节点"
    bl_options = {'REGISTER'} 
    mode: bpy.props.EnumProperty(items=[('ALL', "全部", ""), ('SELECTED', "选中", "")], default='ALL')
    def execute(self, context):
        try:
            js = json.dumps(serialize_recursive(context.space_data.edit_tree, self.mode=='SELECTED', context.scene.gn_compact_mode), indent=2, ensure_ascii=False)
            context.window_manager.clipboard = js
            self.report({'INFO'}, "已复制到剪贴板")
        except Exception as e: self.report({'ERROR'}, str(e))
        return {'FINISHED'}

class GN_OT_Build(bpy.types.Operator):
    bl_idname = "gn.build"
    bl_label = "构建节点"
    bl_options = {'REGISTER', 'UNDO'}
    mode: bpy.props.EnumProperty(items=[('REPLACE', "替换", ""), ('APPEND', "追加", "")], default='REPLACE')
    def execute(self, context):
        space = context.space_data
        if not space.edit_tree: return {'CANCELLED'}
        msg = build_full_structure(space.edit_tree, context.window_manager.clipboard, self.mode == 'REPLACE')
        self.report({'INFO' if "成功" in msg else 'ERROR'}, msg)
        return {'FINISHED'}

class GN_PT_Panel(bpy.types.Panel):
    bl_label = "GeoNeural 节点助手 v4.0.3"
    bl_idname = "GN_PT_main"
    bl_space_type = 'NODE_EDITOR' 
    bl_region_type = 'UI'
    bl_category = 'GeoNeural'
    def draw(self, context):
        layout = self.layout
        try: 
            db_ok = node_mappings.load_db()
            layout.label(text="数据库已连接" if db_ok else "数据库缺失", icon='CHECKMARK' if db_ok else 'ERROR')
        except: layout.label(text="DB Error", icon='ERROR')
        box = layout.box()
        box.label(text="发送给 AI (复制):")
        box.prop(context.scene, "gn_compact_mode", text="紧凑模式")
        r = box.row()
        r.operator("gn.serialize", text="选中节点").mode = 'SELECTED'
        r.operator("gn.serialize", text="全部节点").mode = 'ALL'
        box2 = layout.box()
        box2.label(text="从 AI 接收 (粘贴):")
        r2 = box2.row()
        r2.operator("gn.build", text="追加").mode = 'APPEND'
        r2.operator("gn.build", text="替换").mode = 'REPLACE'

classes = (GN_OT_Serialize, GN_OT_Build, GN_PT_Panel)
def register():
    node_mappings.load_db()
    bpy.types.Scene.gn_compact_mode = bpy.props.BoolProperty(default=False)
    for c in classes: bpy.utils.register_class(c)
def unregister():
    for c in classes: bpy.utils.unregister_class(c)
    del bpy.types.Scene.gn_compact_mode

if __name__ == "__main__":
    register()