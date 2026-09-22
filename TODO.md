# TODO

## 当前基线

- Rust bake/validate 主链路、`.ibla` v1 容器、parser-only TypeScript loader 已落地。
- KTX2 导出（BC6H + zstd）通过 `crates/ktx2_writer` 实现，CLI `--output-format <ibla|ktx2|both>` 可用。
- `.ibla` 与 `.ktx2` 两种输出格式地位对等，CLI 默认输出 `.ibla`。
- 当前对外契约以 `docs/format-spec.md`（纯 `.ibla`）、`crates/ibl_cli/README.md`（CLI + 双格式）、`packages/ibla-loader/README.md` 为准。
- `fixtures/outputs` 是本地生成且被 Git 忽略的样例目录；CI 使用临时样例。

## 已完成：v0.2.0 KTX2 导出

- [x] `crates/ktx2_writer` — write-only KTX2 序列化器，BC6H + zstd，无 CMake 依赖
- [x] `ibl_core` bake pipeline 分离 f32 计算层与编码层，支持 `.ibla` 和 KTX2 双路径
- [x] CLI `--output-format <ibla|ktx2|both>` 选项
- [x] KTX2 fixture 产物（当前 HDR fixture 使用 `--output-format both`，`spruit_sunrise_2k_ktx2` 保持独立 KTX2 输出）
- [x] 文档统一：format-spec 仅含 `.ibla`，KTX2 规格写入 CLI README，各级文档统一口径

## 下一步

- [x] PR1：解除 release tooling 对外层 npm 执行上下文和 JavaScript lockfile 格式的依赖，固定使用 npm 11.11.0。
- [ ] PR2：将 JavaScript workspace 切换到 pnpm，保留 npm 作为 npm registry 发布与消费者验证客户端。
- [ ] PR3：启用 pnpm Cargo 依赖安装与缓存，单独验证实验性 Cargo 集成。
- [ ] PR4：优化 pnpm CI 缓存和 workspace 任务编排。
- [ ] PR5：将发布器的手工依赖顺序抽象为通用依赖图。

- [x] 优先排查并修正 irradiance bake 过早绑定 `irradiance_size` 的问题，避免在卷积前先将源环境重采样到过低分辨率后再做 diffuse 过滤。
- [x] 优先排查并修正 irradiance 的 sample cap 偏低问题，重新对齐与参考实现的采样预算与 LOD 行为，避免 HDR 小范围高亮贡献被过度抹平。
- [x] 新增 `packages/ktx2-loader`，提供浏览器侧 KTX2 加载能力，并在 README 中明确当前仅支持仓库现阶段产物画像（如 `KTX2 + BC6H_UFLOAT + zstd + cubemap`）。
- [x] 新增 `packages/ktx2-viewer`，作为私有浏览器验收工具，支持拖拽 `.ktx2` 文件进行预览与错误展示。
- [x] `packages/ktx2-viewer` 首版不接仓库内 fixture 目录，优先支持手动拖拽验收，避免目录结构耦合。
- [x] 新增 `packages/ibla-viewer`，作为私有浏览器验收工具，支持拖拽 `.ibla` 文件、cubemap cross 预览与错误展示。
- [x] `packages/ibla-viewer` 显示路径与 `packages/ktx2-viewer` 对齐，统一使用 linear → Reinhard → gamma，便于对比 `.ibla` 与 `.ktx2` 输出。
- [x] 将手动浏览器验收入口收敛到 `packages/ibla-viewer` / `packages/ktx2-viewer`。
- [x] 将 `packages/ibla-viewer` / `packages/ktx2-viewer` 通过 GitHub Pages workflow 部署到仓库 Pages 子路径，继续保持手动拖拽验收入口。
- [x] 将公开 `.ibla` JS 包迁移为 `@ibltools/ibla-loader`（`packages/ibla-loader`），旧 `@ibltools/loader` 由发布者后续在 npm 手动废弃。
- [x] 修正 KTX2 BC6H UFLOAT header 的 Vulkan format 值为 `143`；新 writer 仅写标准值，新 loader 对既有 `131` 产物保留受限兼容。

## 自动发包流程

- [x] 实现共用 CI、三个发布组选项、候选归档、OIDC 发布与恢复机制。
- [x] 原地维护 docs/release.md，新增发布说明目录和 README 入口。
- [x] 完成本地 Rust、TypeScript、loader/viewer、发布规则及工作区外消费者检查。
- [x] 提交实施 PR #1 并通过 GitHub CI。
- [x] 配置 master 必经 PR、必过 CI、禁止强推和删除，已合并实施 PR #1。
- [x] 从 master 完成三个发布组的无上传预演（运行 35196405209），下载核对五包与三平台归档，结果见 docs/release.md。
- [ ] 下一次实际版本发布时验证所选包的 OIDC、provenance、上传后消费者及 Release 收尾。

## npm CLI 分发

- [x] npm 0.1.1 的 --version / -V 同时展示 npm 分发版本与实际 Rust CLI 版本；原生输出不变。

- [x] 实现原生版本命令、薄 launcher 和四包暂存打包。
- [x] 接入 npm_cli 发布组、三平台消费者和候选恢复校验。
- [x] 完成本地真实归档消费、Windows 控制台 Ctrl+C、62 项 Rust 测试及 23 项发布回归验证；Unix 信号测试由 Linux/macOS CI 执行。
- [x] 实施 PR #4 已通过 CI 并合并；Linux 归档消费者及 Unix 信号测试通过。
- [x] PR #5 修正 macOS 临时目录断言；master 的 npm CLI 单组预演 35302832171 与四组联合预演 35302835316 均通过。
- [x] 下载并独立核对两个候选的包、原生归档、版本及三平台报告，确认 npm/原生二进制一致；验收链接见 docs/release.md。
- [x] 完成四个 npm CLI 包 0.1.0 首次发布、registry 原包哈希校验及 Trusted Publisher 配置，详见 docs/release.md。
- [ ] 等待 npm 包索引可见并完成首次发布后的普通 registry 安装验收。
- [ ] 下一新版本通过正式工作流验证真实 OIDC、provenance 及三平台 registry 消费者。

## 需要单独立项再展开的方向

- [ ] 特定渲染引擎的运行时集成（放在独立包中设计）。
- [ ] 评估是否为 LDR 输入提供比 `BC6H_UFLOAT` 更合适的 KTX2 编码路径；仅在收益、兼容性与复杂度权衡明确后再决定是否引入。
- [ ] 参考实现对比升级为长期质量基线（单独定义基线产物、指标和回归策略）。
- [x] 明确 npm CLI 分发方案：薄 launcher、三个预编译平台包、独立 npm 版本，复用现有发布流程。

## 暂不纳入当前范围

- 浏览器端 baking
- Rust loader
- wasm loader / wasm core
- napi / node addon
- 通用多引擎适配层
- 在 v1 内提前扩展多种 encoding / container 组合

## 维护约定

- 任何会改变公开行为或文件契约的改动，必须同步更新对应 README 或 docs。
- 完成 TODO 项后，在同一轮改动里同步更新本文件状态。
