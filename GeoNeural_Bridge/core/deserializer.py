# core/deserializer.py
# GeoNeural Bridge v5.14.51
# Critical Fix: 修复崩溃源与属性丢失 (Crash Vector & Domain Restore Fix)
# Architecture: 重构反序列化生命周期，严格遵循 "Topology First, Data Later" 原则
# 1. Skeleton -> 2. Heal -> 3. Pair (关键前置) -> 4. Props (含 Remap) -> 5. Links -> 6. Update

import bpy
import logging
import re
import difflib
from mathutils import Vector, Euler, Matrix, Color, Quaternion

try:
    from . import node_mappings
except ImportError:
    node_mappings = None

logger = logging.getLogger("GeoNeuralBridge.deserializer")

# ==============================================================================
# 1. 智能属性设置器 (增强版)
# ==============================================================================

class SmartPropertySetter:
    # [v5.14.51] 新增属性重映射表，解决 AI 幻觉与 API 差异
    PROP_REMAP = {
        'domain_type': 'domain',       # AI 常见误称
        'data_type': 'data_type',      # 保持不变
        'mode': 'operation',           # Math 节点常见
        'operation': 'operation',
    }

    @staticmethod
    def resolve_prop_name(name):
        return SmartPropertySetter.PROP_REMAP.get(name, name)

    @staticmethod
    def set_property(node, prop_name, value):
        # 1. 映射属性名
        real_prop_name = SmartPropertySetter.resolve_prop_name(prop_name)
        
        # 2. 基础存在性检查
        if not hasattr(node, real_prop_name):
            return False 

        try:
            rna_prop = node.bl_rna.properties.get(real_prop_name)
            if rna_prop and rna_prop.is_readonly: return True

            # 3. 枚举模糊匹配
            if rna_prop and rna_prop.type == 'ENUM' and isinstance(value, str):
                return SmartPropertySetter._set_enum_fuzzy(node, real_prop_name, value, rna_prop)

            # 4. 数学类型转换
            current = getattr(node, real_prop_name)
            if isinstance(current, (Vector, Color, Euler)) and isinstance(value, (list, tuple)):
                if isinstance(current, Color) and len(value) == 3:
                    value = list(value) + [1.0]
                setattr(node, real_prop_name, type(current)(value))
            elif isinstance(current, Matrix) and isinstance(value, (list, tuple)):
                mat = Matrix([value[i:i+4] for i in range(0, 16, 4)]) if len(value) == 16 else Matrix(value)
                setattr(node, real_prop_name, mat)
            else:
                setattr(node, real_prop_name, value)
            return True
        except Exception:
            return False

    @staticmethod
    def _set_enum_fuzzy(node, prop_name, value, rna_prop):
        valid_items = [item.identifier for item in rna_prop.enum_items]
        if value in valid_items: setattr(node, prop_name, value); return True
        
        norm_val = value.upper().replace(" ", "_")
        if norm_val in valid_items: setattr(node, prop_name, norm_val); return True
        
        for item in valid_items:
            if item == norm_val: setattr(node, prop_name, item); return True
            
        matches = difflib.get_close_matches(norm_val, valid_items, n=1, cutoff=0.6)
        if matches: setattr(node, prop_name, matches[0]); return True
        return False

# ==============================================================================
# 2. 节点恢复器
# ==============================================================================

class NodeRestorer:
    PROP_BLACKLIST = {
        'active_item', 'active_index', 'inspection_index', 'is_active_output', 
        'interface', 'node_tree', 'color_ramp', 'warning_propagation',
        'bl_idname', 'bl_label', 'bl_description', 'bl_icon', 'location', 'width', 'height',
        'active_input_index', 'active_main_index', 'active_generation_index'
    }

    @staticmethod
    def restore_props(node, data):
        """
        恢复属性。返回未成功应用的属性字典 (unassigned)。
        """
        if 'label' in data: node.label = data['label']
        if 'mute' in data: node.mute = data['mute']
        if 'use_custom_color' in data: node.use_custom_color = data['use_custom_color']
        if 'color' in data: node.color = data['color']
        
        props = data.get('properties', {})
        if not isinstance(props, dict): return {}

        unassigned_props = {}

        for raw_prop_name, value in props.items():
            if raw_prop_name in NodeRestorer.PROP_BLACKLIST: continue
            if isinstance(value, str) and value.startswith('<bpy_struct'): continue

            if isinstance(value, dict) and value.get('__type__') == 'ColorRamp':
                NodeRestorer._restore_color_ramp(node, raw_prop_name, value['data'])
                continue
            
            if raw_prop_name == "capture_items_data": continue

            # 尝试直接赋值
            success = SmartPropertySetter.set_property(node, raw_prop_name, value)
            
            if not success:
                # 记录原始键名和值，供后续传播使用
                unassigned_props[raw_prop_name] = value

        return unassigned_props

    @staticmethod
    def _restore_color_ramp(node, prop_name, ramp_data):
        if not hasattr(node, prop_name) or not isinstance(ramp_data, dict): return
        ramp = getattr(node, prop_name)
        try:
            if "color_mode" in ramp_data: ramp.color_mode = ramp_data["color_mode"]
            if "interpolation" in ramp_data: ramp.interpolation = ramp_data["interpolation"]
            elements = ramp_data.get("elements", [])
            while len(ramp.elements) < len(elements): ramp.elements.new(1.0)
            while len(ramp.elements) > len(elements): ramp.elements.remove(ramp.elements[-1])
            for i, e_data in enumerate(elements):
                if not isinstance(e_data, dict): continue
                ramp.elements[i].position = e_data.get("pos", 0.0)
                ramp.elements[i].color = e_data.get("color", (1,1,1,1))
        except: pass

    @staticmethod
    def restore_socket_defaults(node, inputs_data):
        if not isinstance(inputs_data, list): return
        for s_data in inputs_data:
            if not isinstance(s_data, dict): continue
            if s_data.get('identifier') == '__extend__' or s_data.get('bl_socket_idname') == 'NodeSocketVirtual': continue
            
            socket = None
            ident = s_data.get('identifier')
            if ident: socket = next((s for s in node.inputs if s.identifier == ident), None)
            if not socket:
                name = s_data.get('name')
                if name: socket = next((s for s in node.inputs if s.name == name), None)

            if socket and 'default_value' in s_data:
                try:
                    val = s_data['default_value']
                    if socket.bl_idname in {'NodeSocketObject', 'NodeSocketMaterial', 'NodeSocketCollection', 'NodeSocketTexture', 'NodeSocketImage'}:
                        type_map = {'NodeSocketObject': 'objects', 'NodeSocketMaterial': 'materials', 'NodeSocketCollection': 'collections', 'NodeSocketTexture': 'textures', 'NodeSocketImage': 'images'}
                        col = getattr(bpy.data, type_map.get(socket.bl_idname, ''), None)
                        if col and isinstance(val, str): 
                            target = col.get(val)
                            if target: socket.default_value = target
                    elif socket.bl_idname == 'NodeSocketVector' and isinstance(val, list):
                        socket.default_value = Vector(val)
                    elif socket.bl_idname == 'NodeSocketColor' and isinstance(val, list):
                        if len(val) == 3: val.append(1.0)
                        socket.default_value = val
                    else:
                        socket.default_value = val
                except: pass
            
            if socket:
                if 'hide' in s_data: socket.hide = s_data['hide']
                if 'hide_value' in s_data: socket.hide_value = s_data['hide_value']

# ==============================================================================
# 3. 反序列化主引擎 (生命周期重构版)
# ==============================================================================

class DeserializationEngine:
    def __init__(self, tree, context):
        self.tree = tree
        self.context = context
        self.node_map = {}
        self.deferred_props_map = {} 

    def deserialize_tree(self, json_data, offset=(0,0)):
        if not isinstance(json_data, dict): return []
        
        nodes_data = json_data.get("nodes", [])
        if not isinstance(nodes_data, list): nodes_data = []
        links_data = json_data.get("links", [])
        frames_data = json_data.get("frames", {})

        # ----------------------------------------------------------------------
        # Step 1: 骨架构建 (Skeleton)
        # ----------------------------------------------------------------------
        ordered_nodes = self._sort_priority(nodes_data)
        for n_data in ordered_nodes:
            if isinstance(n_data, dict):
                self._create_node_skeleton(n_data, offset)

        # ----------------------------------------------------------------------
        # Step 2: 拓扑愈合 (Topology Healing) - 确保配对节点存在
        # ----------------------------------------------------------------------
        self._heal_topology(offset)

        # ----------------------------------------------------------------------
        # Step 3: 区域配对 (Zone Pairing) - 关键前置！
        # ----------------------------------------------------------------------
        # [CRITICAL FIX] 必须在 restore_props 和 update_tag 之前完成配对
        # 否则 (1) 属性无法传播 (2) 图表无效导致崩溃
        self._pair_zones()

        # ----------------------------------------------------------------------
        # Step 4: 属性恢复与传播 (Properties & Propagation)
        # ----------------------------------------------------------------------
        for n_data in nodes_data:
            if not isinstance(n_data, dict): continue
            node = self.node_map.get(n_data.get('name'))
            if not node: continue
            
            # 依赖恢复 (Node Tree)
            if node.bl_idname == 'GeometryNodeGroup' and 'node_tree_name' in n_data:
                self._restore_node_tree_dependency(node, n_data)

            # 核心属性恢复
            unassigned = NodeRestorer.restore_props(node, n_data)
            
            # [v5.14.51] 立即尝试传播未分配的属性 (Propagate Immediately)
            # 因为此时配对关系已建立，我们可以直接查找 partner
            if unassigned:
                self._propagate_attributes(node, unassigned)

            # 遗留数据适配
            props = n_data.get('properties', {})
            if 'capture_items_data' in props:
                self._restore_capture_items(node, props['capture_items_data'])
            elif 'data_type' in props and hasattr(node, 'capture_items'):
                self._adapt_legacy_capture_node(node, props['data_type'])

        # ----------------------------------------------------------------------
        # Step 5: 内部列表内容恢复 (Internal Lists)
        # ----------------------------------------------------------------------
        # 此时拓扑已闭环，恢复 Zone 内部 Item 是安全的
        for n_data in nodes_data:
            if not isinstance(n_data, dict): continue
            node = self.node_map.get(n_data.get('name'))
            if not node: continue

            for state_key, col_name in [('simulation_state', 'state_items'), 
                                      ('repeat_state', 'repeat_items'), 
                                      ('bake_state', 'bake_items')]:
                if state_key in n_data: self._restore_zone_items(node, n_data[state_key], col_name)
            
            if 'foreach_main' in n_data or 'foreach_input' in n_data or 'foreach_generation' in n_data:
                self._restore_foreach_stats(node, n_data)

        # ----------------------------------------------------------------------
        # Step 6: Socket 数值恢复
        # ----------------------------------------------------------------------
        for n_data in nodes_data:
            if not isinstance(n_data, dict): continue
            node = self.node_map.get(n_data.get('name'))
            if not node: continue
            if 'inputs' in n_data: NodeRestorer.restore_socket_defaults(node, n_data['inputs'])
            if 'outputs' in n_data:
                 for i, out in enumerate(n_data['outputs']):
                    if isinstance(out, dict) and i < len(node.outputs) and out.get('hide'): node.outputs[i].hide = True

        # ----------------------------------------------------------------------
        # Step 7: 连接与层级 (Links & Parenting)
        # ----------------------------------------------------------------------
        self._restore_links(links_data)
        
        final_frames = frames_data.copy() if isinstance(frames_data, dict) else {}
        for n_data in nodes_data:
            if isinstance(n_data, dict) and 'parent' in n_data:
                child = self.node_map.get(n_data.get('name'))
                parent = self.node_map.get(n_data.get('parent'))
                if child and parent: child.parent = parent
        self._restore_frames(final_frames)

        # ----------------------------------------------------------------------
        # Step 8: 安全更新 (Safe Update) - 最后一步
        # ----------------------------------------------------------------------
        # 只有在拓扑完整、配对成功、连线完成后的 Update 才是安全的
        if hasattr(self.tree, "update_tag"): 
            try: self.tree.update_tag()
            except Exception as e: logger.warning(f"Final update_tag warning: {e}")

        for node in self.node_map.values(): node.select = True
        return list(self.node_map.values())

    def _pair_zones(self):
        """
        [v5.14.51] 纯粹的配对逻辑，不再负责传播属性。
        配对必须在 restore_props 之前完成。
        """
        zone_types = {
            'GeometryNodeSimulationInput': 'GeometryNodeSimulationOutput',
            'GeometryNodeRepeatInput': 'GeometryNodeRepeatOutput',
            'GeometryNodeBakeInput': 'GeometryNodeBakeOutput',
            'GeometryNodeForeachGeometryElementInput': 'GeometryNodeForeachGeometryElementOutput'
        }
        
        current_nodes = list(self.node_map.values())
        inputs, outputs = {}, {}
        for node in current_nodes:
            if node.bl_idname in zone_types: inputs.setdefault(node.bl_idname, []).append(node)
            elif node.bl_idname in zone_types.values(): outputs.setdefault(node.bl_idname, []).append(node)
        
        for in_type, out_type in zone_types.items():
            in_nodes = inputs.get(in_type, [])
            out_nodes = outputs.get(out_type, [])
            count = min(len(in_nodes), len(out_nodes))
            for i in range(count):
                input_node = in_nodes[i]
                output_node = out_nodes[i]
                try:
                    if hasattr(input_node, 'pair_with_output'):
                        input_node.pair_with_output(output_node)
                except: pass

    def _propagate_attributes(self, source_node, props_dict):
        """
        [v5.14.51] 属性传播逻辑
        尝试将 source_node 上无法应用的属性，应用到其 paired_output (或 input) 上。
        """
        partner = None
        
        # 寻找 partner
        if hasattr(source_node, "paired_output"): # Input Node
            partner = source_node.paired_output
        elif hasattr(source_node, "paired_input"): # Output Node (less common API)
             # Blender API 有时没有直接的 paired_input 属性，需反向查找，
             # 但通常属性是定义在 Input 上的，所以上面的 check 最重要。
             pass 

        if not partner:
            # 备用方案：通过 zone_type 手动查找已配对的 partner
            # (由于 Step 3 已执行配对，这里可以通过拓扑查找)
            pass 

        if partner:
            for p_name, p_val in props_dict.items():
                SmartPropertySetter.set_property(partner, p_name, p_val)

    # --------------------------------------------------------------------------
    # 辅助方法 (保持不变)
    # --------------------------------------------------------------------------
    
    def _restore_node_tree_dependency(self, node, n_data):
        tree_name = n_data.get('node_tree_name')
        if not tree_name: return
        target_tree = bpy.data.node_groups.get(tree_name)
        if not target_tree:
            try:
                target_tree = bpy.data.node_groups.new(tree_name, 'GeometryNodeTree')
                for direction in ['inputs', 'outputs']:
                    if direction in n_data:
                        for s_data in n_data[direction]:
                            s_name = s_data.get('name', 'Socket')
                            s_type = s_data.get('bl_socket_idname', 'NodeSocketFloat')
                            api_type = node_mappings.get_api_enum(s_type) if node_mappings else 'FLOAT'
                            if api_type != 'VIRTUAL':
                                try: target_tree.interface.new_socket(s_name, in_out=direction[:-1].upper(), socket_type=api_type)
                                except: pass
            except: pass
        if target_tree: node.node_tree = target_tree

    def _heal_topology(self, offset):
        zone_pairs = {
            'GeometryNodeForeachGeometryElementInput': 'GeometryNodeForeachGeometryElementOutput',
            'GeometryNodeSimulationInput': 'GeometryNodeSimulationOutput',
            'GeometryNodeRepeatInput': 'GeometryNodeRepeatOutput',
            'GeometryNodeBakeInput': 'GeometryNodeBakeOutput'
        }
        present_types = {}
        for node in self.node_map.values():
            present_types.setdefault(node.bl_idname, []).append(node)
        for in_type, out_type in zone_pairs.items():
            inputs = present_types.get(in_type, [])
            outputs = present_types.get(out_type, [])
            if len(inputs) > len(outputs):
                for i in range(len(inputs) - len(outputs)):
                    ghost = self._create_ghost_node(out_type, inputs[i].location, offset, "Auto_Output")
                    self._sync_ghost_node_data(ghost, inputs[i])
            elif len(outputs) > len(inputs):
                for i in range(len(outputs) - len(inputs)):
                    ghost = self._create_ghost_node(in_type, outputs[i].location, offset, "Auto_Input")
                    self._sync_ghost_node_data(ghost, outputs[i])

    def _create_ghost_node(self, bl_idname, ref_location, offset, suffix):
        try:
            node = self.tree.nodes.new(bl_idname)
            shift = Vector((300, 0)) if "Output" in bl_idname else Vector((-300, 0))
            node.location = ref_location + shift
            unique_name = f"{bl_idname}_{suffix}_{len(self.node_map)}"
            self.node_map[unique_name] = node
            node.label = "(Auto Created)"
            return node
        except: return None

    def _sync_ghost_node_data(self, ghost_node, ref_node):
        if not ghost_node or not ref_node: return
        for col_name in ['main_items', 'input_items', 'generation_items']:
            if hasattr(ref_node, col_name) and hasattr(ghost_node, col_name):
                src = getattr(ref_node, col_name); dst = getattr(ghost_node, col_name)
                dst.clear()
                for item in src:
                    s_type = getattr(item, 'socket_type', 'FLOAT')
                    try: 
                        new_item = dst.new(s_type, item.name)
                        if hasattr(item, 'color') and hasattr(new_item, 'color'): new_item.color = item.color
                    except: pass
        for col_name in ['state_items', 'repeat_items', 'bake_items']:
            if hasattr(ref_node, col_name) and hasattr(ghost_node, col_name):
                src = getattr(ref_node, col_name); dst = getattr(ghost_node, col_name)
                dst.clear()
                for item in src:
                    try: dst.new(getattr(item, 'socket_type', 'FLOAT'), item.name)
                    except: pass

    def _sort_priority(self, nodes_data):
        zone_outputs = {'GeometryNodeSimulationOutput', 'GeometryNodeRepeatOutput', 'GeometryNodeBakeOutput', 'GeometryNodeForeachGeometryElementOutput'}
        outputs, normals, frames = [], [], []
        for n in nodes_data:
            if not isinstance(n, dict): continue
            bid = n.get('bl_idname')
            if bid in zone_outputs: outputs.append(n)
            elif bid == 'NodeFrame': frames.append(n)
            else: normals.append(n)
        return outputs + normals + frames

    def _create_node_skeleton(self, n_data, offset):
        bl_idname = n_data.get('bl_idname')
        orig_name = n_data.get('name')
        try: node = self.tree.nodes.new(bl_idname)
        except: 
            node = self.tree.nodes.new("NodeFrame")
            node.label = f"MISSING: {bl_idname}"
        
        node.name = orig_name 
        self.node_map[orig_name] = node
        
        if 'location' in n_data:
            loc = n_data['location']
            node.location = (loc[0] + offset[0], loc[1] + offset[1])
        else:
            idx = len(self.node_map)
            node.location = (offset[0] + (idx * 200), offset[1] - (idx * 50))
        
        if 'width' in n_data: node.width = n_data['width']
        if 'height' in n_data: node.height = n_data['height']

    def _restore_foreach_stats(self, node, n_data):
        mappings = [('main_items', 'foreach_main'), ('input_items', 'foreach_input'), ('generation_items', 'foreach_generation')]
        for col_name, json_key in mappings:
            if not hasattr(node, col_name) or json_key not in n_data: continue
            collection = getattr(node, col_name)
            try: collection.clear()
            except: pass
            for item in n_data[json_key].get('items', []):
                name = item.get('name', 'Value'); raw_type = item.get('socket_type', 'FLOAT')
                api_type = node_mappings.get_api_enum(raw_type) if node_mappings else 'FLOAT'
                try: collection.new(api_type, name)
                except: pass

    def _restore_zone_items(self, node, state_data, collection_name):
        if not hasattr(node, collection_name) or not isinstance(state_data, dict): return
        collection = getattr(node, collection_name)
        try: collection.clear()
        except: pass
        for item in state_data.get('items', []):
            if isinstance(item, str): name = item; raw_type = 'FLOAT'
            elif isinstance(item, dict): name = item.get('name', 'Value'); raw_type = item.get('socket_type', 'FLOAT')
            else: continue
            if node_mappings:
                api_type = node_mappings.get_api_enum(item.get('bl_socket_idname', raw_type))
            else: api_type = 'FLOAT'
            if api_type == 'VIRTUAL': continue
            try: collection.new(api_type, name)
            except: 
                try: collection.new('GEOMETRY', name)
                except: pass

    def _adapt_legacy_capture_node(self, node, data_type_str):
        try:
            node.capture_items.clear()
            api_type = 'FLOAT' 
            if 'VECTOR' in data_type_str.upper(): api_type = 'FLOAT_VECTOR'
            elif 'COLOR' in data_type_str.upper(): api_type = 'FLOAT_COLOR'
            elif 'INT' in data_type_str.upper(): api_type = 'INT'
            elif 'BOOL' in data_type_str.upper(): api_type = 'BOOLEAN'
            elif 'ROT' in data_type_str.upper(): api_type = 'ROTATION'
            node.capture_items.new(api_type, "Value")
        except: pass

    def _restore_capture_items(self, node, items_data):
        if not hasattr(node, 'capture_items') or not isinstance(items_data, list): return
        try:
            node.capture_items.clear()
            for item in items_data:
                name = item.get("name", "Value") if isinstance(item, dict) else item
                raw_type = item.get("data_type", "FLOAT") if isinstance(item, dict) else "FLOAT"
                api_type = node_mappings.get_api_enum(raw_type) if node_mappings else raw_type
                try: node.capture_items.new(api_type, name)
                except: 
                    try: node.capture_items.new('FLOAT', name)
                    except: pass
        except: pass

    def _restore_links(self, links_data):
        if not isinstance(links_data, list): return
        for link in links_data:
            if not isinstance(link, dict): continue
            src = self.node_map.get(link.get('from_node'))
            dst = self.node_map.get(link.get('to_node'))
            if src and dst:
                from_sock = self._find_socket(src.outputs, link.get('from_socket'), link.get('from_socket_index'))
                to_sock = self._find_socket(dst.inputs, link.get('to_socket'), link.get('to_socket_index'))
                if from_sock and to_sock:
                    try: self.tree.links.new(from_sock, to_sock)
                    except: pass

    def _find_socket(self, collection, name, index):
        if index is not None and 0 <= index < len(collection):
            s = collection[index]
            if s.name == name or s.identifier == name: return s
        for i, s in enumerate(collection):
            if s.identifier == name: return s
        for s in collection:
            if s.name == name and s.bl_idname != 'NodeSocketVirtual': return s
        if isinstance(name, str):
            clean = re.sub(r'_\d+$', '', name).lower()
            for s in collection:
                if s.name.lower() == clean and s.bl_idname != 'NodeSocketVirtual': return s
        type_keywords = {
            "GEOMETRY": "NodeSocketGeometry", "VECTOR": "NodeSocketVector",
            "SHADER": "NodeSocketShader", "COLOR": "NodeSocketColor",
            "IMAGE": "NodeSocketImage", "OBJECT": "NodeSocketObject",
            "COLLECTION": "NodeSocketCollection", "MATERIAL": "NodeSocketMaterial",
            "STRING": "NodeSocketString", "ROTATION": "NodeSocketRotation", "MATRIX": "NodeSocketMatrix"
        }
        if name and name.upper() in type_keywords:
            target = type_keywords[name.upper()]
            for s in collection:
                if s.bl_idname == target and not s.hide and s.enabled: return s
        if index is not None and 0 <= index < len(collection):
            return collection[index]
        return None

    def _restore_frames(self, frames_data):
        if not isinstance(frames_data, dict): return
        for child_name, parent_name in frames_data.items():
            child = self.node_map.get(child_name)
            parent = self.node_map.get(parent_name)
            if child and parent: child.parent = parent