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

- [ ] 为 `packages/e2e-loader` 增加 `.ktx2` 产物的浏览器侧目视验收。
- [ ] 增加更多 fixture、资产类型与手动浏览器验收覆盖，降低后续改动只靠单一路径验证的风险。
- [ ] 补充基于 glTF-IBL-Sampler 参考产物的图像差异回归 fixture，以及 RMSE / PSNR 对比测试。
- [ ] 评估极小 mip 是否需要更轻量的 payload 方案；如果需要，先独立设计再决定是否进入 v2。
- [ ] 仅在 CLI 分发与预编译二进制方案明确后，再评估是否创建 `packages/baker`。

## 需要单独立项再展开的方向

- [ ] 特定渲染引擎的运行时集成（放在独立包中设计）。
- [ ] 参考实现对比升级为长期质量基线（单独定义基线产物、指标和回归策略）。

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
