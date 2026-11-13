# Windows 旧启动器一次迁移候选

此目录只准备轻量 Setup.exe 模板。最终应用源以统筹冻结的 `d321445…` 为准，本模板不改冻结源码，不附 Runtime 分卷，不承担首次完整安装。

## 编译输入

用 NSIS 3 Unicode 编译 `windows-migration.nsi`，传入 `SOURCE`、`OUTFILE`、`ICON`、`VERSION`、`FILEVERSION`，可选 `APPNAME`（默认“开心动力超级学霸”）。`FILEVERSION` 为四段数字；`VERSION` 也用作固定回退目录后缀，打包器应限制为安全的版本标识。

`SOURCE` 必须是打包器已经核对过的最终 Windows app 目录：移除 `resources/seed` 下的大归档及旧 update 目录，保留启动器所需的轻量元数据。NSIS 原样嵌入此目录，不在安装时下载资源。不要把旧完整包、用户 profile、测试设置或签名私钥放入 SOURCE。

`SOURCE` 内必须包含打包器提供并审核的 `resources/app/launcher-migration-check.mjs` 和 `resources/app/launcher-migration-payload.json` 文件 SHA 清单。安装器先把新 app 解到安装器临时目录，再通过新 app 的 Electron、`ELECTRON_RUN_AS_NODE=1` 执行检查，调用完成后恢复该环境变量。它不执行 profile 内未验证的 Node 或 Python。固定调用契约为：

```text
launcher-migration-check.mjs --profile <profile> --install-dir <固定入口> --target windows-x64 --report-file <安装器临时目录中的报告>
```

只有退出码 0 且成功报告确实生成才允许继续，任意检查失败返回 2。helper 必须只读验证：active.json 的当前运行环境与 base 的真实签名、架构和布局，所需 Python/Node 等资源存在，旧 app 身份匹配，安装与 profile 相互独立，安装及候选根目录没有重解析点或危险根路径，新 payload 与冻结文件清单匹配。它还必须检查已有 app、后端及其子进程；发现仍在运行或无法可靠读取进程状态时拒绝安装。检查器自身的新 Electron PID 应从进程检查中排除，不能直接把同名进程一律判为旧程序。helper 不写 profile，不读取或输出 Key 正文；报告只含无正文的文件指纹。**未接入符合此契约的 helper 前，模板不可交给学生使用。**

打包验收还必须确认最终候选 EXE 的 Electron `RunAsNode` fuse 启用，且真实 EXE 在 `ELECTRON_RUN_AS_NODE=1` 下确实执行 helper。源工程未发现关闭 fuse 的构建步骤，但这不能替代候选二进制的验证；若该模式关闭，正常 GUI 的退出码 0 不能当作校验成功。模板因此同时要求独立成功报告，且不在完成页自动启动应用。参见 [Electron 官方 fuse 说明](https://www.electronjs.org/docs/latest/tutorial/fuses)。

允许已经安装且验证有效的 `77f2ba387` 或 `04276f68a` 环境，按 active 与对应 installed/base 检查；不因种子元数据来自早期版本而强装或回退至 77 环境。

## 安装行为

正式模式沿用 HKCU `Software\开心动力超级学霸\InstallDir`；没有该记录时，只接受 `%LOCALAPPDATA%\Programs\开心动力超级学霸`。不显示可改目录页，不接受正式模式 `/D` 把程序放到其他临时位置。已有程序、`%LOCALAPPDATA%\开心动力超级学霸\active.json` 和 runtimes 是前提。

复制候选到同卷暂存目录后，从暂存 app 再运行 helper，检查复制后文件 SHA 及进程，再把旧程序整个目录改名为 `.launcher-<VERSION>.rollback`，把暂存目录改名为原固定入口。回退或暂存目录已存在时直接停止，绝不覆盖。原有 `Uninstall 开心动力超级学霸.exe` 在候选验证后复制到新入口；不创建新卸载器，不重写原卸载注册项。桌面和开始菜单快捷方式仍指向原固定入口。普通失败会把旧程序目录改回；恢复失败时保留两侧目录并给出错误码，不做递归删除。完成页不自动运行应用，通过保留的固定入口打开即可。

学习目录、Key、教材、任务及数据库不参与移动或复制。原程序目录中的未知文件也随旧目录留在 rollback，不能把该目录当垃圾自动清理。安装器不结束应用进程，也不预约重启替换文件；需要先正常退出应用。

## 隔离验收

编译时定义 `TEST_MODE`，设置 `OPEN_DEEPTUTOR_TEST_HOME` 到 `existing_isolated_profile`，再用 `/S /D=<隔离固定app目录>`（`/D` 放在最后）。NSIS 调用 helper 时额外传 `--require-isolated`；helper 必须要求 `.launcher-migration-synthetic.json` 标记，且 profile 不在真实 LOCALAPPDATA 根下。该模式拒绝正式 profile，且不会更改 HKCU 安装指针、卸载注册项、桌面或开始菜单快捷方式。隔离测试结束不应留下指向测试目录的正式入口。

Windows native CI 还必须单独核对正式模式默认入口解析和注册表/快捷方式清单，不能仅以 TEST_MODE 通过代替。至少验证正常迁移、软件运行时拒绝、无效 active/环境拒绝、已有 rollback 拒绝、复制或激活失败回退、原卸载器与学习文件保留；不能用便携临时目录启动成功冒充固定入口迁移。

`python test_windows_template.py` 只检查模板的静态安全边界；当前未做 NSIS native Windows 编译与实际迁移验收。NSIS 行为参考[官方指令文档](https://nsis.sourceforge.io/Docs/Chapter4.html)。
