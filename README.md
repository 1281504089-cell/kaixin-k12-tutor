# 开心动力超级学霸 · 学生体验版 1.7.1

独立桌面项目，含本机运行组件与当前启用的 136 册教材。安装文件不含 API Key、个人学习记录或签名私钥。

| 电脑 | 下载文件 | 验证 |
| --- | --- | --- |
| Apple 芯片 Mac | [下载安装文件](https://github.com/1281504089-cell/kaixin-super-scholar-desktop/releases/tag/student-ae6b75ad3-macos-arm64) | 分卷完整性、打包应用首次启动、UI/API、教材与退出清理通过 |
| Intel Mac | [下载安装文件](https://github.com/1281504089-cell/kaixin-super-scholar-desktop/releases/tag/student-ae6b75ad3-macos-x64) | 分卷完整性、打包应用首次启动、UI/API、教材与退出清理通过 |
| Windows x64 | [下载 Windows 候选安装包](https://github.com/1281504089-cell/kaixin-super-scholar-desktop/releases/tag/payload-42285703885-windows-x64) | 原生运行资源通过；最终新版安装程序尚未完成 Windows 试装 |

仓库已于 2026-11-07 按拥有者确认改为公开。Agent 和学生无需 GitHub 登录即可访问源码、历史记录与 Releases 安装资源；下载安装文件请使用上表的平台链接，并下载该平台全部分卷。安装包仍不含 API Key、个人学习记录或签名私钥。

历史 Release 说明或包内文档中“私有／需拥有者登录”的文字反映发布时状态；当前公开访问状态以本页为准。公开访问不改变第三方教材、组件及商用许可的适用条件。

## 安装

1. 只下载对应电脑的平台文件，不用下载 Source code。每个平台的全部分卷放入同一文件夹，保留原名。
2. Mac：一个 `.dmg` 和三个 `.dmgpart`。双击第一个 `.dmg`，把应用拖入 Applications。
3. Windows：一个 `Setup.exe` 和四个 `open-deeptutor-core-1.7.1-ae6b75ad3-x64.tar.gz.001` 至 `.004` 原始资源分卷，双击 Setup 即可自动校验合并。
4. 建议预留至少 30GB 空间。安装时校验资源，首次启动还会解压环境，两阶段均可能需要数分钟。
5. 新电脑在设置中填写自己的有效聊天接口；旧用户升级保留本机配置与学习记录。

## 本次交付

- 保留老师技能、九科各三个默认对话、项目与对话指令、昵称头像、学习报告、错题本、笔记及横屏布局。
- 照片直接读图；一至两页 PDF 先用页图回答，全文解析在后台进行。公式引用带原页选区图；两个上传入口共用临时附件。
- 配齐文档/OCR、检索、本机 STT 与 Embedding 模型、Manim、FFmpeg、LaTeX、字体、Remotion 与 GeoGebra 资源。
- 核心与界面冻结版本：`ae6b75ad32d58dba5eec3d636071150d5708938b`。Windows 安装器补齐 PowerShell 输入模式、跨 PowerShell 环境的 .NET SHA256 分卷校验与 zlib 外壳打包；自动试装脚本另作编码与无交互兼容修正。回答生成、流式逻辑与思考强度未改。

## 验证与边界

原生 CI 中实际执行了文档读取、中文扫描页、BM25/FAISS、本机模型、数值绘图、中文/公式 Manim 视频和 Remotion 编译/布局；全新学生目录检查不含学习记录，136 册教材可用。各下载页附组件、启动或安装检查结果与校验文件。Windows 原生资源已通过，上一版安装可完成且 UI/API 已响应；最终安装器在本机交叉封装，.NET 合并校验通过本机 PowerShell 回归，但 GitHub 额度／账单限制阻止了新 Windows runner，最终安装、退出和卸载未复验。Windows `validation.json` 如实标记未验证。

CI 全新用户目录与隐藏开发工具验证不等于学生实体电脑、旧系统或真实麦克风试装。此体验版未购买 Apple Developer ID/公证或 Windows 代码签名，首次安装可能出现系统来源提示。

独立栅格生图和文生视频接口按此前要求暂缓；SVG、数学动画与交互图不等同于独立生图服务。Edge 朗读、搜索、公开视频字幕及远程模型仍需网络和对应服务可用性。

GeoGebra 免费许可限非商业使用；Remotion 免费许可有主体规模等条件，正式机构分发前核对实际适用范围，未新增付费许可。详见 [接口与许可说明](delivery-notes.md)、[GeoGebra 官方许可](https://www.geogebra.org/license) 和 [Remotion 官方许可](https://www.remotion.dev/docs/license/pricing)。
