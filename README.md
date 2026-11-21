# 开心动力超级学霸

开心动力超级学霸是一款面向学生的中文桌面学习应用。可以带着作业问老师，打开教材边读边问，也可以把讲义和试卷存下来，下次接着用。

- 想听讲解，点回答下方的朗读。想和老师边说边聊，用语音通话。要给老师看纸上的题，用高拍仪。
- 想安排复习，从聊天里的「规划」开始。错题、笔记、日历和任务看板都在左侧工作台。

**[下载桌面版图文操作手册](docs/desktop-student-guide.pdf)** · [首次安装说明](INSTALL-LATEST.md) · [Windows 安装包](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-20261122-windows-startup-1) · [Mac 安装包](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/latest)

手册对应 `student-20261117-k12-13`，按学生要做的事分节。首次通过 GitHub 下载安装包时，中国大陆用户请先开启 VPN。已经安装可在应用内检查更新。

## 本批变化

Windows 专项更新修复安装后启动失败、升级中断时从备份恢复，以及恢复后的启动器更新入口。Windows x64 用户可在应用内检查更新。
- 静态图、动态图、主动配图和参考图共用核对后的图库。动态图在正文、右栏与全屏显示完整表达式和滑块。
- 教材蓝色链接打开实际 PDF 页，重开历史保留引用、图和答题记录。
- 出题承接当前知识点，依次查询授权长期资料、题库和教材。各题型参加检索，合适的非选择题保留条件和出处改编成选择题。
- 新对话的快图完成后直接显示。已安装三端支持签名增量、整包回退和学习记录保留。

[查看 20261121-resource-5 的详细更新](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-20261121-resource-5)

## 安装与更新

已有软件在「设置 → 关于 → 检查更新」或顶部「核心 → 检查更新」升级。默认使用 COS，访问或校验失败可回退 GitHub。

新电脑下载对应平台的全套安装文件。GitHub 无法访问时，需要开 VPN。 [首次安装说明及三端文件](https://github.com/1281504089-cell/kaixin-k12-tutor/blob/main/INSTALL-LATEST.md)

## 学习资料与记录

保留136册教材、12,101条有效参考片段，698份理科原生题页PDF（3,888页、绑定6,915条记录）及294条预制题图。17条已有异常继续隔离。原生题页含整页或单元，不全部等于精准单题裁图。

本批保留既有老师规则、高思考档位与输出预算。独立语义检索和学习年级候选尚未合入；模型质量与速度验证边界见[更新说明](RELEASE-NOTES.md)。

U 盘以盘内说明和交付回执为准。安装包不包含个人学习记录、API Key 或签名私钥。

## 开发与验证

完整版本、签名与回执见 [CURRENT-DESKTOP-RELEASE.json](CURRENT-DESKTOP-RELEASE.json)。源码重建按[SOURCE-RECONSTRUCTION.json](SOURCE-RECONSTRUCTION.json)、source-manifest.json及有序补丁执行；source-overlay为增量包，不能当完整源码。本批冻结源码差分与摘要见[版本源码载体](https://github.com/1281504089-cell/kaixin-k12-tutor/blob/8280c758378e646527e0fe87580a19e0f2bc452e/releases/student-20261121-resource-5.json)。主分支保留薄配方，题库生成资料另按[BANK-RECOVERY.md](BANK-RECOVERY.md)核对恢复。

保留上游LICENSE与THIRD_PARTY_NOTICES.md。[上游DeepTutor](https://github.com/HKUDS/DeepTutor)。
