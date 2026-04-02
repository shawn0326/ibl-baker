# TODO

## 初始化阶段原则

- [ ] 先搭最小可运行骨架，只创建当前开发必需的目录和包
- [ ] 第一阶段优先 Rust workspace + `ibl_core` + `ibl_cli`
- [ ] 暂不一次性创建 `packages/baker`、`packages/loader` 的完整实现
- [ ] 暂不引入渲染库绑定、插件式抽象、额外 encoding/container 组合

## 阶段目标

- [ ] 先打通一个最小闭环：定义 `.ibla` 格式基础、建立 `ibl_core` API 骨架、让 CLI 能调用 core
- [ ] 先把“格式和边界”定稳，再逐步补 HDR 处理、prefilter、TS loader 和 npm 包

## 仓库初始化

- [x] 创建根 `Cargo.toml` workspace
- [x] 创建 `crates/ibl_core`
- [x] 创建 `crates/ibl_cli`
- [x] 补充基础 `README.md`
- [x] 补充 `LICENSE`
- [x] 只创建当前需要的基础目录；`packages/`、`examples/`、`scripts/` 可延后按需补齐

## 核心边界先定稿

- [x] 固定项目命名：`ibl-baker`、`.ibla`、`IBLA`、`@ibltools`
- [x] 固定单文件单资产模型，不再使用资源包语义
- [x] 定义第一阶段固定策略：`encoding = rgbd`、`container = png`
- [x] 在格式层为 `rgba8`、`rgba16f`、`rgba32f` 预留 `pixelFormat`
- [x] 固定 cubemap face 顺序
- [x] 固定 roughness 与 mip 映射规则
- [x] 固定 RGBD range 策略和还原公式
- [x] 固定单图 payload 粒度规则
- [x] 将 RGBD / 拓扑语义并入 `docs/format-spec.md`，避免重复规范漂移

## 文档先写最小规范

- [x] 编写 `docs/format-spec.md` 初版，明确 Header / Manifest / Chunk Table / Binary Chunks
- [x] 编写 `docs/cli.md` 初版，明确子命令和首批参数范围
- [x] 编写 `docs/loader-api.md` 初版，明确解析和 decode 方向
- [x] 将后续路线单独整理到 `docs/roadmap.md`

## `ibl_core` 最小骨架

- [x] 定义 `IblAsset`、`InspectInfo`、`ValidationReport` 等核心数据结构
- [x] 定义顶层 API 签名：
- [x] `bake_to_asset(input, options) -> IblAsset`
- [x] `write_asset(path, &asset)`
- [x] `read_asset(path) -> IblAsset`
- [x] `inspect_asset(&asset) -> InspectInfo`
- [x] `validate_asset(&asset) -> ValidationReport`
- [x] `extract_asset(&asset, dir)`
- [x] 先实现 `.ibla` manifest / chunk table 的序列化与反序列化骨架
- [x] 先实现 `inspect / validate / extract` 的基础流程，占位即可，不必一开始做完整算法

## `ibl_cli` 最小骨架

- [x] 建立 CLI 入口和参数解析
- [x] 接好 `bake / inspect / validate / extract` 四个子命令骨架
- [x] 为 `bake` 增加 `--asset` 参数，明确单文件单资产输出
- [x] 打通 CLI 到 `ibl_core` 的调用链
- [x] 统一错误输出、日志风格和退出码

## 初始化阶段验证

- [x] 为 `.ibla` 读写补最小测试
- [x] 为 `inspect / validate / extract` 补最小测试
- [x] 补一个最小示例输入和命令行调用示例
- [x] 先验证“命令能跑通、结构能读写、错误能看懂”，暂不追求完整烘焙质量

## 明确延后事项

- [ ] `packages/loader` 待 `.ibla` 格式和 Rust 输出稳定后再创建
- [ ] `packages/baker` 待 CLI 稳定、预编译分发方案明确后再创建
- [ ] 更完整的 `examples/`、`scripts/`、文档矩阵按实际开发节奏补充
- [ ] HDR 读取、latlong -> cubemap、prefilter、irradiance、BRDF LUT 逐项实现，不在初始化阶段一次做完
- [ ] HDR / EXR 转换链路接入后，补高精度 `pixelFormat` 实际写出，不默认降级到 `rgba8`
- [ ] 后续评估极小 mip 层级是否跳过 PNG、改用更轻 payload 存储；如要支持，再单独设计 per-chunk codec 元数据
