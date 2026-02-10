# core/serializer.py
# GeoNeural Bridge v5.13.33 (Based on v5.13.32)
# 修复: Zone Items 序列化增加冗余类型信息，提高容错性

import bpy
import logging
from mathutils import Vector, Euler, Matrix, Color, Quaternion

# 导入新的映射库
try:
    from . import node_mappings
except ImportError:
    node_mappings = None

logger = logging.getLogger("GeoNeuralBridge.serializer")

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

class CompactFilter:
    # 保持 v5.13.32 的精简策略
    NODE_PROP_BLACKLIST = {
        'location', 'location_absolute', 
        'width', 'height', 'color', 'use_custom_color', 
        'select', 'hide', 'bl_icon',
        'bl_width_default', 'bl_width_min', 'bl_width_max',
        'bl_height_default', 'bl_height_min', 'bl_height_max',
        'active_index', 'active_item', 'inspection_index', 'warning_propagation',
        'bl_description'
    }
    SOCKET_PROP_BLACKLIST = {
        'enabled', 'hide', 'hide_value', 'label', 'description'
    }

    @staticmethod
    def process_node(node_data):
        for key in list(node_data.keys()):
            if key in CompactFilter.NODE_PROP_BLACKLIST: del node_data[key]
        if 'properties' in node_data:
            props = node_data['properties']
            for key in list(props.keys()):
                if key in CompactFilter.NODE_PROP_BLACKLIST: del props[key]
                elif isinstance(props[key], str) and props[key].startswith('<bpy_struct'): del props[key]
        for direction in ['inputs', 'outputs']:
            if direction in node_data:
                for socket in node_data[direction]:
                    CompactFilter._process_socket(socket)
        for state_key in ['simulation_state', 'repeat_state', 'bake_state']:
            if state_key in node_data:
                for item in node_data[state_key].get('items', []):
                    if 'color' in item: del item['color']
        return node_data

    @staticmethod
    def _process_socket(socket_data):
        for key in list(socket_data.keys()):
            if key in CompactFilter.SOCKET_PROP_BLACKLIST: del socket_data[key]

class SocketSerializer:
    @staticmethod
    def get_bl_idname(socket):
        if hasattr(socket, 'bl_socket_idname'): return socket.bl_socket_idname
        # 回退使用映射库
        if node_mappings:
            return node_mappings.get_socket_class_name(socket.type)
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
            val = DataCleaner.clean_data(socket.default_value)
            if val is not None: data['default_value'] = val
        
        # Bundle 递归
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
                        # 使用新映射确保准确性
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

        data['inputs'] = [SocketSerializer.serialize(s, i, 'INPUT') for i, s in enumerate(node.inputs)]
        data['outputs'] = [SocketSerializer.serialize(s, i, 'OUTPUT') for i, s in enumerate(node.outputs)]
        data['properties'] = NodeSerializer._serialize_properties(node)

        # Zone 状态捕获
        if node.bl_idname in ('GeometryNodeSimulationInput', 'GeometryNodeSimulationOutput'):
            data['simulation_state'] = NodeSerializer._serialize_zone_state(node, 'state_items')
        elif node.bl_idname in ('GeometryNodeRepeatInput', 'GeometryNodeRepeatOutput'):
            data['repeat_state'] = NodeSerializer._serialize_zone_state(node, 'repeat_items')
        elif node.bl_idname in ('GeometryNodeBakeInput', 'GeometryNodeBakeOutput'):
            data['bake_state'] = NodeSerializer._serialize_zone_state(node, 'bake_items')

        if node.bl_idname == 'GeometryNodeGroup' and node.node_tree:
            data['node_tree_name'] = node.node_tree.name

        return data

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

    @staticmethod
    def _serialize_zone_state(node, collection_name):
        state_data = {'items': [], 'node_type': node.bl_idname}
        output_node = node
        if 'Input' in node.bl_idname:
            paired = getattr(node, 'paired_output', None) or getattr(node, 'pair_with_output', None)
            if paired: output_node = paired
        
        collection = getattr(output_node, collection_name, None)
        if collection:
            for item in collection:
                # [修复] 增加冗余信息：同时记录 socket_type(Enum) 和 bl_socket_idname(Class)
                s_type = getattr(item, 'socket_type', 'FLOAT')
                item_data = {
                    'name': item.name,
                    'socket_type': str(s_type),
                    'bl_socket_idname': node_mappings.get_socket_class_name(s_type) if node_mappings else 'NodeSocketFloat',
                }
                if hasattr(item, 'color'): item_data['color'] = list(item.color)
                state_data['items'].append(item_data)
        return state_data

class SerializationEngine:
    def __init__(self, tree, context, selected_only=False, compact=False):
        self.tree = tree
        self.context = context
        self.selected_only = selected_only
        self.compact = compact
        self.nodes_to_process = [n for n in tree.nodes if n.select] if selected_only else list(tree.nodes)
        self.connected_sockets = set()

    def execute(self):
        node_names = {n.name for n in self.nodes_to_process}
        links_data = []
        for link in self.tree.links:
            if link.from_node.name in node_names and link.to_node.name in node_names:
                link_data = {
                    'from_node': link.from_node.name,
                    'from_socket': link.from_socket.name,
                    'from_socket_index': self._get_socket_index(link.from_node.outputs, link.from_socket),
                    'to_node': link.to_node.name,
                    'to_socket': link.to_socket.name,
                    'to_socket_index': self._get_socket_index(link.to_node.inputs, link.to_socket)
                }
                links_data.append(link_data)
                if self.compact:
                    self.connected_sockets.add((link.to_node.name, link.to_socket.identifier))

        data = {
            "version": "v5.13.33 Strict",
            "tree_type": self.tree.bl_idname,
            "nodes": [],
            "links": links_data,
            "frames": {}
        }

        for node in self.nodes_to_process:
            if self.compact and node.bl_idname == 'NodeFrame': continue
            try:
                node_data = NodeSerializer.serialize(node)
                if self.compact:
                    node_data = CompactFilter.process_node(node_data)
                    if 'inputs' in node_data:
                        for inp in node_data['inputs']:
                            if (node.name, inp['identifier']) in self.connected_sockets:
                                if 'default_value' in inp: del inp['default_value']
                data["nodes"].append(node_data)
            except Exception as e:
                logger.error(f"Serialize error {node.name}: {e}")

        if not self.compact:
            for node in self.nodes_to_process:
                if node.parent and node.parent.name in node_names:
                    data["frames"][node.name] = node.parent.name

        return data

    def _get_socket_index(self, collection, socket):
        for i, s in enumerate(collection):
            if s == socket: return i
        return -1