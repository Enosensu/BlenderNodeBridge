# core/serializer.py
# GeoNeural Bridge v5.14.141 (Omega Armor - Index Identity Mapping)
# 机制优化: 进一步封堵 RNA 属性泄露，彻底过滤 properties 中的 UI 尺寸限界参数和空字符串 label。
# 架构级强化: 废除硬编码的 if-elif Zone 节点类型判定，引入【万能探针提取器】，实现对未知/未来版本动态节点的自动化数据抓取。
# 核心修复: 修复精简模式 (Compact Mode) 下，多输入节点(如 Math)的同名插槽因名称碰撞导致 default_value 被误判剥离的 Bug，全面切入物理 Index 映射锚点。
# 架构: Topology Tracer -> Reroute Bypass -> Data Clean -> Compact Filter -> Output

import bpy
import logging
from mathutils import Vector, Euler, Matrix, Color, Quaternion

try:
    from . import node_mappings
except ImportError:
    node_mappings = None

logger = logging.getLogger("GeoNeuralBridge.serializer")

# ==============================================================================
# 1. 基础工具集
# ==============================================================================

class DataCleaner:
    @staticmethod
    def clean_data(value):
        if value is None: return None
        if isinstance(value, bpy.types.ID): return value.name
        if isinstance(value, (int, str, bool)): return value
        if isinstance(value, float): return round(value, 4)
        if isinstance(value, (Vector, Color, Euler, Quaternion)):
            return [round(x, 4) for x in value]
        if isinstance(value, Matrix):
            return [[round(c, 4) for c in col] for col in value]
        if hasattr(value, "__iter__") and not isinstance(value, (str, dict)):
             return [DataCleaner.clean_data(x) for x in value]
        if isinstance(value, dict): 
            return {k: DataCleaner.clean_data(v) for k, v in value.items()}
        return str(value)

    @staticmethod
    def serialize_color_ramp(ramp):
        if not ramp: return None
        return {
            "color_mode": ramp.color_mode,
            "interpolation": ramp.interpolation,
            "elements": [{"pos": round(e.position, 3), "color": list(e.color)} for e in ramp.elements]
        }

# ==============================================================================
# 2. 拓扑追踪引擎
# ==============================================================================

class TopologyTracer:
    """递归图遍历器：负责穿透无意义的转接点，寻找真实的拓扑终点"""
    @staticmethod
    def get_real_destinations(socket, visited=None):
        if visited is None:
            visited = set()
        
        if socket in visited:
            return []
        visited.add(socket)
        
        if socket.node.bl_idname != 'NodeReroute':
            return [socket]
        
        dests = []
        if socket.node.outputs:
            for out_link in socket.node.outputs[0].links:
                dests.extend(TopologyTracer.get_real_destinations(out_link.to_socket, visited))
        return dests

# ==============================================================================
# 3. 极致精简过滤器 (深度清理版)
# ==============================================================================

class CompactFilter:
    ROOT_BLACKLIST = {
        'location', 'location_absolute', 'width', 'height', 'color', 'use_custom_color', 
        'select', 'hide', 'bl_icon', 'mute'
    }
    
    PROPS_BLACKLIST = {
        'name', 'bl_idname', 'label', 'mute', 
        'show_options', 'show_preview', 'show_texture', 'bl_label', 'shrink', 'label_size',
        'active_index', 'active_item', 'active_input_index', 'active_generation_index', 'active_main_index',
        'inspection_index', 'warning_propagation', 'bl_description',
        'location', 'location_absolute', 'width', 'height', 'color', 'use_custom_color', 
        'select', 'hide', 'bl_icon', 'socket_idname',
        'bl_width_default', 'bl_width_min', 'bl_width_max',
        'bl_height_default', 'bl_height_min', 'bl_height_max'
    }

    SOCKET_PROP_BLACKLIST = {
        'enabled', 'hide', 'hide_value', 'label', 'description',
        'direction', 'bl_socket_idname'
    }

    @staticmethod
    def process_node(node_data):
        is_frame = node_data.get('bl_idname') == 'NodeFrame'
        
        if 'parent' in node_data:
            del node_data['parent']
            
        if node_data.get('label') == "":
            del node_data['label']
            
        for key in list(node_data.keys()):
            if key in CompactFilter.ROOT_BLACKLIST:
                del node_data[key]
                
        if 'properties' in node_data:
            props = node_data['properties']
            for key in list(props.keys()):
                if key in CompactFilter.PROPS_BLACKLIST: 
                    del props[key]
                elif isinstance(props[key], str) and props[key].startswith('<bpy_struct'): 
                    del props[key]
            if not props:
                del node_data['properties']
                
        for direction in ['inputs', 'outputs']:
            if direction in node_data:
                for socket in node_data[direction]:
                    CompactFilter._process_socket(socket)
                
                if direction == 'outputs' or not node_data[direction]:
                    del node_data[direction]

        # 【泛化清洗协议】不再依赖硬编码字典，只要发现节点属性中有 'items' 结构，统一剥离视觉色块
        for key, val in node_data.items():
            if isinstance(val, dict) and 'items' in val:
                for item in val['items']:
                    if isinstance(item, dict) and 'color' in item:
                        del item['color']
                    
        return node_data

    @staticmethod
    def _process_socket(socket_data):
        for key in list(socket_data.keys()):
            if key in CompactFilter.SOCKET_PROP_BLACKLIST: del socket_data[key]
            
        if socket_data.get('identifier') == socket_data.get('name'):
            del socket_data['identifier']

# ==============================================================================
# 4. 序列化逻辑
# ==============================================================================

class SocketSerializer:
    @staticmethod
    def get_bl_idname(socket):
        if hasattr(socket, 'bl_socket_idname'): return socket.bl_socket_idname
        if node_mappings: return node_mappings.get_socket_class_name(socket.type)
        return 'NodeSocketFloat'

    @staticmethod
    def serialize(socket, index, direction='INPUT'):
        bl_idname = SocketSerializer.get_bl_idname(socket)
        data = {
            'name': socket.name,
            'identifier': getattr(socket, 'identifier', socket.name),
            'bl_socket_idname': bl_idname,
            'type': getattr(socket, 'type', 'FLOAT'),
            'index': index,
            'direction': direction,
            'enabled': getattr(socket, 'enabled', True),
            'hide': getattr(socket, 'hide', False),
            'hide_value': getattr(socket, 'hide_value', False),
            'label': getattr(socket, 'label', ''),
        }
        
        if hasattr(socket, 'default_value'):
            try:
                val = DataCleaner.clean_data(socket.default_value)
                if val is not None: data['default_value'] = val
            except Exception:
                pass
        
        if bl_idname == 'NodeSocketBundle' or data['type'] == 'BUNDLE':
            data['is_bundle'] = True
            data['bundle_items'] = SocketSerializer._serialize_bundle_items(socket)
        return data

    @staticmethod
    def _serialize_bundle_items(socket):
        items = []
        try:
            node = socket.node
            tree = node.id_data
            if hasattr(tree, 'interface') and hasattr(tree.interface, 'items_tree'):
                for item in tree.interface.items_tree:
                    if hasattr(item, 'parent') and item.parent and getattr(item.parent, 'name', '') == socket.name:
                        sock_type = getattr(item, 'socket_type', 'FLOAT')
                        items.append({
                            'name': item.name,
                            'socket_type': str(sock_type),
                            'bl_socket_idname': node_mappings.get_socket_class_name(sock_type) if node_mappings else 'NodeSocketFloat'
                        })
        except: pass
        return items

class NodeSerializer:
    ALWAYS_EXCLUDE = {'rna_type', 'node_tree', 'inputs', 'outputs', 'interface', 'dimensions', 'is_active_output', 'internal_links'}

    @staticmethod
    def serialize(node):
        data = {
            'name': node.name,
            'bl_idname': node.bl_idname,
            'label': node.label,
            'location': [int(node.location.x), int(node.location.y)],
            'width': node.width, 'height': node.height,
            'hide': node.hide, 'mute': node.mute,
            'select': True, 'use_custom_color': node.use_custom_color,
            'color': list(node.color),
        }
        
        if node.parent: data['parent'] = node.parent.name

        valid_inputs = []
        for i, s in enumerate(node.inputs):
            if hasattr(s, "is_unavailable") and s.is_unavailable: continue
            valid_inputs.append(SocketSerializer.serialize(s, i, 'INPUT'))
        data['inputs'] = valid_inputs

        valid_outputs = []
        for i, s in enumerate(node.outputs):
            if hasattr(s, "is_unavailable") and s.is_unavailable: continue
            valid_outputs.append(SocketSerializer.serialize(s, i, 'OUTPUT'))
        data['outputs'] = valid_outputs

        data['properties'] = NodeSerializer._serialize_properties(node)

        NodeSerializer._radar_extract_collections(node, data)

        if node.bl_idname == 'GeometryNodeGroup' and node.node_tree:
            data['node_tree_name'] = node.node_tree.name

        return data

    @staticmethod
    def _radar_extract_collections(node, data):
        """【万能提取雷达】：无视节点类型，自动探测并提取底层集合数据"""
        radar_map = {
            'state_items': 'simulation_state',
            'repeat_items': 'repeat_state',
            'bake_items': 'bake_state',
            'main_items': 'foreach_main',
            'input_items': 'foreach_input',
            'generation_items': 'foreach_generation'
        }
        
        # 建立数据主权：寻找数据母体 (Output节点优先)
        master_node = node
        if 'Input' in node.bl_idname:
            paired = getattr(node, 'paired_output', None) or getattr(node, 'pair_with_output', None)
            if paired: 
                master_node = paired

        for mem_attr, json_key in radar_map.items():
            if hasattr(master_node, mem_attr) and not callable(getattr(master_node, mem_attr)):
                collection = getattr(master_node, mem_attr)
                if collection and len(collection) > 0:
                    items = []
                    for item in collection:
                        raw_type = getattr(item, 'socket_type', getattr(item, 'data_type', 'FLOAT'))
                        item_data = {
                            'name': getattr(item, 'name', 'Value'),
                            'socket_type': str(raw_type),
                            'bl_socket_idname': node_mappings.get_socket_class_name(raw_type) if node_mappings else 'NodeSocketFloat',
                        }
                        if hasattr(item, 'color'): item_data['color'] = list(item.color)
                        items.append(item_data)
                    
                    data[json_key] = {'items': items, 'node_type': node.bl_idname}

    @staticmethod
    def _serialize_properties(node):
        props = {}
        for prop in node.bl_rna.properties:
            identifier = prop.identifier
            if identifier in NodeSerializer.ALWAYS_EXCLUDE: continue
            if prop.is_readonly: continue
            val = getattr(node, identifier)
            if isinstance(val, bpy.types.ColorRamp):
                props[identifier] = {"__type__": "ColorRamp", "data": DataCleaner.serialize_color_ramp(val)}
                continue
            if node.bl_idname == 'GeometryNodeCaptureAttribute' and identifier in {'data_type', 'capture_items'}: continue
            clean_val = DataCleaner.clean_data(val)
            if clean_val is not None: props[identifier] = clean_val
        
        if node.bl_idname == 'GeometryNodeCaptureAttribute' and hasattr(node, 'capture_items'):
            items = []
            for item in node.capture_items:
                items.append({"name": item.name, "data_type": getattr(item, "data_type", "FLOAT")})
            props["capture_items_data"] = items
        return props

class SerializationEngine:
    def __init__(self, tree, context, selected_only=False, compact=False):
        self.tree = tree
        self.context = context
        self.selected_only = selected_only
        self.compact = compact
        
        initial_nodes = [n for n in tree.nodes if n.select] if selected_only else list(tree.nodes)
        self.nodes_to_process = self._ensure_zone_integrity(initial_nodes)
        
        # 【架构修复】不再使用 (node_name, socket_name)，切入绝对物理索引 (node_name, socket_index)
        self.connected_sockets = set()

    def _ensure_zone_integrity(self, nodes):
        final_set = set(nodes)
        processed_ids = {n.as_pointer() for n in nodes}

        output_to_input_map = {}
        for n in self.tree.nodes:
            if hasattr(n, "paired_output") and n.paired_output:
                output_to_input_map[n.paired_output] = n

        for node in list(final_set):
            partner = None
            if hasattr(node, "paired_output") and node.paired_output:
                partner = node.paired_output
            elif node in output_to_input_map:
                partner = output_to_input_map[node]

            if partner and partner.as_pointer() not in processed_ids:
                final_set.add(partner)
                processed_ids.add(partner.as_pointer())
                logger.info(f"Auto-included zone partner: {partner.name} for {node.name}")

        return list(final_set)

    def execute(self):
        real_nodes_to_process = [n for n in self.nodes_to_process if n.bl_idname != 'NodeReroute']
        node_names = {n.name for n in real_nodes_to_process}
        
        links_data = []
        processed_links = set()
        
        for link in self.tree.links:
            if link.from_node.bl_idname == 'NodeReroute' or link.from_node.name not in node_names:
                continue
                
            real_dests = TopologyTracer.get_real_destinations(link.to_socket)
            
            for dest_sock in real_dests:
                if dest_sock.node.name in node_names:
                    link_id = (link.from_socket.as_pointer(), dest_sock.as_pointer())
                    
                    if link_id not in processed_links:
                        processed_links.add(link_id)
                        
                        link_data = {
                            'src': link.from_node.name,
                            'src_sock': getattr(link.from_socket, 'identifier', link.from_socket.name),
                            'dst': dest_sock.node.name,
                            'dst_sock': getattr(dest_sock, 'identifier', dest_sock.name)
                        }
                        
                        if not self.compact:
                            link_data['from_node'] = link_data.pop('src')
                            link_data['from_socket'] = link_data.pop('src_sock')
                            link_data['from_socket_index'] = self._get_socket_index(link.from_node.outputs, link.from_socket)
                            link_data['to_node'] = link_data.pop('dst')
                            link_data['to_socket'] = link_data.pop('dst_sock')
                            link_data['to_socket_index'] = self._get_socket_index(dest_sock.node.inputs, dest_sock)
                        
                        links_data.append(link_data)
                        
                        # 【核心防线】记录目标的唯一物理索引 Index，彻底杜绝名称碰撞
                        if self.compact:
                            dest_idx = self._get_socket_index(dest_sock.node.inputs, dest_sock)
                            self.connected_sockets.add((dest_sock.node.name, dest_idx))

        data = {
            "version": "v5.14.141 Omega Armor",
            "tree_type": self.tree.bl_idname,
            "nodes": [],
            "links": links_data,
            "frames": {}
        }

        for node in real_nodes_to_process:
            try:
                node_data = NodeSerializer.serialize(node)
                if self.compact:
                    node_data = CompactFilter.process_node(node_data)
                    # 【核心防线】仅当当前插槽的物理 Index 被记录为已连线时，才执行裁剪清空
                    if node.bl_idname != 'NodeFrame' and 'inputs' in node_data:
                        for inp in node_data['inputs']:
                            if (node.name, inp.get('index', -1)) in self.connected_sockets:
                                if 'default_value' in inp: del inp['default_value']
                data["nodes"].append(node_data)
            except Exception as e:
                logger.error(f"Serialize error {node.name}: {e}")

        for node in real_nodes_to_process:
            if node.parent and node.parent.name in node_names:
                data["frames"][node.name] = node.parent.name

        return data

    def _get_socket_index(self, collection, socket):
        for i, s in enumerate(collection):
            if s == socket: return i
        return -1