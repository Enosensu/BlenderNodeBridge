# BlenderNodeBridge 🌉

*(Formerly GeoNeural Bridge)*

**BlenderNodeBridge** 是一款旨在打破大语言模型（LLM）与 Blender 节点系统底层 API 之间壁垒的终极“全节点”通用插件。

无论是**几何节点（Geometry Nodes）**、**着色器节点（Shader Nodes）还是合成器节点（Compositor Nodes）**，它都能将 AI 生成的极度自由、高度紧凑甚至偶尔带有“幻觉”的 JSON 数据，100% 稳健地在 Blender 中精准物理复原。

---

## ✨ 核心特性 (Core Features)

本项目重构为**“三位一体”的动态响应生态架构**，实现了对 Blender 版本的深度自适应：

* 🧠 **智能语义大脑 (The Semantic Brain)**
* **跨域前缀纠错 (Namespace Rescue)**：自动剥离 AI 混淆的 API 前缀，并返回有序备选队列。
* **深度语义匹配**：基于核心语义和 Difflib 算法，为 JSON 节点寻找 Blender 内存中的最优候选。


* 🛡️ **欧米茄级防御装甲 (Omega Armor Architecture)**
* **活体内存反射 (Live Reflection)**：采用递归 `__subclasses__()` 无死角扫描内存，动态抓取当前版本所有可用节点，告别过时的硬编码。
* **激活状态验证优先级 (EVP)**：通过读取插槽的 `enabled` 与 `hide` 状态，强制抓取当前活跃插槽，解决多态节点幽灵插槽劫持问题。
* **物理索引映射 (Index Identity Mapping)**：在序列化阶段采用绝对物理索引，杜绝同名插槽产生的数据截断。


* 🚀 **LLM 交互优化 (LLM Context Optimization)**
* **超紧凑模式 (Compact Mode)**：导出时自动剥离冗余属性，大幅节省大模型的 Token 开销。
* **万能提取雷达**：无视节点类型，自动探测并同步 Zone 节点（Simulation/Repeat 等）的底层数据。



---

## 🆕 近期更新 (Recent Updates - Omega Armor 系列)

* **v5.14.141 - Index Identity Mapping**: 重构序列化引擎，切换至绝对物理索引锚点，解决 Math/Switch 节点同名插槽的数据丢失 Bug。
* **v5.14.140 - Core Node Injection**: 手动注入 Blender C++ 底层静默节点（如 `NodeGroupInput`），解决结构性元节点的复制粘贴崩溃。
* **v5.14.137 - EVP Abstraction**: 引入 EVP 机制，将几何节点的销毁特性抽象为全局验证逻辑，消除着色器多态节点的劫持隐患。
* **v5.14.131 - Pulse-Sync Protocol**: 引入脉冲同步协议，通过强制刷新视图层更新，消除 Zone 节点插槽生成的时序真空。
* **v5.14.46 - Robust Loader**: 增强对 `\xa0`（非断行空格）等脏字符的处理能力，提升 JSON 解析的健壮性。

---

## 📦 安装方法 (Installation)

本项目目前推荐通过手动复制源码的方式进行安装，以确保在 Blender 5.0+ 环境下的最佳路径兼容性：

1. 下载本项目源码。
2. 将解压后的 `BlenderNodeBridge` 文件夹复制到以下路径：
`C:\Users\你的用户名\AppData\Roaming\Blender Foundation\Blender\5.0\scripts\addons`
3. 启动 Blender。
4. 进入 `编辑 (Edit)` > `偏好设置 (Preferences)` > `插件 (Add-ons)`。
5. 在搜索框输入 `BlenderNodeBridge` 并勾选启用。

或直接下载Release中的zip文件进行安装

![最新版本](https://img.shields.io/github/v/release/Enosensu/BlenderNodeBridge)

---

## 🤝 鸣谢 (Acknowledgements)

本项目在架构设计、深层 Blender API 源码剖析以及复杂模式抽象的迭代过程中，全程由 **Gemini 3.1 Pro** 辅助开发。特此致谢其在代码健壮性审查与 SOLID 原则实践中提供的“全知视角”级技术洞察与支持。

---

## 📄 许可证 (License)

本项目基于 **[MIT License](https://www.google.com/search?q=LICENSE)** 开源。您可以自由地使用、修改和分发本项目的代码，只需保留原作者的版权声明和许可声明即可。
