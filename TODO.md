# TODO

## 当前基线

- Rust bake/validate 主链路、`.ibla` v1 容器、parser-only TypeScript loader 已落地。
- KTX2 导出（BC6H + zstd）通过 `crates/ktx2_writer` 实现，CLI `--output-format <ibla|ktx2|both>` 可用。
- `.ibla` 与 `.ktx2` 两种输出格式地位对等，CLI 默认输出 `.ibla`。
- 当前对外契约以 `docs/format-spec.md`（纯 `.ibla`）、`crates/ibl_cli/README.md`（CLI + 双格式）、`packages/loader/README.md` 为准。
- `fixtures/outputs` 已包含 `.ibla` 和 `.ktx2` 样例产物。

## 已完成：v0.2.0 KTX2 导出

- [x] `crates/ktx2_writer` — write-only KTX2 序列化器，BC6H + zstd，无 CMake 依赖
- [x] `ibl_core` bake pipeline 分离 f32 计算层与编码层，支持 `.ibla` 和 KTX2 双路径
- [x] CLI `--output-format <ibla|ktx2|both>` 选项
- [x] KTX2 fixture 产物（`royal_esplanade_1k_ktx2`、`spruit_sunrise_2k_ktx2`）
- [x] 文档统一：format-spec 仅含 `.ibla`，KTX2 规格写入 CLI README，各级文档统一口径

## 下一步

- [x] 优先排查并修正 irradiance bake 过早绑定 `irradiance_size` 的问题，避免在卷积前先将源环境重采样到过低分辨率后再做 diffuse 过滤。
- [x] 优先排查并修正 irradiance 的 sample cap 偏低问题，重新对齐与参考实现的采样预算与 LOD 行为，避免 HDR 小范围高亮贡献被过度抹平。
- [x] 新增 `packages/ktx2-loader`，提供浏览器侧 KTX2 加载能力，并在 README 中明确当前仅支持仓库现阶段产物画像（如 `KTX2 + BC6H_UFLOAT + zstd + cubemap`）。
- [ ] 新增 `packages/ktx2-viewer`，作为私有浏览器验收工具，支持拖拽 `.ktx2` 文件进行预览与错误展示。
- [ ] `packages/ktx2-viewer` 首版不接仓库内 fixture 目录，优先支持手动拖拽验收，避免目录结构耦合。

## 需要单独立项再展开的方向

- [ ] 特定渲染引擎的运行时集成（放在独立包中设计）。
- [ ] 评估后续是否将当前 `packages/loader` / `packages/e2e-loader` 重构收敛为 `ibla-loader` / `ibla-viewer`，作为独立阶段推进。
- [ ] 评估是否为 LDR 输入提供比 `BC6H_UFLOAT` 更合适的 KTX2 编码路径；仅在收益、兼容性与复杂度权衡明确后再决定是否引入。
- [ ] 参考实现对比升级为长期质量基线（单独定义基线产物、指标和回归策略）。
- [ ] 仅在 CLI 分发与预编译二进制方案明确后，再评估是否创建 `packages/cli`。

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
