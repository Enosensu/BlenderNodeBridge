# core/deserializer.py
# BlenderNodeBridge v5.14.159 (Omega Armor - Context Shield)
# 机制优化: 增加对 AI 超紧凑 Dict 格式 inputs 的泛化支持。
# 核心修复: [Context Shield] 引入跨域侦测协议。当用户将 Shader 贴入 GeoNodes 时，精准拦截无意义的前缀试探，并暴露明确的 "Context Mismatch" 标签，防止误导。
# 核心修复: [Permutation Trial] 突破 Blender 懒加载陷阱，强行唤醒未加载类。
# 核心修复: [Global Anagram Rescue] 内存反射 Jaccard 兜底。
# 核心修复: [Semantic Supremacy] 确立语义绝对优先原则。
# 核心修复: [Atomic Assignment] 安全分量遍历写入，穿透严格类型检查。

import bpy
import logging
import difflib
import re
import itertools
from mathutils import Vector, Euler, Matrix, Color, Quaternion

from . import node_mappings
from .node_mappings import TextSmartEngine, SocketTypeResolver

logger = logging.getLogger("BlenderNodeBridge.deserializer")

# ==============================================================================
# 1. 智能属性设置器
# ==============================================================================

class SmartPropertySetter:
    @staticmethod
    def resolve_prop_name(node, prop_name):
        if hasattr(node, prop_name): return prop_name
            
        norm_prop = str(prop_name).lower().replace(" ", "").replace("_", "")
        
        semantic_aliases = {
            'mode': ['operation'],
            'operation': ['mode'],
            'inputtype': ['data_type', 'type'],
            'datatype': ['input_type', 'type'],
            'domaintype': ['domain'],
            'domain': ['domain_type'],
            'type': ['data_type', 'input_type']
        }
        
        if norm_prop in semantic_aliases:
            for alias in semantic_aliases[norm_prop]:
                if hasattr(node, alias):
                    return alias

        if hasattr(node, "bl_rna"):
            best_match = None
            best_diff = 999
            for rna_key in node.bl_rna.properties.keys():
                norm_rna = str(rna_key).lower().replace(" ", "").replace("_", "")
                if norm_prop == norm_rna or norm_prop in norm_rna or norm_rna in norm_prop:
                    diff = abs(len(rna_key) - len(str(prop_name)))
                    if diff < best_diff:
                        best_diff = diff
                        best_match = rna_key
            if best_match: return best_match
            
        return prop_name

    @staticmethod
    def set_property(node, prop_name, value):
        real_prop_name = SmartPropertySetter.resolve_prop_name(node, prop_name)
        if not hasattr(node, real_prop_name): return False 

        try:
            rna_prop = node.bl_rna.properties.get(real_prop_name)
            if rna_prop and rna_prop.is_readonly: return True

            if rna_prop and rna_prop.type == 'ENUM' and isinstance(value, str):
                return SmartPropertySetter._set_enum_smart(node, real_prop_name, value, rna_prop)

            current = getattr(node, real_prop_name)
            if isinstance(current, (Vector, Color, Euler)) and isinstance(value, (list, tuple)):
                if isinstance(current, Color) and len(value) == 3: value = list(value) + [1.0]
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
    def _set_enum_smart(node, prop_name, value, rna_prop):
        valid_items = [item.identifier for item in rna_prop.enum_items]
        val_str = str(value)
        val_upper = val_str.upper()
        
        if val_upper in valid_items: 
            setattr(node, prop_name, val_upper); return True
        if val_str in valid_items:
            setattr(node, prop_name, val_str); return True

        aliases = {
            "FLOAT_VECTOR": "VECTOR",
            "FLOAT_COLOR": "COLOR",
            "RGBA": "COLOR",
            "BOOL": "BOOLEAN",
            "BOOLEAN": "BOOL"
        }
        if val_upper in aliases:
            alias_target = aliases[val_upper]
            if alias_target in valid_items:
                setattr(node, prop_name, alias_target); return True
            if val_upper == "VECTOR" and "FLOAT_VECTOR" in valid_items:
                setattr(node, prop_name, "FLOAT_VECTOR"); return True
                
        best_match_ident = None
        best_match_score = 0.0
        norm_val = TextSmartEngine.clean_polymorphic(value)

        for item in rna_prop.enum_items:
            if TextSmartEngine.match_strict(value, item.identifier) or TextSmartEngine.match_strict(value, item.name):
                setattr(node, prop_name, item.identifier); return True
            
            val_tokens = TextSmartEngine.get_tokens(value)
            ident_tokens = TextSmartEngine.get_tokens(item.identifier)
            if val_tokens and ident_tokens and (val_tokens.issubset(ident_tokens) or ident_tokens.issubset(val_tokens)):
                score = 0.8 - (abs(len(val_tokens) - len(ident_tokens)) * 0.1)
                if score > best_match_score:
                    best_match_score = score
                    best_match_ident = item.identifier
                
            ident_clean = TextSmartEngine.clean_polymorphic(item.identifier)
            name_clean = TextSmartEngine.clean_polymorphic(item.name)
            score_ident = difflib.SequenceMatcher(None, norm_val, ident_clean).ratio()
            score_name = difflib.SequenceMatcher(None, norm_val, name_clean).ratio()
            
            max_score = max(score_ident, score_name)
            if max_score > best_match_score:
                best_match_score = max_score
                best_match_ident = item.identifier
                
        if best_match_score >= 0.6 and best_match_ident:
            setattr(node, prop_name, best_match_ident); return True
            
        return False


# ==============================================================================
# 2. 终极插槽解析引擎
# ==============================================================================

class SocketResolver:
    @staticmethod
    def _prioritize_active(candidates):
        if not candidates:
            return candidates
        return sorted(
            candidates, 
            key=lambda s: (getattr(s, 'enabled', True), not getattr(s, 'hide', False)), 
            reverse=True
        )

    @staticmethod
    def resolve_candidates(collection, name_or_ident, index=None, orig_name=None):
        candidates = []
        node = collection[0].node if len(collection) > 0 else None
        is_reroute = node and node.bl_idname == 'NodeReroute'

        def is_valid_socket(s):
            if s.bl_idname == 'NodeSocketVirtual' and not is_reroute: return False
            if getattr(s, 'type', '') == 'MENU': return False
            return s not in candidates

        name_str = str(name_or_ident).strip() if name_or_ident else ""

        if index is not None:
            target_sock = None
            logical_sockets = [s for s in collection if is_valid_socket(s)]
            if 0 <= index < len(logical_sockets):
                target_sock = logical_sockets[index]
            elif 0 <= index < len(collection):
                target_sock = collection[index]
                
            if target_sock and is_valid_socket(target_sock):
                if name_str:
                    match_name = (target_sock.name == name_str or target_sock.identifier == name_str)
                    if not match_name:
                        has_perfect_match = any((s.name == name_str or s.identifier == name_str) and is_valid_socket(s) for s in collection)
                        if has_perfect_match:
                            target_sock = None 
                
                if target_sock:
                    candidates.append(target_sock)
                    return SocketResolver._prioritize_active(candidates)

        if not name_or_ident: return candidates

        if node and orig_name:
            is_dynamic = any(x in node.bl_idname for x in ['Group', 'Simulation', 'Repeat', 'Bake', 'Foreach'])
            if is_dynamic:
                orig_name_str = str(orig_name).strip()
                for s in collection:
                    if s.name == orig_name_str and is_valid_socket(s):
                        candidates.append(s)
                if candidates: return SocketResolver._prioritize_active(candidates)

        for s in collection:
            if (s.identifier == name_str or s.name == name_str) and is_valid_socket(s):
                candidates.append(s)

        if candidates: return SocketResolver._prioritize_active(candidates)

        for s in collection:
            if not is_valid_socket(s): continue
            if (TextSmartEngine.match_loose(name_str, s.name) or 
                TextSmartEngine.match_loose(name_str, s.identifier) or 
                TextSmartEngine.match_loose(name_str, getattr(s, 'label', '')) or
                TextSmartEngine.match_loose(name_str, s.bl_idname)):
                candidates.append(s)

        if candidates: return SocketResolver._prioritize_active(candidates)

        name_upper = name_str.upper()
        if name_upper in {'A', 'B', 'C', 'D', 'X', 'Y', 'Z'}:
            idx_map = {'A': 0, 'X': 0, 'B': 1, 'Y': 1, 'C': 2, 'Z': 2, 'D': 3}
            valid_sockets = [s for s in collection if is_valid_socket(s) and getattr(s, 'enabled', True)]
            target_idx = idx_map[name_upper]
            if target_idx < len(valid_sockets):
                candidates.append(valid_sockets[target_idx])
            return candidates

        guessed_type = node_mappings.get_socket_class_name(name_str)
        if guessed_type:
            for s in collection:
                if s.bl_idname == guessed_type and getattr(s, 'enabled', True) and is_valid_socket(s):
                    candidates.append(s)
                    
        if candidates: return SocketResolver._prioritize_active(candidates)

        generic_terms = {"VALUE", "RESULT", "OUTPUT", "INPUT", "DATA", "ANY", "ATTRIBUTE"}
        if name_upper in generic_terms:
            data_sockets = []
            geo_sockets = []
            for s in collection:
                if is_valid_socket(s) and getattr(s, 'enabled', True):
                    if s.type in {'GEOMETRY', 'OBJECT', 'COLLECTION', 'MATERIAL', 'TEXTURE', 'IMAGE'}:
                        geo_sockets.append(s)
                    else:
                        data_sockets.append(s)
            
            if data_sockets:
                candidates.extend(data_sockets)
            else:
                candidates.extend(geo_sockets)

        return SocketResolver._prioritize_active(candidates)


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
        'show_options', 'show_preview', 'show_texture', 'shrink', 'label_size',
        'socket_idname'
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

        priority_keys = ['data_type', 'domain', 'domain_type', 'input_type', 'type']
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
        normalized_inputs = []
        if isinstance(inputs_data, dict):
            for k, v in inputs_data.items():
                k_str = str(k)
                normalized_inputs.append({'identifier': k_str, 'name': k_str, 'default_value': v})
        elif isinstance(inputs_data, list):
            normalized_inputs = inputs_data
        else:
            return
            
        will_be_linked = set()
        if node_name and links_data:
            incoming = [l for l in links_data if l.get('to_node') == node_name or l.get('dst') == node_name]
            for link in incoming:
                t_name = link.get('dst_sock') if link.get('dst_sock') is not None else link.get('to_socket')
                t_idx = link.get('dst_idx') if link.get('dst_idx') is not None else link.get('to_socket_index')
                
                target_sock = NodeRestorer._simulate_link_target(node, t_name, t_idx, will_be_linked)
                if target_sock:
                    will_be_linked.add(target_sock)

        assigned_sockets = set()
        
        for s_data in normalized_inputs:
            if not isinstance(s_data, dict): continue
            
            is_virtual_allowed = (node.bl_idname == 'NodeReroute')
            if s_data.get('identifier') == '__extend__' or (not is_virtual_allowed and s_data.get('bl_socket_idname') == 'NodeSocketVirtual'): 
                continue
            
            idx = s_data.get('index')
            ident = s_data.get('identifier')
            name = s_data.get('name')
            
            name_or_ident = ident or name
            candidates = SocketResolver.resolve_candidates(node.inputs, name_or_ident, idx, orig_name=name)
            
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
                            
                    elif getattr(socket, 'type', '') in {'VECTOR', 'ROTATION'} or 'Vector' in socket.bl_idname:
                        if isinstance(val, (list, tuple)):
                            try:
                                for i in range(min(len(val), len(socket.default_value))):
                                    socket.default_value[i] = float(val[i])
                            except TypeError:
                                socket.default_value = tuple(float(x) for x in val)
                        else:
                            socket.default_value = val
                            
                    elif getattr(socket, 'type', '') == 'RGBA' or 'Color' in socket.bl_idname:
                        if isinstance(val, (list, tuple)):
                            v_list = list(val)
                            if len(v_list) == 3: v_list.append(1.0)
                            try:
                                for i in range(min(len(v_list), len(socket.default_value))):
                                    socket.default_value[i] = float(v_list[i])
                            except TypeError:
                                socket.default_value = tuple(float(x) for x in v_list)
                        else:
                            socket.default_value = val
                            
                    elif getattr(socket, 'type', '') == 'BOOLEAN' or 'Bool' in socket.bl_idname:
                        socket.default_value = bool(val)
                        
                    else:
                        socket.default_value = val
                        
                except Exception as e:
                    logger.warning(f"⚠️ [Data Restore] Failed to set '{socket.name}' default_value to {val}: {e}")
            
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
        self.raw_nodes_map = {}
        self.deferred_props_map = {}
        self._valid_pairs = set()
        
        # 👑 [Context Shield] 跨域上下文侦测
        self.active_tree_type = tree.bl_idname
        self.source_tree_type = None 
        self.is_cross_domain = False

    def deserialize_tree(self, json_data, offset=(0,0)):
        if not isinstance(json_data, dict): return []
        
        # 初始化跨域状态
        self.source_tree_type = json_data.get("tree_type", self.active_tree_type)
        if self.source_tree_type and self.source_tree_type != self.active_tree_type:
            self.is_cross_domain = True
            logger.warning(f"⚠️ [Context Mismatch] Pasting {self.source_tree_type} into {self.active_tree_type}!")
        
        nodes_data = json_data.get("nodes", [])
        if not isinstance(nodes_data, list): nodes_data = []
        
        for n in nodes_data:
            if isinstance(n, dict) and n.get('name'):
                self.raw_nodes_map[n['name']] = n
                
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

            self._radar_restore_collections(node, n_data)

        self._force_topology_refresh() 

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

    def _force_topology_refresh(self):
        try:
            if hasattr(self.tree, "update_tag"):
                self.tree.update_tag()
            
            has_zone = any(
                "Simulation" in n.bl_idname or 
                "Repeat" in n.bl_idname or 
                "Bake" in n.bl_idname or
                "Foreach" in n.bl_idname or
                "Mix" in n.bl_idname or
                "Math" in n.bl_idname or
                "Switch" in n.bl_idname
                for n in self.node_map.values()
            )
            
            if has_zone and self.context:
                if hasattr(self.context, "view_layer") and hasattr(self.context.view_layer, "update"):
                    self.context.view_layer.update()
                
                logger.debug("⚡ [Pulse-Sync] Forced topology refresh for dynamic sockets.")
        except Exception as e:
            logger.warning(f"⚡ [Pulse-Sync] Refresh warning: {e}")

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
                except Exception as e: pass

    def _propagate_attributes(self, source_node, props_dict):
        partner = getattr(source_node, "paired_output", None)
        if partner:
            for p_name, p_val in props_dict.items(): SmartPropertySetter.set_property(partner, p_name, p_val)

    def _restore_node_tree_dependency(self, node, n_data):
        tree_name = n_data.get('node_tree_name')
        if not tree_name: return
        target_tree = bpy.data.node_groups.get(tree_name)

        is_new_tree = False
        if not target_tree:
            try:
                target_tree = bpy.data.node_groups.new(tree_name, 'GeometryNodeTree')
                is_new_tree = True
            except Exception as e:
                logger.warning(f"Failed to create node tree {tree_name}: {e}")
                return

        if target_tree:
            for direction in ['inputs', 'outputs']:
                if direction in n_data:
                    for s_data in n_data[direction]:
                        s_name = s_data.get('name', 'Socket')
                        raw_type = s_data.get('bl_socket_idname') or s_data.get('type') or 'NodeSocketFloat'
                        s_type = raw_type if str(raw_type).startswith('NodeSocket') else 'NodeSocketFloat'

                        exists = False
                        if hasattr(target_tree, "interface"):
                            in_out = direction[:-1].upper()
                            for item in target_tree.interface.items_tree:
                                if item.item_type == 'SOCKET' and item.name == s_name and item.in_out == in_out:
                                    exists = True
                                    break
                            if not exists:
                                try: target_tree.interface.new_socket(name=s_name, in_out=in_out, socket_type=s_type)
                                except: pass
                        else:
                            collection = getattr(target_tree, direction)
                            for s in collection:
                                if s.name == s_name:
                                    exists = True
                                    break
                            if not exists:
                                try: collection.new(s_type, s_name)
                                except: pass

            if is_new_tree or len(target_tree.nodes) == 0:
                try:
                    if 'Group Input' not in target_tree.nodes:
                        in_node = target_tree.nodes.new('NodeGroupInput')
                        in_node.location = (-200, 0)
                    if 'Group Output' not in target_tree.nodes:
                        out_node = target_tree.nodes.new('NodeGroupOutput')
                        out_node.location = (200, 0)
                except Exception as e:
                    logger.warning(f"Failed to populate internal IO nodes: {e}")

            node.node_tree = target_tree

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
        for col_name in ['main_items', 'input_items', 'generation_items', 'state_items', 'repeat_items', 'bake_items']:
            if hasattr(ref_node, col_name) and hasattr(ghost_node, col_name):
                src = getattr(ref_node, col_name)
                dst = getattr(ghost_node, col_name)
                
                if callable(src) or callable(dst): continue
                
                try: dst.clear()
                except: pass
                
                for item in src:
                    s_type = getattr(item, 'socket_type', 'FLOAT')
                    self._robust_new_item(dst, s_type, item.name)

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

    def _global_rescue_node_class(self, raw_idname):
        """【终极防线】全局异位词重组与活体试探 (Anagram Permutation & Reflection)"""
        # 1. 突破懒加载陷阱：主动异位词排列试探
        parts = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|\d+', raw_idname)
        prefix_words = []
        core_words = []
        for p in parts:
            if p.lower() in {'geometry', 'node', 'shader', 'compositor', 'texture', 'function'}:
                prefix_words.append(p)
            else:
                core_words.append(p)
                
        # 👑 [Context Shield] 跨域保护：禁止盲目替换互斥域前缀
        is_strictly_exclusive = 'Bsdf' in core_words or 'OutputMaterial' in raw_idname
        
        if 0 < len(core_words) <= 4:
            prefix_str = "".join(prefix_words)
            if not prefix_str and not is_strictly_exclusive: 
                if self.active_tree_type == 'GeometryNodeTree': prefix_str = "GeometryNode"
                elif self.active_tree_type == 'ShaderNodeTree': prefix_str = "ShaderNode"
                
            for perm in itertools.permutations(core_words):
                test_id = prefix_str + "".join(perm)
                if test_id != raw_idname:
                    try:
                        test_node = self.tree.nodes.new(test_id)
                        real_id = test_node.bl_idname
                        self.tree.nodes.remove(test_node) 
                        return real_id
                    except Exception:
                        pass

        # 2. 内存反射 Jaccard 兜底
        all_node_types = set()
        def _scan_subs(cls):
            for sub in cls.__subclasses__():
                if hasattr(sub, 'bl_idname'):
                    all_node_types.add(sub.bl_idname)
                _scan_subs(sub)
        _scan_subs(bpy.types.Node)

        def _tokenize(name):
            words = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|\d+', name)
            ignore = {"geometry", "node", "shader", "compositor", "texture", "function"}
            stemmed = set()
            for w in words:
                wl = w.lower()
                if wl in ignore: continue
                if wl.endswith('s') and len(wl) > 3: wl = wl[:-1]
                stemmed.add(wl)
            return stemmed

        raw_tokens = _tokenize(raw_idname)
        best_match = None
        best_score = 0.0
        
        for n_type in all_node_types:
            type_tokens = _tokenize(n_type)
            if not raw_tokens or not type_tokens: continue
            
            intersection = raw_tokens.intersection(type_tokens)
            union = raw_tokens.union(type_tokens)
            jaccard = len(intersection) / len(union) if union else 0.0
            
            if jaccard == 1.0: 
                return n_type
            
            seq_score = difflib.SequenceMatcher(None, raw_idname.lower(), n_type.lower()).ratio()
            score = max(jaccard, seq_score)
            
            if score > best_score:
                best_score = score
                best_match = n_type
                
        if best_score > 0.65:
            return best_match
            
        return None

    def _create_node_skeleton(self, n_data, offset):
        raw_idname = n_data.get('bl_idname', 'NodeFrame')
        
        # 截获原始名称，用于精准暴露错误信息
        original_idname = raw_idname 
        
        candidates = node_mappings.resolve_node_idname_candidates(raw_idname)
        
        node = None
        for test_id in candidates:
            try:
                node = self.tree.nodes.new(test_id)
                if test_id != raw_idname and test_id != candidates[0]:
                    logger.info(f"⚡ [Armor Rebuild] Rescued namespace hallucination: {raw_idname} -> {test_id}")
                break
            except:
                pass
                
        if not node:
            rescued_id = self._global_rescue_node_class(raw_idname)
            if rescued_id:
                try:
                    node = self.tree.nodes.new(rescued_id)
                    logger.info(f"🦸‍♂️ [Global Rescue] Forged hallucinated class {raw_idname} into {rescued_id}")
                except Exception as e:
                    pass
        
        # 👑 [Context Shield] 针对跨域粘贴的精准失败暴露
        if not node:
            node = self.tree.nodes.new("NodeFrame")
            if self.is_cross_domain:
                node.label = f"MISSING (Context Mismatch): {original_idname}"
            else:
                node.label = f"MISSING: {original_idname}"
            n_data['label'] = node.label
            n_data['use_custom_color'] = True
            n_data['color'] = (1.0, 0.2, 0.2)
            n_data['width'] = 260.0
            n_data['height'] = 100.0
            logger.warning(f"❌ Failed to create node {original_idname} after exhausting all rescue protocols.")
        
        orig_name = n_data.get('name')
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

    # --------------------------------------------------------------------------
    # 核心装甲防御区 (Armor Defense Mechanisms)
    # --------------------------------------------------------------------------

    def _radar_restore_collections(self, node, n_data):
        radar_map = {
            'capture_items_data': 'capture_items',
            'simulation_state': 'state_items',
            'repeat_state': 'repeat_items',
            'bake_state': 'bake_items',
            'foreach_main': 'main_items',
            'foreach_input': 'input_items',
            'foreach_generation': 'generation_items'
        }
        
        n_data_virtual = n_data.copy()
        props = n_data_virtual.get('properties', {})
        if 'capture_items_data' in props:
            n_data_virtual['capture_items_data'] = props['capture_items_data']

        if 'capture_items_data' not in n_data_virtual and hasattr(node, 'capture_items') and not callable(getattr(node, 'capture_items')):
            legacy_dt = n_data_virtual.get('data_type') or props.get('data_type')
            if legacy_dt:
                self._adapt_legacy_capture_node(node, legacy_dt)
                return

        for json_key, col_alias in radar_map.items():
            if json_key in n_data_virtual:
                items_data = n_data_virtual[json_key]
                if isinstance(items_data, dict): 
                    items_data = items_data.get('items', [])
                
                target_nodes = [node]
                
                if 'Input' in node.bl_idname and hasattr(node, 'paired_output') and node.paired_output:
                    if node.paired_output not in target_nodes:
                        target_nodes.insert(0, node.paired_output)
                elif 'Output' in node.bl_idname:
                    for sibling in self.node_map.values():
                        if 'Input' in sibling.bl_idname and getattr(sibling, 'paired_output', None) == node:
                            if sibling not in target_nodes:
                                target_nodes.append(sibling)
                            break
                
                for t_node in target_nodes:
                    target_col_name = None
                    if hasattr(t_node, col_alias) and not callable(getattr(t_node, col_alias)):
                        target_col_name = col_alias
                    else:
                        fallback_cols = ['repeat_items', 'state_items', 'bake_items', 'capture_items', 'main_items', 'input_items', 'generation_items']
                        for fc in fallback_cols:
                            if hasattr(t_node, fc) and not callable(getattr(t_node, fc)):
                                target_col_name = fc
                                break
                    
                    if target_col_name:
                        collection = getattr(t_node, target_col_name)
                        self._scorched_earth_rebuild(collection, items_data)

    def _scorched_earth_rebuild(self, collection, items_data):
        if not isinstance(items_data, list): return
        
        try:
            collection.clear()
        except Exception:
            try:
                while len(collection) > 0: 
                    collection.remove(collection[0])
            except Exception: pass

        for item in items_data:
            name = "Value"
            raw_type = "FLOAT"
            if isinstance(item, str):
                name = item
            elif isinstance(item, dict):
                name = item.get('name', 'Value')
                raw_type = item.get('data_type') or item.get('socket_type') or item.get('bl_socket_idname') or 'FLOAT'
            
            self._robust_new_item(collection, raw_type, name)

    def _robust_new_item(self, collection, raw_type, name):
        api_type = node_mappings.get_api_enum(raw_type)
        fallbacks = [api_type]
        
        target_upper = str(raw_type).upper()
        if "COLOR" in target_upper or "RGBA" in target_upper:
            fallbacks.extend(['FLOAT_COLOR', 'COLOR', 'RGBA', 'FLOAT'])
        elif "VECTOR" in target_upper:
            fallbacks.extend(['FLOAT_VECTOR', 'VECTOR', 'FLOAT'])
        elif "INT" in target_upper:
            fallbacks.extend(['INT', 'FLOAT'])
        
        fallbacks.extend(['FLOAT', 'GEOMETRY'])
        
        for f_type in fallbacks:
            try:
                item = collection.new(f_type, name)
                if item: return item
            except Exception:
                pass
        return None

    def _adapt_legacy_capture_node(self, node, data_type_str):
        try:
            try: node.capture_items.clear()
            except: pass
            
            api_type = node_mappings.get_api_enum(data_type_str)
            self._robust_new_item(node.capture_items, api_type, "Attribute")
        except: pass

    # --------------------------------------------------------------------------
    # 连接恢复器 
    # --------------------------------------------------------------------------

    @staticmethod
    def _is_type_compatible(sock_a, sock_b):
        if not sock_a or not sock_b: return False
        
        if sock_a.bl_idname == 'NodeSocketVirtual' or sock_b.bl_idname == 'NodeSocketVirtual': return True
        
        type_a = getattr(sock_a, 'type', 'CUSTOM')
        type_b = getattr(sock_b, 'type', 'CUSTOM')
        
        if type_a == type_b: return True
        
        isolated_types = {'GEOMETRY', 'STRING', 'OBJECT', 'COLLECTION', 'IMAGE', 'TEXTURE', 'MATERIAL'}
        if type_a in isolated_types or type_b in isolated_types:
            return False 
            
        return True 

    def _enforce_type_harmony(self, src, dst, candidates_src, candidates_dst):
        from_sock = candidates_src[0] if candidates_src else None
        to_sock = candidates_dst[0] if candidates_dst else None
        
        if from_sock and not to_sock:
            for d in dst.inputs:
                if getattr(d, 'enabled', True) and not getattr(d, 'hide', False) and not d.is_linked and self._is_type_compatible(from_sock, d):
                    logger.info(f"⚡ [Type Harmony] Rescued missing target socket: {src.name}[{from_sock.name}] -> {dst.name}[{d.name}]")
                    return from_sock, d
                    
        if from_sock and to_sock and not self._is_type_compatible(from_sock, to_sock):
            logger.info(f"⚡ [Type Harmony] Intercepted illegal link: {src.name}[{from_sock.name}] -> {dst.name}[{to_sock.name}]")
            
            rescued_from = None
            rescued_to = None
            
            for s in src.outputs:
                if getattr(s, 'enabled', True) and not getattr(s, 'hide', False) and self._is_type_compatible(s, to_sock):
                    rescued_from = s
                    rescued_to = to_sock
                    break
                    
            if not rescued_from:
                for d in dst.inputs:
                    if getattr(d, 'enabled', True) and not getattr(d, 'hide', False) and not d.is_linked and self._is_type_compatible(from_sock, d):
                        rescued_from = from_sock
                        rescued_to = d
                        break
                        
            if rescued_from and rescued_to:
                logger.info(f"   [Rescued]: Re-routed to {src.name}[{rescued_from.name}] -> {dst.name}[{rescued_to.name}]")
                return rescued_from, rescued_to
                
        return from_sock, to_sock

    def _restore_links(self, links_data):
        if not isinstance(links_data, list): return
        
        dead_links = []
        connected_sources = set()
        connected_destinations = set()
        
        for link in links_data:
            if not isinstance(link, dict): continue
            
            src_name = link.get('src') if link.get('src') is not None else link.get('from_node')
            dst_name = link.get('dst') if link.get('dst') is not None else link.get('to_node')
            
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
        from_sock_ident = link.get('src_sock') if link.get('src_sock') is not None else link.get('from_socket')
        to_sock_ident = link.get('dst_sock') if link.get('dst_sock') is not None else link.get('to_socket')
        
        from_idx = link.get('src_idx') if link.get('src_idx') is not None else link.get('from_socket_index')
        to_idx = link.get('dst_idx') if link.get('dst_idx') is not None else link.get('to_socket_index')

        src_orig_name = link.get('src') if link.get('src') is not None else link.get('from_node')
        dst_orig_name = link.get('dst') if link.get('dst') is not None else link.get('to_node')

        src_data = self.raw_nodes_map.get(src_orig_name)
        if not src_data: src_data = self.raw_nodes_map.get(src.name, {})

        dst_data = self.raw_nodes_map.get(dst_orig_name)
        if not dst_data: dst_data = self.raw_nodes_map.get(dst.name, {})
        
        def get_orig_name(node_data, ident):
            if not node_data: return None
            for s in node_data.get('outputs', []) + node_data.get('inputs', []):
                if s.get('identifier') == ident:
                    return s.get('name')
            return None

        from_orig_name = get_orig_name(src_data, from_sock_ident)
        to_orig_name = get_orig_name(dst_data, to_sock_ident)

        candidates_src = SocketResolver.resolve_candidates(src.outputs, from_sock_ident, from_idx, orig_name=from_orig_name)
        candidates_dst = SocketResolver.resolve_candidates(dst.inputs, to_sock_ident, to_idx, orig_name=to_orig_name)
        
        from_sock, to_sock = self._enforce_type_harmony(src, dst, candidates_src, candidates_dst)

        if not from_sock and len(src.outputs) > 0:
             is_src_reroute = src.bl_idname == 'NodeReroute'
             from_sock = next((s for s in src.outputs if not getattr(s, 'hide', False) and getattr(s, 'enabled', True) and (s.bl_idname != 'NodeSocketVirtual' or is_src_reroute)), None)

        if to_sock and to_sock.is_linked and to_idx is None:
            original_name = to_sock.name
            for other_sock in dst.inputs:
                if other_sock == to_sock: continue
                if other_sock.name == original_name and not other_sock.is_linked:
                    to_sock = other_sock
                    break

        if not to_sock and "Simulation" in dst.bl_idname:
            logger.warning(f"❌ [Link-Trace] Failed to find target socket on {dst.name}")
            logger.warning(f"   Target: '{to_sock_ident}' (Index: {to_idx})")
            logger.warning(f"   Available Sockets: {[s.name for s in dst.inputs]}")

        if from_sock and to_sock:
            try: 
                self.tree.links.new(from_sock, to_sock)
                return True
            except Exception as e:
                logger.warning(f"⚠️ Blender Refused Link: {src.name} -> {dst.name} ({e})")
                pass
        return False

    def _heal_dead_links(self, dead_links, connected_sources, connected_destinations):
        for link in dead_links:
            dst_name = link.get('dst') if link.get('dst') is not None else link.get('to_node')
            dst = self.node_map.get(dst_name) or self.tree.nodes.get(dst_name)
            if not dst: continue
            
            candidates = [n for n in self.node_map.values() if n.name not in connected_sources and len(n.outputs) > 0]
            if not candidates: continue
            
            best_candidate = None
            best_score = -1
            
            src_name_hint = link.get('src') if link.get('src') is not None else link.get('from_node')
            if not src_name_hint: continue

            hint_lower = src_name_hint.lower()

            for cand in candidates:
                cand_name_lower = cand.name.lower()
                
                is_versioned_name = cand_name_lower.startswith(hint_lower + ".")
                is_contained = hint_lower in cand_name_lower
                
                if is_versioned_name or is_contained:
                    sim_score = 0.9
                else:
                    sim_score = difflib.SequenceMatcher(None, hint_lower, cand_name_lower).ratio()
                
                if sim_score < 0.5: continue

                score = 0
                score += (sim_score * 100)

                if cand.name not in connected_destinations: score += 10 
                if "Input" in cand.bl_idname or "Info" in cand.bl_idname or "Time" in cand.bl_idname: score += 5
                
                if score > best_score:
                    best_score = score
                    best_candidate = cand
                    
            if best_candidate:
                if self._create_single_link(best_candidate, dst, link):
                    connected_sources.add(best_candidate.name)
                    logger.info(f"Auto-Healed hallucinated link using orphan node: {best_candidate.name} (Score: {best_score:.2f})")

    def _restore_frames(self, frames_data):
        if not isinstance(frames_data, dict): return
        for child_name, parent_name in frames_data.items():
            child = self.node_map.get(child_name)
            parent = self.node_map.get(parent_name)
            if child and parent: child.parent = parent