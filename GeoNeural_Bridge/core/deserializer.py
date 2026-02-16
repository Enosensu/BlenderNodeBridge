# core/deserializer.py
# GeoNeural Bridge v5.14.72 (The Ultimate Polymorphic Engine)
# 架构突破: 废除硬编码映射字典。将“多态清洗”与“词序无关匹配”同时应用于底层 API Identifier 与顶层 UI Name。
# 理由: 彻底解决 AI 基于 UI 名称臆测枚举值的乱序、变体问题，实现最高级别的架构通用性。
# 流程: Topology First -> Heal -> Pair (Ledger) -> Props (Dual-Track Fuzzy Enum) -> Inputs -> Links -> Update

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
# 1. 智能属性设置器 (双轨多态匹配引擎)
# ==============================================================================

class SmartPropertySetter:
    PROP_REMAP = {
        'domain_type': 'domain',
        'data_type': 'data_type',      
        'mode': 'operation',
        'operation': 'operation',
        'input_type': 'input_type'
    }

    @staticmethod
    def resolve_prop_name(name):
        return SmartPropertySetter.PROP_REMAP.get(name, name)

    @staticmethod
    def set_property(node, prop_name, value):
        real_prop_name = SmartPropertySetter.resolve_prop_name(prop_name)
        
        if not hasattr(node, real_prop_name):
            return False 

        try:
            rna_prop = node.bl_rna.properties.get(real_prop_name)
            if rna_prop and rna_prop.is_readonly: return True

            if rna_prop and rna_prop.type == 'ENUM' and isinstance(value, str):
                return SmartPropertySetter._set_enum_fuzzy(node, real_prop_name, value, rna_prop)

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
        """
        [v5.14.72 终极重构] 双轨多态解析引擎 (Dual-Track Polymorphic Resolver)
        同时对比枚举项的 API identifier 和 UI name，通过纯算法解决所有缩写、别名、乱序问题。
        """
        enum_items = rna_prop.enum_items
        
        # 1. 输入值多态清洗
        val_str = str(value)
        camel_to_snake = re.sub(r'([a-z])([A-Z])', r'\1_\2', val_str)
        norm_val = camel_to_snake.upper().replace(" ", "_").replace("-", "_")
        
        def get_sorted_tokens(s):
            return sorted([t for t in s.split('_') if t])
            
        norm_tokens = get_sorted_tokens(norm_val)
        
        best_match_ident = None
        best_match_score = 0.0

        for item in enum_items:
            # 提取双轨特征
            ident = item.identifier
            name = item.name
            
            # 特征清洗
            ident_clean = ident.upper()
            name_clean = name.upper().replace(" ", "_").replace("-", "_")
            
            # 优先级 1: 精确匹配 (涵盖了 identifier 和清洗后的 UI name)
            if norm_val == ident_clean or norm_val == name_clean:
                setattr(node, prop_name, ident)
                return True
                
            # 优先级 2: 词序无关匹配 (完美解决 AND_NOT <-> NOT_AND 的问题)
            ident_tokens = get_sorted_tokens(ident_clean)
            name_tokens = get_sorted_tokens(name_clean)
            
            if norm_tokens and (norm_tokens == ident_tokens or norm_tokens == name_tokens):
                setattr(node, prop_name, ident)
                return True
                
            # 记录用于优先级 3 (Difflib) 的最高分
            score_ident = difflib.SequenceMatcher(None, norm_val, ident_clean).ratio()
            score_name = difflib.SequenceMatcher(None, norm_val, name_clean).ratio()
            max_score = max(score_ident, score_name)
            
            if max_score > best_match_score:
                best_match_score = max_score
                best_match_ident = ident
                
        # 优先级 3: 终极模糊兜底
        if best_match_score >= 0.6 and best_match_ident:
            setattr(node, prop_name, best_match_ident)
            return True
            
        return False

# ==============================================================================
# 2. 终极插槽解析引擎
# ==============================================================================

class SocketResolver:
    @staticmethod
    def resolve_candidates(collection, name_or_ident, index=None):
        candidates = []
        
        if index is not None and 0 <= index < len(collection):
            candidates.append(collection[index])
            return candidates

        if not name_or_ident: return candidates

        for s in collection:
            if s.identifier == name_or_ident or s.name == name_or_ident:
                if s.bl_idname != 'NodeSocketVirtual' and s not in candidates:
                    candidates.append(s)

        if candidates: return candidates

        name_str = str(name_or_ident)
        name_upper = name_str.strip().upper()

        clean = re.sub(r'_\d+$', '', name_str).lower()
        for s in collection:
            if s.name.lower() == clean and s.bl_idname != 'NodeSocketVirtual' and s not in candidates:
                candidates.append(s)

        if candidates: return candidates

        if name_upper in {'A', 'B', 'C', 'D', 'X', 'Y', 'Z'}:
            idx_map = {'A': 0, 'X': 0, 'B': 1, 'Y': 1, 'C': 2, 'Z': 2, 'D': 3}
            valid_sockets = [s for s in collection if s.bl_idname != 'NodeSocketVirtual' and not s.hide and s.enabled]
            target_idx = idx_map[name_upper]
            if target_idx < len(valid_sockets):
                candidates.append(valid_sockets[target_idx])
            return candidates

        type_keywords = {
            "GEOMETRY": "NodeSocketGeometry", "VECTOR": "NodeSocketVector",
            "SHADER": "NodeSocketShader", "COLOR": "NodeSocketColor",
            "IMAGE": "NodeSocketImage", "OBJECT": "NodeSocketObject",
            "COLLECTION": "NodeSocketCollection", "MATERIAL": "NodeSocketMaterial",
            "STRING": "NodeSocketString", "ROTATION": "NodeSocketRotation", "MATRIX": "NodeSocketMatrix",
            "BOOLEAN": "NodeSocketBool", "BOOL": "NodeSocketBool",
            "INT": "NodeSocketInt", "INTEGER": "NodeSocketInt",
            "FLOAT": "NodeSocketFloat"
        }
        if name_upper in type_keywords:
            target_id = type_keywords[name_upper]
            for s in collection:
                if s.bl_idname == target_id and not s.hide and s.enabled and s not in candidates:
                    candidates.append(s)
        
        if candidates: return candidates

        generic_terms = {"VALUE", "RESULT", "OUTPUT", "INPUT", "DATA", "ANY"}
        if name_upper in generic_terms:
            for s in collection:
                if s.bl_idname != 'NodeSocketVirtual' and not s.hide and s.enabled and s not in candidates:
                    candidates.append(s)

        return candidates

# ==============================================================================
# 3. 节点恢复器
# ==============================================================================

class NodeRestorer:
    STRUCTURAL_KEYS = {
        'name', 'bl_idname', 'inputs', 'outputs', 'parent', 'links', 
        'properties', 'frames', 'nodes', 'tree_type', 'version',
        'simulation_state', 'repeat_state', 'bake_state', 
        'foreach_main', 'foreach_input', 'foreach_generation',
        'capture_items_data'
    }
    
    PROP_BLACKLIST = {
        'active_item', 'active_index', 'inspection_index', 'is_active_output', 
        'interface', 'node_tree', 'color_ramp', 'warning_propagation',
        'bl_label', 'bl_description', 'bl_icon', 'location', 'width', 'height',
        'active_input_index', 'active_main_index', 'active_generation_index',
        'show_options', 'show_preview', 'show_texture', 'shrink', 'label_size'
    }

    @staticmethod
    def restore_props(node, data):
        if 'label' in data: node.label = data['label']
        if 'mute' in data: node.mute = data['mute']
        if 'use_custom_color' in data: node.use_custom_color = data['use_custom_color']
        if 'color' in data: node.color = data['color']
        
        defined_props = data.get('properties', {})
        if not isinstance(defined_props, dict): defined_props = {}
        
        merged_props = defined_props.copy()
        for key, value in data.items():
            if key in NodeRestorer.STRUCTURAL_KEYS: continue
            if key in NodeRestorer.PROP_BLACKLIST: continue
            if key.startswith('<bpy_struct'): continue
            if key not in merged_props:
                merged_props[key] = value

        priority_keys = ['data_type', 'domain', 'domain_type', 'input_type']
        for p_key in priority_keys:
            if p_key in merged_props:
                SmartPropertySetter.set_property(node, p_key, merged_props[p_key])
                del merged_props[p_key]

        unassigned_props = {}
        for raw_prop_name, value in merged_props.items():
            if raw_prop_name in NodeRestorer.PROP_BLACKLIST: continue
            if isinstance(value, str) and value.startswith('<bpy_struct'): continue

            if isinstance(value, dict) and value.get('__type__') == 'ColorRamp':
                NodeRestorer._restore_color_ramp(node, raw_prop_name, value['data'])
                continue
            
            if raw_prop_name == "capture_items_data": continue

            success = SmartPropertySetter.set_property(node, raw_prop_name, value)
            if not success: unassigned_props[raw_prop_name] = value

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
    def _simulate_link_target(node, target_name, target_index, will_be_linked):
        candidates = SocketResolver.resolve_candidates(node.inputs, target_name, target_index)
        sock = candidates[0] if candidates else None
        
        if sock and sock in will_be_linked and target_index is None:
            original_name = sock.name
            for other_sock in node.inputs:
                if other_sock == sock: continue
                if other_sock.name == original_name and other_sock not in will_be_linked:
                    sock = other_sock; break
        return sock

    @staticmethod
    def restore_socket_defaults(node, inputs_data, node_name=None, links_data=None):
        if not isinstance(inputs_data, list): return
        
        will_be_linked = set()
        if node_name and links_data:
            incoming = [l for l in links_data if l.get('to_node') == node_name or l.get('dst') == node_name]
            for link in incoming:
                t_name = link.get('to_socket') or link.get('dst_sock')
                t_idx = link.get('to_socket_index') or link.get('dst_idx')
                target_sock = NodeRestorer._simulate_link_target(node, t_name, t_idx, will_be_linked)
                if target_sock:
                    will_be_linked.add(target_sock)

        assigned_sockets = set()
        
        for s_data in inputs_data:
            if not isinstance(s_data, dict): continue
            if s_data.get('identifier') == '__extend__' or s_data.get('bl_socket_idname') == 'NodeSocketVirtual': continue
            
            idx = s_data.get('index')
            ident = s_data.get('identifier')
            name = s_data.get('name')
            
            name_or_ident = ident or name
            candidates = SocketResolver.resolve_candidates(node.inputs, name_or_ident, idx)
            
            socket = None
            avail = [s for s in candidates if s not in will_be_linked and s not in assigned_sockets]
            if avail: 
                socket = avail[0]
            else:
                unassigned = [s for s in candidates if s not in assigned_sockets]
                if unassigned: 
                    socket = unassigned[0]
                elif candidates: 
                    socket = candidates[0]

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
                    elif socket.bl_idname in ('NodeSocketBool', 'NodeSocketBoolean') or socket.type == 'BOOLEAN':
                        socket.default_value = bool(val)
                    else:
                        socket.default_value = val
                except: pass
            
            if socket:
                if 'hide' in s_data: socket.hide = s_data['hide']
                if 'hide_value' in s_data: socket.hide_value = s_data['hide_value']
                assigned_sockets.add(socket)

# ==============================================================================
# 4. 反序列化主引擎
# ==============================================================================

class DeserializationEngine:
    def __init__(self, tree, context):
        self.tree = tree
        self.context = context
        self.node_map = {}
        self.deferred_props_map = {}
        self._valid_pairs = set()

    def deserialize_tree(self, json_data, offset=(0,0)):
        if not isinstance(json_data, dict): return []
        
        nodes_data = json_data.get("nodes", [])
        if not isinstance(nodes_data, list): nodes_data = []
        links_data = json_data.get("links", [])
        frames_data = json_data.get("frames", {})

        ordered_nodes = self._sort_priority(nodes_data)
        for n_data in ordered_nodes:
            if isinstance(n_data, dict):
                self._create_node_skeleton(n_data, offset)

        self._heal_topology(offset)
        self._pair_zones()

        for n_data in nodes_data:
            if not isinstance(n_data, dict): continue
            node = self.node_map.get(n_data.get('name'))
            if not node: continue
            
            if node.bl_idname == 'GeometryNodeGroup' and 'node_tree_name' in n_data:
                self._restore_node_tree_dependency(node, n_data)

            unassigned = NodeRestorer.restore_props(node, n_data)
            
            if unassigned:
                self._propagate_attributes(node, unassigned)

            props = n_data.get('properties', {})
            capture_items = n_data.get('capture_items_data') or props.get('capture_items_data')
            legacy_dt = n_data.get('data_type') or props.get('data_type')

            if capture_items:
                self._restore_capture_items(node, capture_items)
            elif legacy_dt and hasattr(node, 'capture_items'):
                self._adapt_legacy_capture_node(node, legacy_dt)

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

        for n_data in nodes_data:
            if not isinstance(n_data, dict): continue
            name = n_data.get('name')
            node = self.node_map.get(name)
            if not node: continue
            if 'inputs' in n_data: 
                NodeRestorer.restore_socket_defaults(node, n_data['inputs'], node_name=name, links_data=links_data)
            
            if 'outputs' in n_data:
                 for i, out in enumerate(n_data['outputs']):
                    if isinstance(out, dict) and i < len(node.outputs) and out.get('hide'): node.outputs[i].hide = True

        self._restore_links(links_data)
        
        final_frames = frames_data.copy() if isinstance(frames_data, dict) else {}
        for n_data in nodes_data:
            if isinstance(n_data, dict) and 'parent' in n_data:
                child = self.node_map.get(n_data.get('name'))
                parent = self.node_map.get(n_data.get('parent'))
                if child and parent: child.parent = parent
        self._restore_frames(final_frames)

        if hasattr(self.tree, "update_tag"): 
            try: self.tree.update_tag()
            except Exception as e: logger.warning(f"Final update_tag warning: {e}")

        for node in self.node_map.values(): node.select = True
        return list(self.node_map.values())

    def _pair_zones(self):
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
                try:
                    if hasattr(in_nodes[i], 'pair_with_output'):
                        in_nodes[i].pair_with_output(out_nodes[i])
                        self._valid_pairs.add(in_nodes[i].name)
                        self._valid_pairs.add(out_nodes[i].name)
                except Exception as e: 
                    logger.warning(f"Zone pairing failed: {e}")

    def _propagate_attributes(self, source_node, props_dict):
        partner = getattr(source_node, "paired_output", None)
        if partner:
            for p_name, p_val in props_dict.items(): SmartPropertySetter.set_property(partner, p_name, p_val)

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
        bl_idname = n_data.get('bl_idname', 'NodeFrame')
        orig_name = n_data.get('name')
        
        try: 
            node = self.tree.nodes.new(bl_idname)
        except: 
            node = self.tree.nodes.new("NodeFrame")
            node.label = f"MISSING: {bl_idname}"
        
        if orig_name:
            node.name = orig_name 
        else:
            orig_name = node.name
            n_data['name'] = orig_name
            
        self.node_map[orig_name] = node
        
        loc = n_data.get('location')
        if loc and isinstance(loc, (list, tuple)) and len(loc) >= 2:
            node.location = (loc[0] + offset[0], loc[1] + offset[1])
        else:
            idx = len(self.node_map)
            node.location = (offset[0] + (idx * 200), offset[1] - (idx * 50))
        
        if 'width' in n_data: node.width = n_data['width']
        if 'height' in n_data: node.height = n_data['height']

    def _restore_foreach_stats(self, node, n_data):
        if node.name not in self._valid_pairs: return
        
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
        if node.name not in self._valid_pairs: return
        
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
        
        dead_links = []
        connected_sources = set()
        connected_destinations = set()
        
        for link in links_data:
            if not isinstance(link, dict): continue
            
            src_name = link.get('src') or link.get('from_node')
            dst_name = link.get('dst') or link.get('to_node')
            
            src = self.node_map.get(src_name)
            if not src and src_name in self.tree.nodes:
                src = self.tree.nodes.get(src_name)
                
            dst = self.node_map.get(dst_name)
            if not dst and dst_name in self.tree.nodes:
                dst = self.tree.nodes.get(dst_name)
            
            if src and dst:
                if self._create_single_link(src, dst, link):
                    connected_sources.add(src.name)
                    connected_destinations.add(dst.name)
            elif not src and dst:
                dead_links.append(link)
                connected_destinations.add(dst.name)
                
        if dead_links:
            self._heal_dead_links(dead_links, connected_sources, connected_destinations)

    def _create_single_link(self, src, dst, link):
        from_sock_name = link.get('src_sock') or link.get('from_socket')
        to_sock_name = link.get('dst_sock') or link.get('to_socket')
        
        from_idx = link.get('src_idx') or link.get('from_socket_index')
        to_idx = link.get('dst_idx') or link.get('to_socket_index')

        candidates_src = SocketResolver.resolve_candidates(src.outputs, from_sock_name, from_idx)
        from_sock = candidates_src[0] if candidates_src else None
        
        candidates_dst = SocketResolver.resolve_candidates(dst.inputs, to_sock_name, to_idx)
        to_sock = candidates_dst[0] if candidates_dst else None

        if not from_sock and len(src.outputs) > 0:
             from_sock = next((s for s in src.outputs if not s.hide and s.enabled and s.bl_idname != 'NodeSocketVirtual'), None)

        if to_sock and to_sock.is_linked and to_idx is None:
            original_name = to_sock.name
            for other_sock in dst.inputs:
                if other_sock == to_sock: continue
                if other_sock.name == original_name and not other_sock.is_linked:
                    to_sock = other_sock
                    break

        if from_sock and to_sock:
            try: 
                self.tree.links.new(from_sock, to_sock)
                return True
            except: pass
        return False

    def _heal_dead_links(self, dead_links, connected_sources, connected_destinations):
        for link in dead_links:
            dst_name = link.get('dst') or link.get('to_node')
            dst = self.node_map.get(dst_name) or self.tree.nodes.get(dst_name)
            if not dst: continue
            
            candidates = [n for n in self.node_map.values() if n.name not in connected_sources and len(n.outputs) > 0]
            if not candidates: continue
            
            best_candidate = None
            best_score = -1
            
            for cand in candidates:
                score = 0
                if cand.name not in connected_destinations: score += 10 
                if "Input" in cand.bl_idname or "Info" in cand.bl_idname or "Time" in cand.bl_idname: score += 5
                
                if score > best_score:
                    best_score = score
                    best_candidate = cand
                    
            if best_candidate:
                if self._create_single_link(best_candidate, dst, link):
                    connected_sources.add(best_candidate.name)
                    logger.info(f"Auto-Healed hallucinated link using orphan node: {best_candidate.name}")

    def _restore_frames(self, frames_data):
        if not isinstance(frames_data, dict): return
        for child_name, parent_name in frames_data.items():
            child = self.node_map.get(child_name)
            parent = self.node_map.get(parent_name)
            if child and parent: child.parent = parent