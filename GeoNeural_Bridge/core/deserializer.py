# core/deserializer.py
# GeoNeural Bridge v5.14.2
# 修复: 连接恢复逻辑由 "名称优先" 改为 "索引优先"，解决 Vector Math 等节点同名插槽导致的连接错乱问题
# 基础: v5.14.1

import bpy
import logging
from mathutils import Vector, Euler, Matrix, Color, Quaternion

try:
    from . import node_mappings
except ImportError:
    node_mappings = None

logger = logging.getLogger("GeoNeuralBridge.deserializer")

# ==============================================================================
# 1. 节点操作原子函数
# ==============================================================================

class NodeRestorer:
    PROP_BLACKLIST = {
        'active_item', 'active_index', 'inspection_index', 'is_active_output', 
        'interface', 'node_tree', 'color_ramp', 'warning_propagation',
        'bl_idname', 'bl_label', 'bl_description', 'bl_icon', 'location', 'width', 'height'
    }

    @staticmethod
    def restore_props(node, data):
        if 'label' in data: node.label = data['label']
        if 'mute' in data: node.mute = data['mute']
        if 'use_custom_color' in data: node.use_custom_color = data['use_custom_color']
        if 'color' in data: node.color = data['color']
        
        props = data.get('properties', {})
        for prop_name, value in props.items():
            if prop_name in NodeRestorer.PROP_BLACKLIST: continue
            if isinstance(value, str) and value.startswith('<bpy_struct'): continue

            if isinstance(value, dict) and value.get('__type__') == 'ColorRamp':
                NodeRestorer._restore_color_ramp(node, prop_name, value['data'])
                continue
            
            if prop_name == "capture_items_data": continue

            if hasattr(node, prop_name):
                try:
                    rna = node.bl_rna.properties.get(prop_name)
                    if rna and rna.is_readonly: continue
                    current = getattr(node, prop_name)
                    if isinstance(current, (Vector, Color, Euler)) and isinstance(value, list):
                        setattr(node, prop_name, type(current)(value))
                    elif isinstance(current, Matrix) and isinstance(value, list):
                        mat = Matrix([value[i:i+4] for i in range(0, 16, 4)]) if len(value) == 16 else Matrix(value)
                        setattr(node, prop_name, mat)
                    else:
                        setattr(node, prop_name, value)
                except: pass

    @staticmethod
    def _restore_color_ramp(node, prop_name, ramp_data):
        if not hasattr(node, prop_name) or not ramp_data: return
        ramp = getattr(node, prop_name)
        try:
            if "color_mode" in ramp_data: ramp.color_mode = ramp_data["color_mode"]
            if "interpolation" in ramp_data: ramp.interpolation = ramp_data["interpolation"]
            elements = ramp_data.get("elements", [])
            while len(ramp.elements) < len(elements): ramp.elements.new(1.0)
            while len(ramp.elements) > len(elements): ramp.elements.remove(ramp.elements[-1])
            for i, e_data in enumerate(elements):
                ramp.elements[i].position = e_data.get("pos", 0.0)
                ramp.elements[i].color = e_data.get("color", (1,1,1,1))
        except: pass

    @staticmethod
    def restore_socket_defaults(node, inputs_data):
        for s_data in inputs_data:
            if s_data.get('identifier') == '__extend__' or \
               s_data.get('bl_socket_idname') == 'NodeSocketVirtual': 
                continue
            
            # 数值恢复也采用 ID 优先策略
            socket = None
            ident = s_data.get('identifier')
            
            if ident:
                socket = next((s for s in node.inputs if s.identifier == ident), None)
            
            if not socket:
                name = s_data.get('name')
                if name:
                    socket = next((s for s in node.inputs if s.name == name), None)

            if socket and 'default_value' in s_data:
                try:
                    val = s_data['default_value']
                    if socket.bl_idname in {'NodeSocketObject', 'NodeSocketMaterial', 'NodeSocketCollection', 'NodeSocketTexture', 'NodeSocketImage'}:
                        type_map = {'NodeSocketObject': 'objects', 'NodeSocketMaterial': 'materials', 'NodeSocketCollection': 'collections', 'NodeSocketTexture': 'textures', 'NodeSocketImage': 'images'}
                        col = getattr(bpy.data, type_map.get(socket.bl_idname, ''), None)
                        if col and isinstance(val, str): 
                            target = col.get(val)
                            if target: socket.default_value = target
                    elif socket.bl_idname == 'NodeSocketColor' and isinstance(val, list):
                        if len(val) == 3: val.append(1.0)
                        socket.default_value = val
                    elif socket.bl_idname == 'NodeSocketVector' and isinstance(val, list):
                        socket.default_value = Vector(val)
                    elif socket.bl_idname == 'NodeSocketRotation' and isinstance(val, list):
                        if len(val) == 3: socket.default_value = val
                    else:
                        socket.default_value = val
                except Exception: pass
            
            if socket:
                if 'hide' in s_data: socket.hide = s_data['hide']
                if 'hide_value' in s_data: socket.hide_value = s_data['hide_value']

# ==============================================================================
# 3. 反序列化主引擎
# ==============================================================================

class DeserializationEngine:
    def __init__(self, tree, context):
        self.tree = tree
        self.context = context
        self.node_map = {} 

    def deserialize_tree(self, json_data, offset=(0,0)):
        nodes_data = json_data.get("nodes", [])
        links_data = json_data.get("links", [])
        frames_data = json_data.get("frames", {})

        # Phase 1: 骨架
        ordered_nodes = self._sort_priority(nodes_data)
        for n_data in ordered_nodes:
            self._create_node_skeleton(n_data, offset)

        # Phase 2: 定义
        for n_data in nodes_data:
            node = self.node_map.get(n_data.get('name'))
            if not node: continue
            
            for state_key, col_name in [('simulation_state', 'state_items'), 
                                      ('repeat_state', 'repeat_items'), 
                                      ('bake_state', 'bake_items')]:
                if state_key in n_data:
                    self._restore_zone_items(node, n_data[state_key], col_name)
            
            if 'capture_items_data' in n_data.get('properties', {}):
                self._restore_capture_items(node, n_data['properties']['capture_items_data'])

        # Phase 3: 配对
        self._pair_zones(nodes_data)

        # Phase 4: 数值
        for n_data in nodes_data:
            node = self.node_map.get(n_data.get('name'))
            if not node: continue
            if 'inputs' in n_data: NodeRestorer.restore_socket_defaults(node, n_data['inputs'])
            if 'outputs' in n_data:
                for i, out in enumerate(n_data['outputs']):
                    if i < len(node.outputs) and out.get('hide'): node.outputs[i].hide = True

        # Phase 5: 连接与父子
        self._restore_links(links_data)
        
        final_frames = frames_data.copy()
        for n_data in nodes_data:
            if 'parent' in n_data and n_data['parent']:
                child_name = n_data.get('name')
                parent_name = n_data.get('parent')
                if child_name and parent_name and child_name not in final_frames:
                    final_frames[child_name] = parent_name
        self._restore_frames(final_frames)

        for node in self.node_map.values(): node.select = True
        return list(self.node_map.values())

    def _sort_priority(self, nodes_data):
        zone_outputs = {'GeometryNodeSimulationOutput', 'GeometryNodeRepeatOutput', 'GeometryNodeBakeOutput'}
        outputs, normals, frames = [], [], []
        for n in nodes_data:
            if n.get('bl_idname') in zone_outputs: outputs.append(n)
            elif n.get('bl_idname') == 'NodeFrame': frames.append(n)
            else: normals.append(n)
        return outputs + normals + frames

    def _create_node_skeleton(self, n_data, offset):
        bl_idname = n_data.get('bl_idname')
        orig_name = n_data.get('name')
        try:
            node = self.tree.nodes.new(bl_idname)
        except:
            node = self.tree.nodes.new("NodeFrame")
            node.label = f"MISSING: {bl_idname}"
            node.use_custom_color = True; node.color = (1, 0, 0)

        node.name = orig_name 
        self.node_map[orig_name] = node

        if 'location' in n_data:
            loc = n_data['location']
            node.location = (loc[0] + offset[0], loc[1] + offset[1])
        else:
            idx = len(self.node_map)
            node.location = (offset[0] + (idx * 220), offset[1] - (idx * 50))

        if 'width' in n_data: node.width = n_data['width']
        if 'height' in n_data: node.height = n_data['height']
        NodeRestorer.restore_props(node, n_data)

    def _restore_zone_items(self, node, state_data, collection_name):
        if not hasattr(node, collection_name): return
        collection = getattr(node, collection_name)
        try: collection.clear()
        except: pass

        for item in state_data.get('items', []):
            name = item.get('name', 'Value')
            raw_type = item.get('socket_type', 'FLOAT')
            bl_idname = item.get('bl_socket_idname')
            
            if node_mappings:
                if bl_idname: api_type = node_mappings.get_api_enum(bl_idname)
                else: api_type = node_mappings.get_api_enum(raw_type)
            else:
                api_type = 'FLOAT'

            if api_type == 'VIRTUAL': continue
            try: collection.new(api_type, name)
            except: 
                try: collection.new('GEOMETRY', name)
                except: pass

    def _restore_capture_items(self, node, items_data):
        if not hasattr(node, 'capture_items'): return
        try:
            node.capture_items.clear()
            for item in items_data:
                name = item.get("name", "Value")
                raw_type = item.get("data_type", "FLOAT")
                api_type = node_mappings.get_api_enum(raw_type) if node_mappings else raw_type
                try: node.capture_items.new(api_type, name)
                except: 
                    try: node.capture_items.new('FLOAT', name)
                    except: pass
        except: pass

    def _pair_zones(self, nodes_data):
        zone_types = {
            'GeometryNodeSimulationInput': 'GeometryNodeSimulationOutput',
            'GeometryNodeRepeatInput': 'GeometryNodeRepeatOutput',
            'GeometryNodeBakeInput': 'GeometryNodeBakeOutput'
        }
        inputs = {}
        outputs = {}
        for n_data in nodes_data:
            bl_idname = n_data.get('bl_idname')
            node = self.node_map.get(n_data.get('name'))
            if not node: continue
            if bl_idname in zone_types:
                inputs.setdefault(bl_idname, []).append(node)
            elif bl_idname in zone_types.values():
                outputs.setdefault(bl_idname, []).append(node)
        
        for in_type, out_type in zone_types.items():
            in_nodes = inputs.get(in_type, [])
            out_nodes = outputs.get(out_type, [])
            count = min(len(in_nodes), len(out_nodes))
            for i in range(count):
                try:
                    if hasattr(in_nodes[i], 'pair_with_output'):
                        in_nodes[i].pair_with_output(out_nodes[i])
                except: pass

    def _restore_links(self, links_data):
        for link in links_data:
            src = self.node_map.get(link.get('from_node'))
            dst = self.node_map.get(link.get('to_node'))
            if src and dst:
                from_sock = self._find_socket(src.outputs, link.get('from_socket'), link.get('from_socket_index'))
                to_sock = self._find_socket(dst.inputs, link.get('to_socket'), link.get('to_socket_index'))
                if from_sock and to_sock:
                    try: self.tree.links.new(from_sock, to_sock)
                    except: pass

    def _find_socket(self, collection, name, index):
        """
        [v5.14.2 Fix] 连接查找逻辑翻转: Index First (索引优先)
        解决 Vector Math 等节点多个输入插槽同名导致的连接错误。
        """
        # 1. 优先尝试索引匹配
        # 如果 JSON 里的索引在范围内，且名字也对得上，那绝对就是它了
        if index is not None and 0 <= index < len(collection):
            s = collection[index]
            if s.name == name and s.bl_idname != 'NodeSocketVirtual':
                return s
        
        # 2. 回退到名称匹配 (Name Fallback)
        # 只有当索引对不上 (Blender版本变了导致插槽移位) 时才用这个
        for s in collection:
            if s.name == name and s.bl_idname != 'NodeSocketVirtual': 
                return s
        
        # 3. 最后的手段 (Blind Index)
        # 名字对不上，但索引还在，死马当活马医
        if index is not None and 0 <= index < len(collection):
            s = collection[index]
            if s.bl_idname != 'NodeSocketVirtual': 
                return s
                
        return None

    def _restore_frames(self, frames_data):
        for child_name, parent_name in frames_data.items():
            child = self.node_map.get(child_name)
            parent = self.node_map.get(parent_name)
            if child and parent: child.parent = parent