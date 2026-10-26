# TODO

## 当前基线

- Rust bake/validate 主链路、稳定的 .ibla v1、KTX2 导出与独立 BRDF LUT 已落地。
- 核心库、KTX2 writer、CLI、两个 parser-only loader 和私有 Pages site 的职责边界保持稳定；site 使用手动拖拽入口。
- 当前对外契约以 [IBLA 规范](docs/format-spec.md)、[CLI README](crates/ibl_cli/README.md)、[IBLA loader README](packages/ibla-loader/README.md) 和 [KTX2 loader README](packages/ktx2-loader/README.md) 为准。
- 后续按[运行时契约](docs/runtime-contract.md)优先保证方向、归一化和明显画面正确性，再考虑输出稳定、参数简洁、烘焙/加载性能与 GPU 查询成本；小误差研究作为诊断，历史 15%/10% 指标不再作为所有改动的统一发布门槛。
- 根目录使用 Cargo 与 pnpm workspace；pnpm 安装 Cargo source，Cargo 负责 Rust 构建和发布，npm 负责 registry 发布与消费者验收。
- 本地输出位于被 Git 忽略的 fixtures/outputs；CI 使用 target/ci-fixtures。CI 覆盖格式检查、Clippy、源码语法、类型检查、测试及归档消费者。
- 2026-09-29 已正式发布 Rust/CLI 0.2.3、KTX2 loader 0.3.0 和 npm CLI 0.1.1；所选八包的 OIDC、完整性、provenance、消费者和 Release 收尾已验证，.ibla loader 未参与此次发布。
- 发布操作以 [Release Process](docs/release.md) 为入口；历史 PR、bootstrap、预演与发布证据见 [Release History](docs/release-history.md)。

## 本轮收尾

- [x] 调整工作重点并补齐运行时消费契约，明确 irradiance 的 E/π、BRDF LUT 线性 RG、roughness 查询、方向、RGBD 过滤近似、按层解压及零拷贝视图生命周期；精简 CLI 帮助的常用/高级参数分层，修正 README 的旋转单位为度，见[运行时契约](docs/runtime-contract.md)。
- [x] 完成加载、投影、过滤、编码/打包/写出的耗时及阶段内存剖析；CLI 单作业共享一次源解码，基础 cubemap 改为所有权转移，LUT 写出借用字节。512 面宽九组产物逐字节一致，进程峰值提交内存降低 19.7%–37.0%，六面 JPEG 稳定提速 8.1%–10.5%；明确编码阶段因保留源图而增加内存的权衡，见[性能验收报告](docs/pipeline-performance.md)。
- [x] 完成以 `a306d63` 为增量基线的过滤源 LOD/mip 插值预计算；浮点逐位回归和八组兼容矩阵通过，512 面宽三类输入/三种格式的九组产物逐字节一致，耗时下降 11.3%–20.5%，峰值提交内存基本持平。保持完整链、默认画质和消费契约，不新增公开参数；124 项 Rust 测试及本地静态检查通过，见[过滤优化验收报告](docs/lod-performance.md)。

- [x] 分离浮点 cubemap 烘焙与格式编码，CLI `both` 每个资产只烘焙一次；各格式独立截断告警及部分成功语义保持不变，见[核心库说明](crates/ibl_core/README.md)。
- [x] 增加 `--specular-min-size` 与 `BakeOptions::specular_min_size`，覆盖 NPOT、极小尺寸、完整 roughness 重烘焙及两个真实 loader；补充消费方实际级数和禁用自动 mip 的约定，见[CLI 说明](crates/ibl_cli/README.md#specular-levels)。
- [x] 加入独立 BRDF LUT 数值参考回归及隔离的画质/编码/交替性能实验工具；生产源 LOD、采样曲线和默认完整链暂时保持不变。
- [x] 完成优化候选筛选、编码/截断分离、历史版本对照、固定材质画面和 27 组端到端性能验收；所有候选均触发必要质量门槛失败，保留 `auto=1` 及原算法。`both` 耗时降至基线的 56.4%–58.8%；实际 site 五层预览通过，详见[优化验收报告](docs/quality-optimization-acceptance.md)。

- [x] 完成完整 mip 链下的线性预算、样本数/源足迹解耦与 BC6H 搜索/补边实验；4635 个 HDR 参考查询全部收敛。线性及全面补边仍有最终采样退化，生产保留二次预算，仅采用 1×1 均匀块修复；27 组端到端耗时为共享烘焙基线的 0.994–1.006 倍，静态线性候选九组为 1.176–1.369 倍。格式、消费约定和公开参数不变，详见[完整链验收报告](docs/sampling-encoding-acceptance.md)。

- [x] 完成 HDR 编码范围截断防护、核心库 BakeReport 与 CLI 按实际输出汇总的 stderr 告警；范围边界、跨面/mip 计数、两种格式独立告警、写入失败无告警和正常载荷兼容性已通过验收，契约见 [CLI README](crates/ibl_cli/README.md) 与 [核心库 README](crates/ibl_core/README.md)。
- [x] 实现固定名称 CI Gate，汇总 Linux Quality 与 Windows/macOS Cargo 检查，仅 success 结果通过。
- [x] 修正 bootstrap 当前状态，归档历史发布证据并精简执行清单。
- [x] 完成 PR 的失败、取消、跳过与成功路径验收，并验证新的必过检查；验收证据记录在 Release History。
- [x] 完成跨面无缝采样与奇数尺寸源 mip 完整覆盖；解析测试、cmgen 实际浮点产物及画面复核、逐场景性能门槛和 Windows/macOS 编译检查通过，保留轻微退化与已有粗尾层误差，见 [阶段二验收报告](docs/source-sampling-acceptance.md)。
- [x] 完成立体角加权源 mip 的独立、小规模可行性研究；离散积分与覆盖验证通过，但收益未达到扩展门槛，并保留局部退化及 HDR 参考未裁定项。生产继续使用 box；512、完整画面与生产性能矩阵未开展，见 [可行性报告](docs/mip-weighting-feasibility.md)。
- [x] 修复 specular 在 `--samples < 8` 时的采样预算下溢，保留低正值并将 0 按 1 使用及记录；默认预算不变，核心预算边界和两种格式的小尺寸 CLI 回归通过，契约见 [CLI README](crates/ibl_cli/README.md)。
- [x] 补齐 KTX2 writer、Rust IBLA 读写/校验及两个 loader 的 mip 拓扑校验；保留合法截断链、非 2 幂尺寸和矩形单面纹理，提前拒绝超长尾链及错误尺寸记录，定向回归通过，契约见 [IBLA 规范](docs/format-spec.md) 与对应 README。

## 待验证

- [ ] 本轮分支合入/发布前取得新的 Linux Quality 和 macOS Cargo CI 结果；本地 Windows Rust、两个 loader、site 和 npm CLI 验收通过，远端平台结果不得以历史绿灯替代。

- [ ] 自然发生部分生产发布失败时，记录真实恢复证据；当前恢复顺序和 checksum 防护已有模拟测试覆盖，不人为制造生产发布故障。
- [ ] 在 .ibla loader 下一次实际版本发布时，补充该包的生产 OIDC/provenance 和 registry 消费者验收。

## 需要单独立项的方向

- [ ] 特定渲染引擎的运行时集成，放在独立包中设计。
- [ ] 评估 LDR 输入的其它 KTX2 编码路径；以收益、兼容性和复杂度的明确权衡为前提。
- [ ] 将参考实现对比升级为长期质量基线，单独定义基线产物、指标和回归策略。
- [ ] 仅在出现新的可复现收益证据后，单独研究源 mip 足迹与 FIS 重建的联合策略；当前加权候选不进入生产，未来仍需完整画质与逐场景性能验收。
- [ ] 仅在出现明显视觉问题时恢复强太阳覆盖、粗尾直接积分或采样序列研究；先固定画面复现、实际使用条件和性能预算，再选择局部实验。保留已有收敛数据，不默认扩展更高尺寸/更多参考查询，也不把像素编码 SSE 改善等同于最终画面改善。

## 暂不纳入当前范围

- HDR 全局缩放、恢复倍率与外部消费协议；仅在代表性场景持续出现明显高光问题后重新评估。
- 浏览器端 baking、Rust loader、Wasm、N-API / Node addon 和通用多引擎适配层。
- 在 .ibla v1 内提前扩展 encoding、container 或资产模型。

## 维护约定

- 改变公开行为或文件契约时，同步更新对应 README 或 docs。
- 完成 TODO 项后，在同一轮改动里同步状态；规格细节优先链接对外契约文档。
