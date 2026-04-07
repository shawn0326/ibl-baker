# AGENTS.md

## 沟通规则

- 与用户沟通时使用中文。
- 汇报进度、实现细节和取舍时，保持简洁、清晰、以执行为导向。

## 项目语言规则

- 默认交付内容使用英文：源代码、标识符、提交信息、代码注释、README、文档、CLI 帮助文本、日志和错误信息、测试名称、示例文件、规范说明文件。
- 以下文件使用中文：`AGENTS.md`、`TODO.md`。

## 仓库速览

- 根目录同时使用 Cargo workspace 与 npm workspace。
- `crates/ibl_core`：Rust 核心库，负责源图读取、bake 主流程、`.ibla` 读写与校验。
- `crates/ibl_cli`：公开 CLI，负责参数解析、调用 `ibl_core`、输出 bake/validate 工作流。
- `packages/loader`：唯一公开 JS 包，提供 parser-only 的 `parseIBLA(buffer)`。
- `packages/e2e-loader`：私有浏览器验收工具，用于读取仓库内 fixtures、解析 `.ibla`、解码 PNG payload 并做中立可视化。
- `fixtures/outputs`：已提交的产物样例，供 loader 测试与浏览器验收复用。
- `scripts/refresh-fixtures.mjs`：刷新仓库内 fixtures 的入口脚本。

## 对外契约入口

以下文档是当前开发与维护时的优先依据：

- `docs/format-spec.md`
- `crates/ibl_cli/README.md`
- `packages/loader/README.md`

以下文档适合快速理解仓库结构与职责分层：

- `README.md`
- `crates/ibl_core/README.md`

规则：

- 实现必须遵守对外契约文档。
- 如果改动会影响公开行为、文件格式或 loader 契约，必须在同一轮改动里同步更新对应 README 或 docs。
- 能直接链接到 README 或 docs 的地方，优先链接，不在 `AGENTS.md` / `TODO.md` 里重复展开规格细节。

## 当前固定边界

- `.ibla` v1 继续保持稳定容器契约，不擅自扩展 container、encoding 或 chunk 模型。
- v1 的 `.ibla` 仍只承载单个纹理资产；specular 与 irradiance 分别输出独立 `.ibla`，BRDF LUT 继续输出独立 `.png`。
- `packages/loader` 在 v1 中保持 parser-only，不加入 PNG decode、RGBD decode、GPU 上传或运行时纹理封装。
- `packages/e2e-loader` 是仓库内部验收工具，不作为公开运行时集成层承诺。
- 如需引擎适配、分发包装或额外运行时能力，放在独立包中实现，不反向污染 `ibl_core` 与 `packages/loader`。

## 演进原则

- 优先保持 `.ibla` v1 的稳定、明确、可验证，不为了未来能力提前打破当前契约。
- 继续维持 Rust bake/core、CLI、TypeScript parser-only loader 三层分工，避免把运行时集成反向塞回核心库。
- 如需新增分发包装、引擎适配或浏览器侧消费层，放在独立包中推进，并以现有格式契约为边界。
- 如果未来需要引入新的 container、encoding 或更轻量的小 mip payload 方案，应作为显式的新阶段设计处理，而不是隐式扩展 v1。

## 计划与维护约定

- `TODO.md` 是当前唯一的执行清单，记录下一步工作和仍可能继续推进的事项。
- 每次完成 `TODO.md` 中的事项后，必须在同一轮改动里同步更新状态。

## 输出风格

- 创建或修改项目文件时，默认使用英文，保持命名一致、结构清晰、实现精简。
- 向用户汇报时，清楚说明改动内容、重要取舍和关键假设。
