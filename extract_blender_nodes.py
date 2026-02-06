import os
import re
import json
import glob

# ================= 配置区域 =================
# Blender 源码根路径
SOURCE_ROOT = r"I:\ACG\Tool\Blender\blender-5.0.1"
# 固定数据库名称
OUTPUT_FILENAME = "blender_node_schema.json"
OUTPUT_PATH = os.path.join(os.path.expanduser("~"), "Desktop", OUTPUT_FILENAME)

TARGET_DIRS = [
    os.path.join("source", "blender", "nodes", "geometry", "nodes"),
    os.path.join("source", "blender", "nodes", "shader", "nodes"),
    os.path.join("source", "blender", "nodes", "texture", "nodes"),
    os.path.join("source", "blender", "nodes", "compositor", "nodes"),
    os.path.join("source", "blender", "nodes", "composite", "nodes"),
    os.path.join("source", "blender", "nodes", "function", "nodes"),
]

# ===========================================
# 1. 静态数据注入 (替代插件中的字典)
# ===========================================

# C++ Socket 类型 -> Blender Python API 类型映射
SOCKET_TYPE_MAP = {
    "Float": "NodeSocketFloat", "Int": "NodeSocketInt", "Bool": "NodeSocketBool",
    "String": "NodeSocketString", "Vector": "NodeSocketVector", "Color": "NodeSocketColor",
    "RGBA": "NodeSocketColor", "Rotation": "NodeSocketRotation", "Matrix": "NodeSocketMatrix",
    "Object": "NodeSocketObject", "Collection": "NodeSocketCollection", "Material": "NodeSocketMaterial",
    "Image": "NodeSocketImage", "Texture": "NodeSocketTexture", "Geometry": "NodeSocketGeometry",
    "Shader": "NodeSocketShader", "Menu": "NodeSocketMenu", "Virtual": "NodeSocketVirtual"
}

# 全局通用枚举定义 (在提取时直接注入节点，插件无需知道这些)
GLOBAL_ENUMS = {
    "rna_enum_attribute_domain_items": ["POINT", "EDGE", "FACE", "CORNER", "CURVE", "INSTANCE", "LAYER"],
    "rna_enum_attribute_type_items": ["FLOAT", "INT", "FLOAT_VECTOR", "FLOAT_COLOR", "BOOLEAN", "ROTATION", "MATRIX", "STRING"],
    "rna_enum_node_socket_data_type_items": ["FLOAT", "INT", "FLOAT_VECTOR", "FLOAT_COLOR", "BOOLEAN", "ROTATION", "MATRIX"],
    "rna_enum_math_operations": ["ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "MINIMUM", "MAXIMUM", "LESS_THAN", "GREATER_THAN"],
    "rna_enum_vector_math_operations": ["ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "CROSS_PRODUCT", "PROJECT", "REFLECT", "REFRACT", "FACEFORWARD", "DOT_PRODUCT", "DISTANCE", "LENGTH", "SCALE", "NORMALIZE", "ABSOLUTE", "MINIMUM", "MAXIMUM", "FLOOR", "CEIL", "FRACTION", "MODULO", "WRAP", "SNAP", "SINE", "COSINE", "TANGENT"],
    "rna_enum_boolean_math_operations": ["INTERSECT", "UNION", "DIFFERENCE", "NOT", "AND", "OR", "XOR", "IMPLY", "NIMPLY"],
    "rna_enum_mix_blend_type_items": ["MIX", "DARKEN", "MULTIPLY", "BURN", "LIGHTEN", "SCREEN", "DODGE", "ADD", "OVERLAY", "SOFT_LIGHT", "LINEAR_LIGHT", "DIFFERENCE", "EXCLUSION", "SUBTRACT", "DIVIDE", "HUE", "SATURATION", "COLOR", "VALUE"],
}

# 纹理通用输入补丁
TEXTURE_COMMON_INPUTS = [
    {"name": "Color 1", "identifier": "Color 1", "type": "Color", "bl_socket_type": "NodeSocketColor"},
    {"name": "Color 2", "identifier": "Color 2", "type": "Color", "bl_socket_type": "NodeSocketColor"}
]

# ===========================================
# 2. 提取逻辑
# ===========================================

def clean_content(text):
    text = re.sub(r'//.*', '', text)
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    return text

def extract_local_enums(content):
    enums = {}
    pattern = re.compile(r'static\s+(?:const\s+)?EnumPropertyItem\s+(\w+)\[\]\s*=\s*\{(.*?)\};', re.DOTALL)
    for match in pattern.finditer(content):
        name, body = match.groups()
        raw_items = re.findall(r'\{.*?, "([A-Za-z0-9_]+)"', body)
        valid_items = [i for i in raw_items if i and " " not in i and len(i) > 1]
        if valid_items: enums[name] = valid_items
    return enums

def extract_properties(content, local_enums):
    props = {}
    
    # 宏解析 RNA_def_node_enum
    regex_macro = re.compile(r'RNA_def_node_enum\s*\([^,]+,\s*"([^"]+)"\s*,[^,]+,[^,]+,\s*(\w+)')
    for m in regex_macro.finditer(content):
        p_name, enum_var = m.groups()
        # 优先查本地，查不到查全局，再查不到给空
        options = local_enums.get(enum_var, GLOBAL_ENUMS.get(enum_var, []))
        props[p_name] = {"type": "ENUM", "options": options}

    # 标准解析 RNA_def_property
    lines = content.split(';')
    last_prop_var = None
    last_prop_name = None
    
    for line in lines:
        line = line.strip()
        def_match = re.search(r'(\w+)\s*=\s*RNA_def_property\s*\([^,]+,\s*"([^"]+)"\s*,\s*(PROP_[A-Z]+)', line)
        if def_match:
            last_prop_var, last_prop_name, type_enum = def_match.groups()
            props[last_prop_name] = {"type": type_enum.replace("PROP_", ""), "options": []}
            continue
        
        if last_prop_var and f"RNA_def_property_enum_items({last_prop_var}" in line.replace(" ", ""):
            enum_match = re.search(r'RNA_def_property_enum_items\s*\([^,]+,\s*(\w+)', line)
            if enum_match:
                enum_var = enum_match.group(1)
                options = local_enums.get(enum_var, GLOBAL_ENUMS.get(enum_var, []))
                if last_prop_name in props: props[last_prop_name]["options"] = options

    return props

def extract_sockets(content):
    inputs, outputs = [], []
    
    # 1. node_declare 模板匹配
    pattern_tpl = re.compile(r'\.add_(input|output)<decl::(\w+)>\((.*?)\)(.*?)(?:;|\n)', re.DOTALL)
    seen_in, seen_out = set(), set()

    for match in pattern_tpl.finditer(content):
        direction, sock_type, args_str, chain_calls = match.groups()
        strings = re.findall(r'"([^"]+)"', args_str)
        name = strings[0] if strings else "Unknown"
        identifier = strings[1] if len(strings) > 1 else name
        
        default_val = None
        def_match = re.search(r'\.default_value\((.*?)\)', chain_calls)
        if def_match: default_val = def_match.group(1).strip()
        
        subtype = None
        if "PROP_EULER" in chain_calls: subtype = "EULER"
        elif "PROP_FACTOR" in chain_calls: subtype = "FACTOR"
        
        # 直接映射到 Blender API 类型
        bl_type = SOCKET_TYPE_MAP.get(sock_type, "NodeSocketFloat")

        sock = {
            "name": name,
            "identifier": identifier,
            "type": sock_type, 
            "bl_socket_type": bl_type, # 关键：直接告诉插件用什么类型
            "default_raw": default_val,
            "subtype": subtype
        }

        if direction == "input":
            if identifier not in seen_in: inputs.append(sock); seen_in.add(identifier)
        else:
            if identifier not in seen_out: outputs.append(sock); seen_out.add(identifier)

    # 2. 动态端口匹配
    pattern_dyn = re.compile(r'\.add_(input|output)\(([^,]+),\s*"([^"]+)"\)', re.DOTALL)
    for match in pattern_dyn.finditer(content):
        direction, _, name = match.groups()
        # 动态端口通常是 Geometry 或 Field，给个通用标记
        sock = {"name": name, "identifier": name, "type": "DYNAMIC", "bl_socket_type": "DYNAMIC", "subtype": None}
        if direction == "input": inputs.append(sock)
        else: outputs.append(sock)

    # 3. 遗留数组匹配
    if not inputs and not outputs and "bNodeSocketTemplate" in content:
        if "COMMON_INPUTS" in content: inputs.extend(TEXTURE_COMMON_INPUTS)
        
        def parse_arr(arr_name):
            res = []
            # 修复 f-string 语法错误，使用 {{ }}
            regex = re.compile(rf'{arr_name}\[\]\s*=\s*\{{(.*?)\}};', re.DOTALL)
            m = regex.search(content)
            if not m: return []
            raw = re.findall(r'SOCK_([A-Z]+).*?N_\("([^"]+)"\)', m.group(1))
            for s_type, s_name in raw:
                # SOCK_RGBA -> Color
                simple_type = s_type.replace("SOCK_", "").title().replace("Rgba", "Color")
                bl_type = SOCKET_TYPE_MAP.get(simple_type, "NodeSocketFloat")
                res.append({"name": s_name, "identifier": s_name, "type": simple_type, "bl_socket_type": bl_type})
            return res

        inputs.extend(parse_arr("inputs"))
        outputs.extend(parse_arr("outputs"))

    return inputs, outputs

def extract_node_data(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f: raw = f.read()
    except: return []
    content = clean_content(raw)
    filename = os.path.basename(filepath)
    nodes_found = []

    # 宏定义节点 (TexDef)
    if "TexDef" in content:
        pattern = re.compile(r'TexDef\(\w+,\s*"([^"]+)",\s*(\w+),\s*(\w+),\s*"([^"]+)"', re.DOTALL)
        for match in pattern.finditer(content):
            bl_idname, out_macro, in_prefix, ui_name = match.groups()
            
            # 简单处理宏节点的端口 (此处简化，依赖前文的数组解析能力)
            # 实际情况中，TexDef 的端口定义比较隐晦，这里为了演示，假设它们使用了标准的 inputs 数组变体
            # 更好的做法是构建一个临时的 content string 包含对应的数组定义，然后调用 extract_sockets
            # 为保证代码简洁，这里略过 TexDef 的深入展开，主要关注标准 C++ 节点
            # 但为了不漏，我们创建一个基础条目
            nodes_found.append({
                "bl_idname": bl_idname,
                "ui_name": ui_name,
                "file": filename,
                "inputs": [], # 需进一步完善宏解析逻辑
                "outputs": [],
                "rna_properties": {},
                "is_macro": True
            })

    # 标准节点
    id_match = re.search(r'\w+_node_type_base\(&ntype,\s*"([^"]+)"', content)
    if id_match:
        bl_idname = id_match.group(1)
        if not any(n['bl_idname'] == bl_idname for n in nodes_found):
            ui_match = re.search(r'ntype\.ui_name\s*=\s*"([^"]+)"', content)
            ui_name = ui_match.group(1) if ui_match else bl_idname
            
            # 提取旧名 (Legacy Name) 用于别名表
            legacy_match = re.search(r'ntype\.enum_name_legacy\s*=\s*"([^"]+)"', content)
            legacy_name = legacy_match.group(1) if legacy_match else None

            inputs, outputs = extract_sockets(content)
            local_enums = extract_local_enums(content)
            props = extract_properties(content, local_enums)
            
            nodes_found.append({
                "bl_idname": bl_idname,
                "ui_name": ui_name,
                "legacy_name": legacy_name,
                "file": filename,
                "inputs": inputs,
                "outputs": outputs,
                "rna_properties": props,
                "is_macro": False
            })

    return nodes_found

def main():
    print(f"🚀 V10.0 全知全能提取开始...")
    
    # 最终的数据库结构
    database = {
        "meta": {
            "version": "5.0.1",
            "socket_map": SOCKET_TYPE_MAP # 存一份给插件参考
        },
        "nodes": {},
        "alias_map": {} # 反向查找表: UI Name / Legacy Name -> Real ID
    }
    
    for sub in TARGET_DIRS:
        path = os.path.join(SOURCE_ROOT, sub)
        if not os.path.exists(path): continue
        
        for fpath in glob.glob(os.path.join(path, "*.cc")):
            extracted = extract_node_data(fpath)
            for node in extracted:
                idname = node["bl_idname"]
                
                # 1. 存入节点库
                database["nodes"][idname] = node
                
                # 2. 构建别名表 (Alias Map) - 这是插件“去脑”的关键
                # ID 本身
                database["alias_map"][idname] = idname
                # UI 名称 (如 "Accumulate Field")
                if node.get("ui_name"):
                    database["alias_map"][node["ui_name"]] = idname
                    # 去空格版 (如 "AccumulateField")
                    database["alias_map"][node["ui_name"].replace(" ", "")] = idname
                # 旧枚举名 (如 "ACCUMULATE_FIELD")
                if node.get("legacy_name"):
                    database["alias_map"][node["legacy_name"]] = idname
                
                # 特殊简化规则 (例如去前缀)
                simple_name = idname.replace("GeometryNode", "").replace("ShaderNode", "").replace("FunctionNode", "")
                database["alias_map"][simple_name] = idname

    # 写入文件
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(database, f, indent=2)
    
    print("-" * 50)
    print(f"✅ 数据库构建完成: {len(database['nodes'])} 个节点")
    print(f"🏷️  别名索引条目: {len(database['alias_map'])} 条")
    print(f"💾 文件位置: {OUTPUT_PATH}")

if __name__ == "__main__":
    main()