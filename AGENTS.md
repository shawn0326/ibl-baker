# AGENTS.md

## 沟通规则

- 与用户沟通时使用中文。
- 汇报进度、实现细节和取舍时，保持简洁、清晰、以执行为导向。

## 项目语言规则

- 默认交付内容使用英文：源代码、标识符、提交信息、代码注释、README、文档、CLI 帮助文本、日志和错误信息、测试名称、示例文件、规范说明文件。
- 以下文件使用中文：`AGENTS.md`、`TODO.md`。

## 仓库速览

- 根目录同时使用 Cargo workspace 与 npm workspace。
- `crates/ibl_core`：Rust 核心库，负责源图读取、bake 主流程、`.ibla` 读写与校验、KTX2 导出。
- `crates/ibl_cli`：公开 CLI（`ibl-baker`），支持 `--output-format <ibla|ktx2|both>`，输出 `.ibla`、`.ktx2` 或两者并行。
- `crates/ktx2_writer`：write-only KTX2 序列化器，BC6H（`intel_tex_2`）+ zstd 超级压缩，不依赖 CMake。
- `packages/loader`：公开 `.ibla` JS 包（`@ibltools/loader`），提供 parser-only 的 `parseIBLA(buffer)`；不处理 `.ktx2`。
- `packages/ktx2-loader`：公开 KTX2 JS 包（`@ibltools/ktx2-loader`），提供 narrow parser-only 的 `parseKTX2IBL(buffer)`；不做 zstd、BC6H decode 或 GPU 上传。
- `packages/ibla-viewer`：私有浏览器验收工具，用于手动拖拽 `.ibla` 文件、解析 PNG payload，并使用与 KTX2 viewer 一致的 linear → Reinhard → gamma 显示路径；不接仓库 fixture 目录。
- `packages/ktx2-viewer`：私有浏览器验收工具，用于手动拖拽 `.ktx2` 文件、解析、zstd 解压，并在 WebGPU 支持 `texture-compression-bc` 时做 BC6H 预览；首版不接仓库 fixture 目录。
- `fixtures/outputs`：已提交的产物样例（`.ibla` 与 `.ktx2`），供 loader 测试与浏览器验收复用。
- `scripts/refresh-fixtures.mjs`：刷新仓库内 fixtures 的入口脚本。

## 输出格式

CLI 并行支持两种输出格式，地位对等：

- **`.ibla`** — 便携归档格式，PNG 编码载荷，支持 `rgbd-srgb`/`srgb`/`linear` 编码。
- **`.ktx2`** — GPU 就绪格式，BC6H_UFLOAT + zstd 超级压缩，面向引擎和 Web 端直接消费。

BRDF LUT 始终输出为独立 `.png`，不受格式选项影响。

## 对外契约入口

以下文档是当前开发与维护时的优先依据：

- `docs/format-spec.md` — `.ibla` 二进制格式规范（纯 `.ibla`，不含 KTX2 内容）
- `crates/ibl_cli/README.md` — CLI 用法、选项、两种输出格式的完整说明
- `packages/loader/README.md` — TypeScript `.ibla` 解析器 API 契约
- `packages/ktx2-loader/README.md` — TypeScript KTX2 解析器 API 契约

以下文档适合快速理解仓库结构与职责分层：

- `README.md` — 项目总览
- `crates/ibl_core/README.md` — 核心库职责范围

规则：

- 实现必须遵守对外契约文档。
- 如果改动会影响公开行为、文件格式或 loader 契约，必须在同一轮改动里同步更新对应 README 或 docs。
- KTX2 的输出规格写在 CLI README 中（`### KTX2 Output` 章节），不写入 `docs/format-spec.md`。
- 能直接链接到 README 或 docs 的地方，优先链接，不在 `AGENTS.md` / `TODO.md` 里重复展开规格细节。

## 当前固定边界

- `.ibla` v1 继续保持稳定容器契约，不擅自扩展 container、encoding 或 chunk 模型。
- v1 的 `.ibla` 仍只承载单个纹理资产；specular 与 irradiance 分别输出独立文件，BRDF LUT 继续输出独立 `.png`。
- KTX2 输出固定为 BC6H_UFLOAT + zstd，不引入其他压缩格式。
- `packages/loader` 在 v1 中保持 parser-only，只处理 `.ibla`，不加入 KTX2 解析、PNG decode、RGBD decode、GPU 上传或运行时纹理封装。
- `packages/ktx2-loader` 在 v1 中保持 parser-only，只处理当前 `ibl-baker` KTX2 产物画像，不加入 zstd、BC6H decode、GPU 上传或运行时纹理封装。
- `packages/ibla-viewer` 是仓库内部验收工具，不作为公开运行时集成层承诺；保持手动拖拽入口，不耦合仓库 fixture 目录。
- `packages/ktx2-viewer` 是仓库内部验收工具，不作为公开运行时集成层承诺；首版保持手动拖拽入口，不耦合仓库 fixture 目录。
- 如需引擎适配、分发包装或额外运行时能力，放在独立包中实现，不反向污染核心库与 loader。

## 演进原则

- 优先保持 `.ibla` v1 和 KTX2 输出的稳定，不为了未来能力提前打破当前契约。
- 继续维持 Rust bake/core、ktx2_writer、CLI、TypeScript parser-only loader 分工，避免把运行时集成反向塞回核心库。
- 如需新增分发包装、引擎适配或浏览器侧消费层，放在独立包中推进，并以现有格式契约为边界。
- 如果未来需要引入新的 container、encoding 或更轻量的 payload 方案，应作为显式的新阶段设计处理。

## 计划与维护约定

- `TODO.md` 是当前唯一的执行清单，记录下一步工作和仍可能继续推进的事项。
- 每次完成 `TODO.md` 中的事项后，必须在同一轮改动里同步更新状态。

## 输出风格

- 创建或修改项目文件时，默认使用英文，保持命名一致、结构清晰、实现精简。
- 向用户汇报时，清楚说明改动内容、重要取舍和关键假设。
