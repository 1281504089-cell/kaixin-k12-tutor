# 开心动力超级学霸

中文桌面学习应用，支持教材与边读边问、题库、错题和笔记、九科学习项目、任务看板、实时语音及高拍仪。

正式安装文件见 [GitHub Latest](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/latest)。本说明对应 `student-20261117-k12-8`。

## 本批变化

1. 在当前聊天打开教材，保留原聊天、项目与阅读位置。
2. 资料入口统一分为教材库、题库、长期资料。
3. 聊天加号可直接引用资料、原页或原题，浅蓝色来源可跳转查看。
4. 任务关联后短暂显示“已关联”，不再自动弹出右栏。
5. 设置提供恢复显示偏好的入口，保留API、模型、老师规则和学习数据。
6. “关于”显示正在运行的完整构建号，便于确认真正更新到了哪一批。

## 安装与更新

已有软件使用“设置 → 关于 → 检查更新”或顶部“核心 → 检查更新”，点击“下载并更新”。只有出现“重新打开完成更新”提示时才按提示重开。无需先卸载、清空聊天或删除学习目录。

完成后在“设置 → 关于 → 当前已安装版本”核对构建号包含 `20261117-k12-8`，再检查一次更新。`v1.7.1`是主版本，不能单独用来判断批次；本批配套启动器为 `20261118-updater-4`。

新电脑请从[同批发行页面](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-20261117-k12-8)下载对应系统的完整一组，不使用页面底部的Source code代替安装包。

| 电脑 | GitHub所需文件 | 打开哪个 |
| --- | --- | --- |
| Windows x64 | Setup和4个Runtime，共5份，同一文件夹 | Setup.exe |
| Intel Mac | 首卷dmg和002至005，共5份 | 只打开首卷-part.dmg |
| Apple芯片Mac | 首卷dmg和002至004，共4份 | 只打开首卷-part.dmg |

两种Mac需macOS13或以上。首次安装建议预留40GB临时空间。Windows完整ZIP先“全部解压”，Mac挂载后拖入“应用程序”。首次启动默认简体中文，填写自己的模型API；麦克风、摄像头和共享屏幕按需要授权。详细步骤及文件链接见[首次安装](INSTALL-LATEST.md)。

正常更新显示实际下载大小与进度；本批核心约799MiB，首次完整安装及某些历史运行环境会更大。下载需要能访问GitHub，无需GitHub Token。遇到错误请保留错误文字和运行日志，按[历史迁移说明](MIGRATE-LEGACY.md)核对完整构建，不串装旧补丁或修改运行环境编号。

## 学习资料与记录

保留136册教材、12,101条有效参考片段，698份理科原生题页PDF（3,888页、绑定6,915条记录）及294条预制题图。17条已有异常继续隔离。原生题页含整页或单元，不全部等于精准单题裁图。

本批保留既有老师规则、高思考档位与输出预算。独立语义检索和学习年级候选尚未合入；模型质量与速度验证边界见[更新说明](RELEASE-NOTES.md)。

U盘目前仍是原第4批，已由用户取走，内容未替换；GitHub版本与U盘交付分别记录。安装包不包含个人记录、API Key或签名私钥。

## 开发与验证

完整版本、签名与回执见 [CURRENT-DESKTOP-RELEASE.json](CURRENT-DESKTOP-RELEASE.json)。源码重建按[SOURCE-RECONSTRUCTION.json](SOURCE-RECONSTRUCTION.json)、source-manifest.json及有序补丁执行；source-overlay为增量包，不能当完整源码。主分支保留薄配方，题库生成资料另按[BANK-RECOVERY.md](BANK-RECOVERY.md)核对恢复。

保留上游LICENSE与THIRD_PARTY_NOTICES.md。[上游DeepTutor](https://github.com/HKUDS/DeepTutor)。
