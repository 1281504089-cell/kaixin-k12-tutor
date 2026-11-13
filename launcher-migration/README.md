# 旧启动器一次迁移：打包与资料保留辅助

此目录是交给统筹发行流程的**候选打包工具**，不是学生下载页，也不是已完成三端试装的迁移包。冻结桌面源码为 `d3214451efd0a392aca1000805362626632cc858`，`frozen-shell.json` 锁定其中 26 个启动器源码及资源文件。

仅取最终完整安装包中已构建的 `.app` / Windows app 目录，保留 Electron 外壳、真实早期签名 seed 元数据，剔除 seed 大归档和整个 `resources/update`。不打包 profile，不读取真实学习记录或 Key，不改稳定清单，不发布、不写 U 盘。

## 四项主要输入

| 参数 | 输入 |
| --- | --- |
| `--final-installed-app-dir` | 本批最终安装的 `.app`，或 Windows 含主 EXE、resources 的 app 目录；不能用旧 shell 冒充 |
| `--target` | `windows-x64`、`macos-x64`、`macos-arm64` |
| `--existing-isolated-profile` | 已有合法签名运行环境和**合成**聊天/任务/测试 Key 的隔离 profile |
| `--output-dir` | 与 app、profile 均不重叠的全新输出目录 |

隔离 profile 根须有 `.launcher-migration-synthetic.json`，内容 `{"synthetic":true}`。禁止给真实资料目录加标记来绕过保护。profile 必须有签名有效的 `active.json`、对应 `runtimes/<id>/installed.json`、所需 base、Python/Node 和 core/web，不能是空目录。

默认使用本目录 `baselines/runtime-<target>.json` 的三份真实早期完整 seed 元数据，来自本机留存的 `ci-bootstrap/final-delivery/delivery-signed-<target>.json`，已用冻结 shell 的公钥再次验证原签名。原始路径和文件 SHA 见 `baselines/provenance.json`。协调方从历史公开 `payload-42341195532-<target>/runtime.json` 取回的版本未通过当前公钥验签，**本工具没有使用这些公共原始 payload 清单**；GitHub 文件 digest 正确不代表桌面运行环境签名有效。也可另传 `--baseline-manifest <真实旧77完整签名JSON>`；必须是原始完整元数据，不接受带 `baseRuntimeId` 的薄更新，不改 runtimeId、builtAt 或签名，也不重新签一个假“早期版本”。seed 公钥必须与最终 shell 相同。使用 042 profile 时不要求本地额外安装 77 环境。

运行前需要 Python 3.10+ 和 Node.js 22+；这只是制包工具要求，学生使用时不需要安装开发工具。

```bash
python3 -B package_launcher.py \
  --final-installed-app-dir '/build/final/开心动力超级学霸.app' \
  --target macos-arm64 \
  --existing-isolated-profile '/build/qa/synthetic-profile' \
  --output-dir '/build/out/launcher-migration' \
  --baseline-manifest '/build/authentic-old77/runtime-macos-arm64.json' \
  --node '/build/toolchain/node'
```

Windows 相同参数，target 改 `windows-x64`；另需 NSIS 3 Unicode 的 `makensis`，可用 `--makensis <path>` 指定。原生 Windows 编译 TEST_MODE 验收副本时加 `--test-installer`；该副本不得交给学生。正式迁移 Setup 不需要 Runtime 分卷，也不会暗中改用便携 ZIP。

## 产物与固定入口

- Mac：`Kaixin-Launcher-Migration-d3214451efd0-macos-<arch>.zip`，其中只有可替换原固定入口的 `开心动力超级学霸.app`。会重新做 ad-hoc 签名并严格校验；**没有 Developer ID 签名和 Apple 公证**。这是一次性外壳替换，不是完整新装包。先正常退出旧软件，保留旧 app 作为回退，再在原 Applications 固定位置替换同名 app；不删除 Application Support 中的学习目录。不能把 ZIP 放进 Downloads 后一直从临时副本启动，冒充已迁移固定入口。
- Windows：`Kaixin-Launcher-Migration-d3214451efd0-windows-x64-Setup.exe`。沿用原 HKCU/default 固定入口。详情见 [WINDOWS.md](WINDOWS.md)。两次只读预检后，同卷改名旧程序为版本固定 rollback，再启用新程序；保留原卸载器、注册指针与学习目录，不强制结束其他进程。
- 同名 `-report.json`：归档 SHA256、真实 seed 文件摘要、冻结 shell、静态预检和未验项。**`nativeMigration` / `nativeUpdateUI` 初始均为 `not_run`**，不能把打包通过当成原生界面升级通过。

包内清单验证 Windows 的完整候选文件集合；Mac 对签名会修改的 `MacOS`、`Frameworks` 和签名目录使用 `codesign --verify --deep --strict`，SHA 清单覆盖其余资源。最终 ZIP/Setup 另有完整归档 SHA256。

## 原生 CI 的接入契约

统筹 CI 已单独负责原生 Electron 更新入口驱动，本工具不重复实现。使用与最终产物同字节的 app 验证以下链路：

1. 已安装的 `77f2ba387` 和 `04276f68a` 分别准备合成 profile、聊天、任务、测试 Key、阅读记录；应用正常退出后建立下述检查点。
2. 从最终完整 app 制作小迁移包。校验 ZIP/Setup SHA、seed 签名和无大归档。Windows 原生直接用**候选自身的 EXE**执行嵌入 helper，并取得成功报告，确认 Electron 的 `ELECTRON_RUN_AS_NODE` 可用；外部 Node 静态预检不替代这一项。
3. Mac 在隔离固定 Applications 入口替换 `.app`；Windows 在 TEST_MODE 的隔离固定入口运行 Setup。环境变量 `OPEN_DEEPTUTOR_TEST_HOME` 始终指向同一个合成 profile，禁止打开真实账号。
4. 实际启动新固定入口，经过 renderer 的 `kaixinDesktop.checkForUpdates` IPC 完成检查、真实下载、验签、备份、核心切换与重启；再次检查得到已是最新。进程归属、成功弹窗和重启证据由统筹驱动记录。
5. 正常退出后比较资料保留结果；三端转写和随包 FFmpeg 的真实验证由统筹 CI 独立记录，不能用本目录的离线夹具代替。

资料指纹工具只输出合成数据的哈希与行数，不输出 Key/聊天/任务正文：

```bash
python3 -B verify_profile.py --profile '/qa/synthetic-profile' --out '/qa/before.json'
# 运行一次迁移、启动与检查更新；正常退出应用后：
python3 -B verify_profile.py --profile '/qa/synthetic-profile' \
  --before '/qa/before.json' --out '/qa/preservation-report.json'
```

必须保留原设置文件、附件和每条 SQLite 原有记录；允许数据库增加新表/新行，不接受原行减少或修改。若新版本确需数据迁移而改变原行，本工具会报差异，交统筹审核迁移语义，不放宽成“通过”。空 profile、未退出留下非空 WAL、真实用户目录都会拒绝。

## 不触网自检

```bash
python3 -B test_migration.py --node '/toolchain/node' \
  --frozen-source '/checkout/final-frozen-source' -v
python3 -B test_windows_template.py
```

使用临时 Ed25519 测试签名，只放在自动删除的夹具中；**测试签名不会进入生产包**。覆盖三个 target 的资源剥离、原 seed 字节保留、042 profile 复用、缺 base/坏签名/未标记目录/篡改 payload/外部链接/输出重叠拒绝、数据丢失识别，以及真实更新模块的离线可调用性。

## 明确限制

此 shell 的日常“检查更新”仍只升级已签名学习核心/前端与相容运行资源，**不能自动替换 Electron/启动器自身**。因此需要这一次小迁移包；不能声称推送 core 已修复所有历史旧更新器。将来再次修改外壳时仍须判断是否需要新的外壳迁移能力。

当前只完成工具与离线自检。最终小包须等本批最终完整 app 构建后，使用真实旧 seed 制作，再由三端原生 CI 补齐固定入口覆盖、失败回退、真实更新与资料保留验收；未补齐前不发布给学生。
