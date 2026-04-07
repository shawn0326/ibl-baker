# TODO

## 当前基线

- `.ibla` v1 容器、Rust bake/validate 主链路、parser-only TypeScript loader、浏览器侧验收工具已经落地。
- 当前对外契约以 `docs/format-spec.md`、`crates/ibl_cli/README.md`、`packages/loader/README.md` 为准。
- 当前公开 JS 面仅保留 `packages/loader`；`packages/e2e-loader` 继续作为仓库内私有验收工具存在。

## 下一步

- [ ] 为 `packages/e2e-loader` 增加更多 fixture、资产类型与手动浏览器验收覆盖，降低后续改动只靠单一路径验证的风险。
- [ ] 补充基于 glTF-IBL-Sampler 参考产物的图像差异回归 fixture，以及 RMSE / PSNR 对比测试。
- [ ] 评估极小 mip 是否需要更轻量的 payload 方案；如果需要，先形成独立 codec / metadata 方案，再决定是否进入 v2。
- [ ] 仅在 CLI 分发与预编译二进制方案明确后，再评估是否创建 `packages/baker`。

## 需要单独立项再展开的方向

- [ ] 如需新增特定渲染引擎的运行时集成，放在独立包中设计与实现。
- [ ] 如需把参考实现对比升级为长期质量基线，再单独定义基线产物、指标和回归策略。

## 维护约定

- 任何会改变公开行为或文件契约的改动，必须同步更新对应 README 或 docs。
- 完成 TODO 项后，在同一轮改动里同步更新本文件状态。

## 暂不纳入当前范围

- 浏览器端 baking。
- Rust loader。
- wasm loader / wasm core。
- napi / node addon。
- 通用多引擎适配层，或把 three / Babylon / t3d 统一抽象成单一运行时接口。
- 额外 container（如 `ktx` / `ktx2`）。
- 在 v1 内提前扩展多种 encoding / container 组合。
- 过早引入插件化或渲染器绑定抽象。
