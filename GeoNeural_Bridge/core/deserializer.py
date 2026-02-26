# core/deserializer.py
# GeoNeural Bridge v5.14.134 (Omega Armor - Precision Healing)
# 机制优化: 增加对 AI 超紧凑 Dict 格式 inputs 的泛化支持。
# 机制优化: 增加 input_type -> data_type 的专属语义别名桥接。
# 架构级强化: 万能集合雷达、焦土重建协议与装甲回退试探器。
# 漏洞修复: 引入内部填充协议，解决 API 创建 NodeGroup 内部真空的缺陷。
# 漏洞修复: 引入 [语义绝对优先绑定]，解决动态节点序列化过程中的标识符漂移。
# 架构级强化: 升级 [全向双写协议 Bidirectional Dual-Write]，同步 Zone 节点数据。
# 核心修复: 引入 [Pulse-Sync Protocol] 脉冲同步协议，强制刷新 Zone 节点拓扑。
# 核心修复: 增强 [Link Semantic Anchor]，引入双重故障转移机制。
# 紧急修复: 修正 [Auto-Heal] 机制的过度医疗问题，引入名称相似度阈值，防止缺失的外部节点被错误的内部节点顶替。

import bpy
import logging
import difflib
from mathutils import Vector, Euler, Matrix, Color, Quaternion

from . import node_mappings
from .node_mappings import TextSmartEngine, SocketTypeResolver

logger = logging.getLogger("GeoNeuralBridge.deserializer")

# ==============================================================================
# 1. 智能属性设置器
# ==============================================================================

class SmartPropertySetter:
    @staticmethod
    def resolve_prop_name(node, prop_name):
        if hasattr(node, prop_name): return prop_name
            
        semantic_aliases = {
            'mode': 'operation',
            'inputtype': 'data_type', 
            'domaintype': 'domain'
        }
        norm_prop = TextSmartEngine.clean_for_loose(prop_name)
        if norm_prop in semantic_aliases and hasattr(node, semantic_aliases[norm_prop]):
            return semantic_aliases[norm_prop]

        if hasattr(node, "bl_rna"):
            best_match = None
            best_diff = 999
            for rna_key in node.bl_rna.properties.keys():
                if TextSmartEngine.match_loose(prop_name, rna_key):
                    diff = abs(len(rna_key) - len(prop_name))
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
        if value in valid_items: 
            setattr(node, prop_name, value); return True
            
        best_match_ident = None
        best_match_score = 0.0
        norm_val = TextSmartEngine.clean_polymorphic(value)

        for item in rna_prop.enum_items:
            if TextSmartEngine.match_strict(value, item.identifier) or TextSmartEngine.match_strict(value, item.name):
                setattr(node, prop_name, item.identifier); return True
                
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
    def resolve_candidates(collection, name_or_ident, index=None, orig_name=None):
        candidates = []
        
        if index is not None and 0 <= index < len(collection):
            candidates.append(collection[index])
            return candidates

        if not name_or_ident: return candidates
        name_str = str(name_or_ident).strip()

        node = collection[0].node if len(collection) > 0 else None
        is_reroute = node and node.bl_idname == 'NodeReroute'

        def is_valid_socket(s):
            return (s.bl_idname != 'NodeSocketVirtual' or is_reroute) and s not in candidates

        if node and orig_name:
            is_dynamic = any(x in node.bl_idname for x in ['Group', 'Simulation', 'Repeat', 'Bake', 'Foreach'])
            if is_dynamic:
                orig_name_str = str(orig_name).strip()
                for s in collection:
                    if s.name == orig_name_str and is_valid_socket(s):
                        candidates.append(s)
                if candidates: return candidates

        for s in collection:
            if (s.identifier == name_str or s.name == name_str) and is_valid_socket(s):
                candidates.append(s)

        if candidates: return candidates

        for s in collection:
            if not is_valid_socket(s): continue
            if (TextSmartEngine.match_loose(name_str, s.name) or 
                TextSmartEngine.match_loose(name_str, s.identifier) or 
                TextSmartEngine.match_loose(name_str, getattr(s, 'label', '')) or
                TextSmartEngine.match_loose(name_str, s.bl_idname)):
                candidates.append(s)

        if candidates: return candidates

        name_upper = name_str.upper()
        if name_upper in {'A', 'B', 'C', 'D', 'X', 'Y', 'Z'}:
            idx_map = {'A': 0, 'X': 0, 'B': 1, 'Y': 1, 'C': 2, 'Z': 2, 'D': 3}
            valid_sockets = [s for s in collection if is_valid_socket(s) and not getattr(s, 'hide', False) and getattr(s, 'enabled', True)]
            target_idx = idx_map[name_upper]
            if target_idx < len(valid_sockets):
                candidates.append(valid_sockets[target_idx])
            return candidates

        guessed_type = node_mappings.get_socket_class_name(name_str)
        if guessed_type:
            for s in collection:
                if s.bl_idname == guessed_type and not getattr(s, 'hide', False) and getattr(s, 'enabled', True) and is_valid_socket(s):
                    candidates.append(s)
                    
        if candidates: return candidates

        generic_terms = {"VALUE", "RESULT", "OUTPUT", "INPUT", "DATA", "ANY", "ATTRIBUTE"}
        if name_upper in generic_terms:
            data_sockets = []
            geo_sockets = []
            for s in collection:
                if is_valid_socket(s) and not getattr(s, 'hide', False) and getattr(s, 'enabled', True):
                    if s.type in {'GEOMETRY', 'OBJECT', 'COLLECTION', 'MATERIAL', 'TEXTURE', 'IMAGE'}:
                        geo_sockets.append(s)
                    else:
                        data_sockets.append(s)
            
            if data_sockets:
                candidates.extend(data_sockets)
            else:
                candidates.extend(geo_sockets)

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
                t_name = link.get('to_socket') or link.get('dst_sock')
                t_idx = link.get('to_socket_index') or link.get('dst_idx')
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
        self.raw_nodes_map = {}
        self.deferred_props_map = {}
        self._valid_pairs = set()

    def deserialize_tree(self, json_data, offset=(0,0)):
        if not isinstance(json_data, dict): return []
        
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

            # 核心数据注入
            self._radar_restore_collections(node, n_data)

        # ==============================================================================
        # ⚡ [OMEGA PATCH] 脉冲同步协议 (Pulse-Sync Protocol)
        # 目的: 消除 Zone 节点数据注入后，Socket 生成前的时序真空
        # ==============================================================================
        self._force_topology_refresh() 
        # ==============================================================================

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
        """
        [Omega Armor] 强制 Blender 根据 Items 数据计算并生成 Sockets。
        这解决了 Simulation/Repeat Zone 自定义接口无法立即连线的问题。
        """
        try:
            # 1. 基础标签更新 (通知 Blender 树结构已脏)
            if hasattr(self.tree, "update_tag"):
                self.tree.update_tag()
            
            # 2. 强制上下文更新 (这是生成 Zone Sockets 的关键)
            # 注意: 这是一个昂贵的操作，但对于 Zone 重建是必须的。
            # 我们通过检测是否存在 Zone 节点来决定是否执行，以优化性能。
            has_zone = any(
                "Simulation" in n.bl_idname or 
                "Repeat" in n.bl_idname or 
                "Bake" in n.bl_idname or
                "Foreach" in n.bl_idname 
                for n in self.node_map.values()
            )
            
            if has_zone and self.context:
                # 尝试触发视图层更新，迫使 NodeTree 评估
                # 某些情况下，仅 update_tag 是不够的
                if hasattr(self.context, "view_layer") and hasattr(self.context.view_layer, "update"):
                    self.context.view_layer.update()
                
                logger.debug("⚡ [Pulse-Sync] Forced topology refresh for Zone Sockets.")
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

    def _create_node_skeleton(self, n_data, offset):
        raw_idname = n_data.get('bl_idname', 'NodeFrame')
        bl_idname = node_mappings.resolve_node_idname(raw_idname)
        
        orig_name = n_data.get('name')
        
        try: 
            node = self.tree.nodes.new(bl_idname)
        except Exception as e: 
            node = self.tree.nodes.new("NodeFrame")
            node.label = f"MISSING: {bl_idname}"
            logger.warning(f"Failed to create node {bl_idname}, error: {e}")
        
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
        """【万能集合雷达】：无视硬编码，自动探测节点自带集合并灌入数据"""
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
                
                # 【双向查找协议】：无论给的是 Input 还是 Output，都能顺藤摸瓜找到另一半
                if 'Input' in node.bl_idname and hasattr(node, 'paired_output') and node.paired_output:
                    if node.paired_output not in target_nodes:
                        target_nodes.insert(0, node.paired_output) # Output 优先（Master）
                elif 'Output' in node.bl_idname:
                    # 反向查找：遍历当前图谱，寻找哪个 Input 的 paired_output 是当前节点
                    for sibling in self.node_map.values():
                        if 'Input' in sibling.bl_idname and getattr(sibling, 'paired_output', None) == node:
                            if sibling not in target_nodes:
                                target_nodes.append(sibling) # Input 延后（Proxy）
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
                        # 不触发 break，对目标列表执行完美双写 (Dual-Write)

    def _scorched_earth_rebuild(self, collection, items_data):
        """【焦土重建协议】：先拔除所有系统幽灵占位符，再重构数据"""
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
        """【装甲回退试探器】：免疫 API Enum 断层与精神分裂"""
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
        from_sock_ident = link.get('src_sock') or link.get('from_socket')
        to_sock_ident = link.get('dst_sock') or link.get('to_socket')
        from_idx = link.get('src_idx') or link.get('from_socket_index')
        to_idx = link.get('dst_idx') or link.get('to_socket_index')

        # 【核心修复 - Omega Armor Semantic Anchor】
        src_orig_name = link.get('src') or link.get('from_node')
        dst_orig_name = link.get('dst') or link.get('to_node')

        src_data = self.raw_nodes_map.get(src_orig_name)
        if not src_data: src_data = self.raw_nodes_map.get(src.name, {}) # Failover

        dst_data = self.raw_nodes_map.get(dst_orig_name)
        if not dst_data: dst_data = self.raw_nodes_map.get(dst.name, {}) # Failover
        
        def get_orig_name(node_data, ident):
            if not node_data: return None
            for s in node_data.get('outputs', []) + node_data.get('inputs', []):
                if s.get('identifier') == ident:
                    return s.get('name')
            return None

        from_orig_name = get_orig_name(src_data, from_sock_ident)
        to_orig_name = get_orig_name(dst_data, to_sock_ident)

        candidates_src = SocketResolver.resolve_candidates(src.outputs, from_sock_ident, from_idx, orig_name=from_orig_name)
        from_sock = candidates_src[0] if candidates_src else None
        
        candidates_dst = SocketResolver.resolve_candidates(dst.inputs, to_sock_ident, to_idx, orig_name=to_orig_name)
        to_sock = candidates_dst[0] if candidates_dst else None

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

        # === [DIAGNOSTIC PROBE] 诊断探针 ===
        if not to_sock and "Simulation" in dst.bl_idname:
            logger.warning(f"❌ [Link-Trace] Failed to find target socket on {dst.name}")
            logger.warning(f"   Target: '{to_sock_ident}' (Index: {to_idx})")
            logger.warning(f"   Available Sockets: {[s.name for s in dst.inputs]}")
        # ===================================

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
            dst_name = link.get('dst') or link.get('to_node')
            dst = self.node_map.get(dst_name) or self.tree.nodes.get(dst_name)
            if not dst: continue
            
            candidates = [n for n in self.node_map.values() if n.name not in connected_sources and len(n.outputs) > 0]
            if not candidates: continue
            
            best_candidate = None
            best_score = -1
            
            # 【v5.14.134 修复】：获取源节点的原始名称暗示
            src_name_hint = link.get('src') or link.get('from_node')
            if not src_name_hint: continue

            for cand in candidates:
                # 【关键修复】：引入名称相似度检测
                # 如果名称相差太远（例如 Post_Raycast vs Debug_Line_Shape），则判定为无关节点，拒绝修复。
                # 只有当名称高度相似（例如 Math vs Math.001）时，才认为是重命名导致的断连。
                sim_score = difflib.SequenceMatcher(None, src_name_hint.lower(), cand.name.lower()).ratio()
                
                # 相似度阈值：低于 0.5 视为完全不同的节点，直接跳过
                if sim_score < 0.5: continue

                score = 0
                score += (sim_score * 100) # 名称越像，权重越高

                if cand.name not in connected_destinations: score += 10 
                if "Input" in cand.bl_idname or "Info" in cand.bl_idname or "Time" in cand.bl_idname: score += 5
                
                if score > best_score:
                    best_score = score
                    best_candidate = cand
                    
            if best_candidate:
                if self._create_single_link(best_candidate, dst, link):
                    connected_sources.add(best_candidate.name)
                    logger.info(f"Auto-Healed hallucinated link using orphan node: {best_candidate.name} (Similarity: {best_score:.2f})")

    def _restore_frames(self, frames_data):
        if not isinstance(frames_data, dict): return
        for child_name, parent_name in frames_data.items():
            child = self.node_map.get(child_name)
            parent = self.node_map.get(parent_name)
            if child and parent: child.parent = parent