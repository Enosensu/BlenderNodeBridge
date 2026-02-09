bl_info = {
    "name": "GeoNeural Bridge (v5.13.19 Restored & Enhanced)",
    "author": "Dev_Nodes_V5",
    "version": (5, 13, 19),
    "blender": (4, 0, 0),
    "location": "Node Editor > Sidebar > GeoNeural",
    "description": "集大成版本：恢复自动布局与调试系统，保留运算与捕获节点的核心修复。",
    "category": "Node",
}

import bpy
import json
import re
import os
import traceback
import mathutils

try:
    from . import node_mappings
except ImportError:
    pass

# ==============================================================================
# 0. 调试探针 (Restored from v5.13.16)
# ==============================================================================

class DebugUtils:
    @staticmethod
    def log(context, message):
        if getattr(context.scene, "gn_debug_mode", False):
            print(f"[GN DEBUG] {message}")

    @staticmethod
    def inspect_capture_node(node, phase="UNKNOWN"):
        print(f"\n--- [GN DEBUG] INSPECT: {node.name} ({phase}) ---")
        if hasattr(node, "capture_items"):
            print(f"  [COLLECTION] capture_items count: {len(node.capture_items)}")
            for i, item in enumerate(node.capture_items):
                d_type = getattr(item, "data_type", "UNKNOWN")
                print(f"    Item #{i}: name='{item.name}', data_type='{d_type}'")
        else:
            print("  [COLLECTION] capture_items NOT FOUND")
        print("------------------------------------------------\n")

# ==============================================================================
# 1. 基础工具集
# ==============================================================================

class DataUtils:
    @staticmethod
    def robust_json_load(text):
        if not text: return {}
        if "```" in text:
            pattern = r"```json(.*?)```|```(.*?)```"
            match = re.search(pattern, text, re.DOTALL)
            if match: text = match.group(1) if match.group(1) else match.group(2)
        pattern = r'("[^"\\]*(?:\\.[^"\\]*)*")|(\/\/.*|\/\*[\s\S]*?\*\/)'
        text = re.sub(pattern, lambda m: m.group(1) if m.group(1) else "", text)
        text = re.sub(r',(\s*[}\]])', r'\1', text)
        try: return json.loads(text)
        except: return None

    @staticmethod
    def clean_data(value):
        if value is None: return None
        if isinstance(value, bpy.types.ID): return value.name
        if isinstance(value, (int, float, str, bool)):
            if isinstance(value, float): return round(value, 4)
            return value
        if hasattr(value, "to_list"): return [DataUtils.clean_data(x) for x in value.to_list()]
        if hasattr(value, "to_tuple"): return [DataUtils.clean_data(x) for x in value.to_tuple()]
        if hasattr(value, "__len__") and not isinstance(value, (str, dict)):
            return [DataUtils.clean_data(x) for x in value]
        if isinstance(value, dict): return {k: DataUtils.clean_data(v) for k, v in value.items()}
        return None

class BlenderJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        try:
            if hasattr(obj, "to_list"): return [round(x, 4) for x in obj.to_list()]
            if hasattr(obj, "to_tuple"): return [round(x, 4) for x in obj.to_tuple()]
            if hasattr(obj, "__len__") and not isinstance(obj, (str, dict, bytes)):
                 try: return [x for x in obj]
                 except: pass
            if hasattr(obj, "name"): return obj.name
        except: return str(obj)
        return super().default(obj)

# ==============================================================================
# 2. 复杂数据处理器
# ==============================================================================

class SpecialHandlers:
    ZONE_INPUTS = {'GeometryNodeRepeatInput', 'GeometryNodeSimulationInput', 'GeometryNodeForeachGeometryElementInput'}
    ZONE_PAIRS = [
        ('GeometryNodeRepeatInput', 'GeometryNodeRepeatOutput'),
        ('GeometryNodeSimulationInput', 'GeometryNodeSimulationOutput'),
        ('GeometryNodeForeachGeometryElementInput', 'GeometryNodeForeachGeometryElementOutput')
    ]
    BUILTIN_SOCKETS = {"Geometry", "几何数据", "Iteration", "Iterations", "Delta Time"}

    @staticmethod
    def serialize_color_ramp(ramp):
        if not ramp: return None
        return {
            "color_mode": ramp.color_mode, "hue_interpolation": ramp.hue_interpolation,
            "interpolation": ramp.interpolation,
            "elements": [{"alpha": round(e.alpha, 4), "pos": round(e.position, 4), "color": [round(c, 4) for c in e.color]} for e in ramp.elements]
        }

    @staticmethod
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
                ramp_obj.elements[i].position = e.get("pos", e.get("position", 0.0))
                ramp_obj.elements[i].color = e.get("color", (1,1,1,1))
        except: pass

    @staticmethod
    def rebuild_zone_interface(output_node, interface_data):
        if not interface_data: return
        target_collection = getattr(output_node, "repeat_items", getattr(output_node, "state_items", None))
        if target_collection is None: return
        existing = {item.name for item in target_collection}
        for item in interface_data:
            name = item.get("name")
            if name in SpecialHandlers.BUILTIN_SOCKETS or name in existing: continue
            raw_type = item.get("socket_type", "NodeSocketFloat")
            api_type = node_mappings.get_zone_api_type(raw_type)
            try: target_collection.new(api_type, name)
            except: pass
        if output_node.id_data: output_node.id_data.update_tag()

    @staticmethod
    def get_base_name(name):
        return re.sub(r"[._]\d+$", "", name)

# ==============================================================================
# 3. 序列化引擎
# ==============================================================================

class SerializationEngine:
    def __init__(self, tree, context, selected_only=False, compact=False):
        self.tree = tree
        self.context = context
        self.selected_only = selected_only
        self.compact = compact
        self.nodes_to_process = [n for n in tree.nodes if n.select] if selected_only else list(tree.nodes)
        self.node_socket_maps = {} 

    def execute(self):
        self._precalculate_visual_names(self.tree)
        return self._serialize_recursive(self.tree)

    def _precalculate_visual_names(self, current_tree):
        for node in current_tree.nodes:
            self.node_socket_maps[node.name] = {"inputs": {}, "outputs": {}}
            visible_inputs = [s for s in node.inputs if getattr(s, "enabled", True) and not s.hide]
            base_counters = {}
            for s in visible_inputs:
                base = SpecialHandlers.get_base_name(s.name)
                base_counters[base] = base_counters.get(base, 0) + 1
                visual_name = f"{base}_{base_counters[base]:03d}"
                self.node_socket_maps[node.name]["inputs"][s.identifier] = visual_name
            visible_outputs = [s for s in node.outputs if getattr(s, "enabled", True) and not s.hide]
            base_counters_out = {}
            for s in visible_outputs:
                base = SpecialHandlers.get_base_name(s.name)
                base_counters_out[base] = base_counters_out.get(base, 0) + 1
                visual_name = f"{base}_{base_counters_out[base]:03d}"
                self.node_socket_maps[node.name]["outputs"][s.identifier] = visual_name

    def _calculate_absolute_location(self, node):
        curr = node
        abs_x, abs_y = 0.0, 0.0
        while curr:
            abs_x += curr.location.x
            abs_y += curr.location.y
            curr = curr.parent
        return [round(abs_x, 4), round(abs_y, 4)]

    def _serialize_node(self, node):
        if self.context.scene.gn_debug_mode and node.bl_idname == 'GeometryNodeCaptureAttribute':
            DebugUtils.inspect_capture_node(node, "PRE-SERIALIZE")

        d = {"name": node.name, "type": node.bl_idname, "params": {}, "inputs": {}}
        ALWAYS_EXCLUDE = {'rna_type', 'node_tree', 'inputs', 'outputs', 'interface', 'dimensions', 'is_active_output'}
        COMPACT_EXCLUDE = {
            'location', 'location_absolute', 'width', 'height', 
            'color', 'use_custom_color', 'select', 'color_tag'
        }

        for prop in node.bl_rna.properties.keys():
            if prop in ALWAYS_EXCLUDE: continue
            if self.compact and prop in COMPACT_EXCLUDE: continue

            # [Capture Bypass]
            if node.bl_idname == 'GeometryNodeCaptureAttribute' and prop in {'data_type', 'capture_items'}: 
                continue

            try:
                val = getattr(node, prop)
                if isinstance(val, bpy.types.ColorRamp):
                    d["params"][prop] = {"__type__": "ColorRamp", "data": SpecialHandlers.serialize_color_ramp(val)}
                elif isinstance(val, (int, float, str, bool, list, mathutils.Vector, mathutils.Color)):
                    safe_val = DataUtils.clean_data(val)
                    if safe_val is not None: d["params"][prop] = safe_val
            except: pass

        if node.bl_idname == 'GeometryNodeCaptureAttribute':
            capture_items_data = []
            if hasattr(node, "capture_items"):
                for item in node.capture_items:
                    d_type = getattr(item, "data_type", "FLOAT")
                    capture_items_data.append({"name": item.name, "data_type": d_type})
            d["params"]["capture_items_data"] = capture_items_data

        if node.bl_idname in SpecialHandlers.ZONE_INPUTS:
            d["is_zone"] = True
            d["zone_interface"] = [{"name": o.name, "socket_type": o.bl_idname} for o in node.outputs if o.bl_idname != "NodeSocketVirtual" and o.name not in SpecialHandlers.BUILTIN_SOCKETS]

        input_map = self.node_socket_maps.get(node.name, {}).get("inputs", {})
        for inp in node.inputs:
            if not inp.is_linked and hasattr(inp, "default_value"):
                val = DataUtils.clean_data(inp.default_value)
                if val is not None:
                    key = input_map.get(inp.identifier, inp.name)
                    d["inputs"][key] = val
        
        if not self.compact:
            d["location"] = [int(node.location.x), int(node.location.y)]
            d["location_absolute"] = self._calculate_absolute_location(node)
            if node.bl_idname == 'NodeFrame': d["width"], d["height"] = node.width, node.height
            d["socket_props"] = {}
            for s in node.inputs:
                s_props = {}
                if s.hide: s_props["hide"] = True
                if s.hide_value: s_props["hide_value"] = True
                if s_props:
                    key = input_map.get(s.identifier, s.name)
                    d["socket_props"][key] = s_props
        
        if node.parent: d["parent"] = node.parent.name
        return d

    def _serialize_recursive(self, current_tree):
        nodes = self.nodes_to_process if current_tree == self.tree else list(current_tree.nodes)
        data = {"tree_type": current_tree.bl_idname, "nodes": [], "links": []}
        valid_names = {n.name for n in nodes}

        for node in nodes:
            node_data = self._serialize_node(node)
            data["nodes"].append(node_data)
            if hasattr(node, "node_tree") and node.node_tree:
                node_data["node_tree_name"] = node.node_tree.name

        for link in current_tree.links:
            if link.from_node.name in valid_names and link.to_node.name in valid_names:
                src_map = self.node_socket_maps.get(link.from_node.name, {}).get("outputs", {})
                dst_map = self.node_socket_maps.get(link.to_node.name, {}).get("inputs", {})
                
                src_sock_name = src_map.get(link.from_socket.identifier, link.from_socket.name)
                dst_sock_name = dst_map.get(link.to_socket.identifier, link.to_socket.name)

                data["links"].append({
                    "src": link.from_node.name, "src_sock": src_sock_name, "src_id": link.from_socket.identifier,
                    "dst": link.to_node.name, "dst_sock": dst_sock_name, "dst_id": link.to_socket.identifier
                })
        return data

# ==============================================================================
# 4. 构建引擎 (Construction Engine)
# ==============================================================================

class ConstructionEngine:
    def __init__(self, tree, context):
        self.tree = tree
        self.context = context
        self.node_map = {}
        self.created_nodes = []
        self.has_valid_location = False

    def build(self, json_data, clear=False, offset=(0,0)):
        if clear: self.tree.nodes.clear()
        nodes_data = json_data.get("nodes", [])
        if "root" in json_data and isinstance(json_data["root"], dict):
            nodes_data = json_data["root"].get("nodes", [])

        links_data = json_data.get("links", []) or json_data.get("root", {}).get("links", [])

        for n_data in nodes_data: self._create_node(n_data)
        for n_data in nodes_data: self._set_parent(n_data)
        for n_data in nodes_data: self._configure_transform_and_props(n_data, offset)
        self._handle_zones(nodes_data)
        self._link_nodes(links_data)
        
        # [RESTORED] LayoutEngine 调用逻辑
        if not self.has_valid_location and len(self.created_nodes) > 1:
            LayoutEngine.apply(self.tree, self.created_nodes)
            
        if self.created_nodes:
            self.tree.nodes.active = self.created_nodes[-1]

    def _create_node(self, n_data):
        raw_type = n_data.get("type")
        name = n_data.get("name")
        final_type = node_mappings.resolve_node_id(raw_type)
        
        node = None
        try: node = self.tree.nodes.new(final_type)
        except: pass
        if node is None and final_type != raw_type:
            try: node = self.tree.nodes.new(raw_type)
            except: pass
        if node is None:
            if "Proximity" in raw_type and "Geometry" in raw_type:
                try: node = self.tree.nodes.new("GeometryNodeProximity")
                except: pass
        if node is None:
            node = self.tree.nodes.new("NodeFrame")
            node.label = f"MISSING: {raw_type}"
            node.use_custom_color = True; node.color = (1.0, 0.0, 0.0)

        node.name = name; node.select = True
        self.node_map[name] = node; self.created_nodes.append(node)

    def _set_parent(self, n_data):
        if "parent" in n_data and n_data["parent"] in self.node_map:
            node = self.node_map.get(n_data["name"])
            if node: node.parent = self.node_map[n_data["parent"]]

    def _resolve_socket(self, collection, identifier, name):
        if not name: return None
        match = re.match(r"^(.*?)(?:_?(\d+))?$", name)
        target_base = name
        target_idx_0 = 0
        if match:
            base_str, num_str = match.groups()
            if num_str:
                target_base = base_str if base_str else "Value"
                target_idx_0 = int(num_str) - 1
            else:
                target_base = name
                target_idx_0 = 0
        match_count = 0
        visible_sockets = [s for s in collection if getattr(s, "enabled", True) and not s.hide]
        for s in visible_sockets:
            s_base = SpecialHandlers.get_base_name(s.name)
            if s_base.lower() == target_base.lower():
                if match_count == target_idx_0:
                    return s
                match_count += 1
        for s in collection:
            if s.name == name and getattr(s, "enabled", True): return s
        if identifier:
            for s in collection:
                if s.identifier == identifier: return s
        return None

    def _configure_transform_and_props(self, n_data, offset):
        node = self.node_map.get(n_data.get("name"))
        if not node: return

        if self.context.scene.gn_debug_mode and node.bl_idname == 'GeometryNodeCaptureAttribute':
             DebugUtils.log(self.context, f"Building Capture Node: {n_data.get('params')}")

        params = n_data.get("params", {})
        
        # Location Logic
        is_pasting_to_root = (node.parent is None)
        loc_abs = n_data.get("location_absolute")
        loc_rel = n_data.get("location", params.get("location"))

        if is_pasting_to_root and loc_abs:
            self.has_valid_location = True
            node.location = (loc_abs[0] + offset[0], loc_abs[1] + offset[1])
        elif loc_rel:
            self.has_valid_location = True
            node.location = (loc_rel[0] + offset[0], loc_rel[1] + offset[1])
            
        if node.bl_idname == 'NodeFrame':
            if "width" in n_data: node.width = n_data["width"]
            if "height" in n_data: node.height = n_data["height"]
            if "label" in params: node.label = params["label"]
            if "label_size" in params: node.label_size = int(params["label_size"])
            if "shrink" in params: node.shrink = bool(params["shrink"])
            if "use_custom_color" in params: node.use_custom_color = bool(params["use_custom_color"])
            if "color" in params and node.use_custom_color:
                col = params["color"]
                if len(col) >= 3: node.color = (col[0], col[1], col[2])

        is_input_node = node.bl_idname.startswith("FunctionNodeInput")
        
        # [Pre-Pass] Capture Items
        if node.bl_idname == 'GeometryNodeCaptureAttribute':
            capture_data = params.get("capture_items_data")
            if not capture_data and "data_type" in params:
                 capture_data = [{"name": "Value", "data_type": params["data_type"]}]

            if capture_data and hasattr(node, "capture_items"):
                node.capture_items.clear()
                for item in capture_data:
                    raw_data_type = item.get("data_type", "FLOAT")
                    api_type = node_mappings.get_capture_socket_type(raw_data_type)
                    try:
                        node.capture_items.new(api_type, item.get("name", "Value"))
                    except: pass

        for k, v in params.items():
            if k in {"location", "width", "height", "capture_items_data"}: continue
            
            # [CRITICAL FIX v5.13.17] 仅对 CaptureAttribute 跳过 data_type
            if node.bl_idname == 'GeometryNodeCaptureAttribute' and k == 'data_type': continue
            
            if node.bl_idname == 'NodeFrame' and k in {'color', 'use_custom_color', 'label', 'label_size', 'shrink'}: continue
            
            if is_input_node and hasattr(node, k):
                try:
                    if k == "vector" and isinstance(v, list): setattr(node, k, mathutils.Vector(v)); continue
                    elif k == "color" and isinstance(v, list): setattr(node, k, mathutils.Color(v[:3])); continue
                    else: setattr(node, k, v); continue
                except: pass

            if isinstance(v, dict) and "__type__" in v:
                if v["__type__"] == "ColorRamp": SpecialHandlers.build_color_ramp(getattr(node, k, None), v["data"])
                continue
            
            node_mappings.universal_set_property(node, k, v)

        if self.context.scene.gn_debug_mode and node.bl_idname == 'GeometryNodeCaptureAttribute':
             DebugUtils.inspect_capture_node(node, "POST-PROP-SET")

        inputs_data = n_data.get("inputs", {})
        for k, v in inputs_data.items():
            target_socket = self._resolve_socket(node.inputs, None, k)
            if target_socket:
                try:
                    if target_socket.type == 'OBJECT' and isinstance(v, str): target_socket.default_value = bpy.data.objects.get(v)
                    elif target_socket.type == 'MATERIAL' and isinstance(v, str): target_socket.default_value = bpy.data.materials.get(v)
                    elif target_socket.type == 'IMAGE' and isinstance(v, str): target_socket.default_value = bpy.data.images.get(v)
                    else: 
                        target_socket.default_value = v
                        if self.context.scene.gn_debug_mode and node.bl_idname == 'GeometryNodeCaptureAttribute':
                            DebugUtils.log(self.context, f"Set '{target_socket.name}' = {v}")
                except Exception as e: pass
        
        socket_props = n_data.get("socket_props", {})
        for k, props in socket_props.items():
            s = self._resolve_socket(node.inputs, None, k)
            if s:
                if "hide" in props: s.hide = props["hide"]
                if "hide_value" in props: s.hide_value = props["hide_value"]

    def _handle_zones(self, nodes_data):
        for in_type, out_type in SpecialHandlers.ZONE_PAIRS:
            inputs = [n for n in self.node_map.values() if n.bl_idname == in_type]
            outputs = [n for n in self.node_map.values() if n.bl_idname == out_type]
            if len(inputs) == 1 and len(outputs) == 1:
                try: inputs[0].pair_with_output(outputs[0])
                except: pass
        for n_data in nodes_data:
            node = self.node_map.get(n_data.get("name"))
            if node and n_data.get("is_zone") and "zone_interface" in n_data:
                if node.bl_idname in SpecialHandlers.ZONE_INPUTS:
                    out_type = node.bl_idname.replace("Input", "Output")
                    outputs = [n for n in self.node_map.values() if n.bl_idname == out_type]
                    if outputs: SpecialHandlers.rebuild_zone_interface(outputs[0], n_data["zone_interface"])

    def _link_nodes(self, links_data):
        for l in links_data:
            src, dst = self.node_map.get(l.get("src")), self.node_map.get(l.get("dst"))
            if src and dst:
                try:
                    src_sock = self._resolve_socket(src.outputs, l.get("src_id"), l.get("src_sock"))
                    dst_sock = self._resolve_socket(dst.inputs, l.get("dst_id"), l.get("dst_sock"))
                    if src_sock and dst_sock: self.tree.links.new(src_sock, dst_sock)
                except: pass

# ==============================================================================
# 5. 布局引擎 (Restored)
# ==============================================================================

class LayoutEngine:
    @staticmethod
    def apply(tree, new_nodes):
        if not new_nodes or len(new_nodes) < 2: return
        node_map = {n.name: n for n in new_nodes}
        parents = {n.name: [] for n in new_nodes}
        children = {n.name: [] for n in new_nodes}
        for link in tree.links:
            if link.from_node.name in node_map and link.to_node.name in node_map:
                children[link.from_node.name].append(link.to_node.name)
                parents[link.to_node.name].append(link.from_node.name)
        levels = {n.name: 0 for n in new_nodes}
        queue = [name for name, p in parents.items() if not p] or [new_nodes[0].name]
        visited = set(queue)
        while queue:
            curr = queue.pop(0)
            for child in children[curr]:
                if levels[child] < levels[curr] + 1:
                    levels[child] = levels[curr] + 1
                    if child not in visited: visited.add(child); queue.append(child)
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
# 6. UI & Operators
# ==============================================================================

class GN_OT_Serialize(bpy.types.Operator):
    bl_idname = "gn.serialize"
    bl_label = "序列化节点"
    mode: bpy.props.EnumProperty(items=[('ALL', "全部", ""), ('SELECTED', "选中", "")], default='ALL')
    
    def execute(self, context):
        try:
            tree = context.space_data.edit_tree
            if not tree: return {'CANCELLED'}
            engine = SerializationEngine(tree, context, selected_only=(self.mode=='SELECTED'), compact=context.scene.gn_compact_mode)
            data = engine.execute()
            json_str = json.dumps(data, indent=2, ensure_ascii=False, cls=BlenderJSONEncoder)
            context.window_manager.clipboard = json_str
            self.report({'INFO'}, f"已复制 {len(data['nodes'])} 个节点")
        except Exception as e:
            self.report({'ERROR'}, str(e)); traceback.print_exc()
        return {'FINISHED'}

class GN_OT_Build(bpy.types.Operator):
    bl_idname = "gn.build"
    bl_label = "构建节点"
    mode: bpy.props.EnumProperty(items=[('REPLACE', "替换", ""), ('APPEND', "追加", "")], default='REPLACE')
    
    def execute(self, context):
        tree = context.space_data.edit_tree
        if not tree: return {'CANCELLED'}
        try:
            data = DataUtils.robust_json_load(context.window_manager.clipboard)
            if not data: 
                self.report({'ERROR'}, "剪贴板无效"); return {'CANCELLED'}
            
            if "root" in data and "nodes" not in data: data = data["root"]

            if self.mode == 'APPEND':
                for n in tree.nodes: n.select = False

            engine = ConstructionEngine(tree, context)
            offset = (0, 0)
            engine.build(data, clear=(self.mode == 'REPLACE'), offset=offset)
            self.report({'INFO'}, "构建完成")
        except Exception as e:
            self.report({'ERROR'}, f"构建失败: {e}"); traceback.print_exc()
        return {'FINISHED'}

class GN_PT_Panel(bpy.types.Panel):
    bl_label = "GeoNeural 节点助手 v5.13.19"
    bl_idname = "GN_PT_main"
    bl_space_type = 'NODE_EDITOR' 
    bl_region_type = 'UI'
    bl_category = 'GeoNeural'
    def draw(self, context):
        layout = self.layout
        try: 
            db_ok = node_mappings.load_db()
            layout.label(text="数据库已连接" if db_ok else "数据库缺失 (Dynamic)", icon='CHECKMARK' if db_ok else 'INFO')
        except: layout.label(text="DB Error", icon='ERROR')
        box = layout.box()
        box.label(text="发送给 AI (复制):")
        box.prop(context.scene, "gn_compact_mode", text="紧凑模式")
        box.prop(context.scene, "gn_debug_mode", text="🔧 开启调试日志")
        r = box.row()
        r.operator("gn.serialize", text="选中节点").mode = 'SELECTED'
        r.operator("gn.serialize", text="全部节点").mode = 'ALL'
        box2 = layout.box()
        box2.label(text="从 AI 接收 (粘贴):")
        r2 = box2.row()
        r2.operator("gn.build", text="追加").mode = 'APPEND'
        r2.operator("gn.build", text="替换").mode = 'REPLACE'

def register():
    node_mappings.load_db()
    bpy.types.Scene.gn_compact_mode = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.gn_debug_mode = bpy.props.BoolProperty(default=False)
    for c in (GN_OT_Serialize, GN_OT_Build, GN_PT_Panel): bpy.utils.register_class(c)

def unregister():
    for c in (GN_OT_Serialize, GN_OT_Build, GN_PT_Panel): bpy.utils.unregister_class(c)
    del bpy.types.Scene.gn_compact_mode
    del bpy.types.Scene.gn_debug_mode

if __name__ == "__main__":
    register()