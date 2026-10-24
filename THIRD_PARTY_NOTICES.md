# 上游来源与修改记录

## gpt-instruct

- 仓库：https://github.com/MDX-Tom/gpt-instruct
- 固定提交：`3ab84df64468bb74cc9eb4e5423660083953c44f`
- 原文件：`codex-instruct.py`
- 原文件 Git blob：`b55d4a181105ac1f7d932e3c3343c65cff00f7e9`
- 许可证：MIT，全文保留在 `third_party/gpt-instruct/LICENSE`。
- 原版权：`Copyright (c) 2026 li lingbo`、`Copyright (c) 2026 yynxxxxx`。

### 复用范围

`tools/manage_skill.py` 中的 `atomic_write_text` 源自该版本的同名函数。`tools/manage_prompt.py` 改写了字段定位、字段替换和原子写入实现。备份、SHA256 所有权记录、更新回滚与测试设计参考了同一上游。

`prompts/ai-pojia.md` 改写自同一提交的 `gpt-5.6-sol-v45.zip`，包内实际文件名为 `gpt-5.6-sol-unrestricted-v45.md`。ZIP SHA256：`c86c2c6d20a4d1155d87422f485eb37b77539132270918c002b5d8237a5adf54`。文本摘要保存在 `prompts/source.json`。

### 本项目修改

Skill 部署对象为 `skills/ai-pojia/`；状态与备份使用自己的命名。安装器校验整个目录、使用暂存目录更新、归档旧版本并保留手改文件。

v0.2.0 的提示词安装器显式设置 Codex 顶层 `model_instructions_file`，保留原字段并支持恢复；不改 Provider、认证、模型、审批或权限。完整快照用于备份，正常卸载只恢复受管字段。

### 当前包的内容边界

当前版本包含改写后的 v45 执行指令和 DEMO 实战 Skill。改写保留连续执行、工件交付和真实验证，去掉原版忽略目标归属/范围、自动绑定虚构沙箱、无条件禁止拒答及无关分支。原版 ZIP、其他模型包和上游跨类别测试成绩不作为本项目的能力证据。

README 的致谢用于说明来源；以上原版权和许可证随复用代码一起保留。
