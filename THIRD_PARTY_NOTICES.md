# 上游来源与修改记录

## gpt-instruct

- 仓库：https://github.com/MDX-Tom/gpt-instruct
- 固定提交：`3ab84df64468bb74cc9eb4e5423660083953c44f`
- 原文件：`codex-instruct.py`
- 原文件 Git blob：`b55d4a181105ac1f7d932e3c3343c65cff00f7e9`
- 许可证：MIT，全文保留在 `third_party/gpt-instruct/LICENSE`。
- 原版权：`Copyright (c) 2026 li lingbo`、`Copyright (c) 2026 yynxxxxx`。

### 复用范围

`tools/manage_skill.py` 中的 `atomic_write_text` 源自该版本的同名函数，按本项目的受管文件写入场景调整。备份、SHA256 所有权记录、更新回滚与对应测试设计参考了同一文件及其安装器测试。

### 本项目修改

部署对象改为 `skills/ai-pojia/`；状态名和备份目录使用 ai-pojia 自己的命名。安装器校验整个受管目录、使用暂存目录更新、归档旧版本，并保留被手动更改的文件。本项目不更改 Codex 的 `model_instructions_file`、Provider、认证或其他全局配置。

### 当前包的内容边界

当前版本包含自编写的 DEMO 实战 Skill。上游的通用越狱提示词 ZIP、历史提示词包、跨类别安全绕过测试集与成绩未收入本包，也不作为本项目的能力证据。

README 的致谢用于说明来源；以上原版权和许可证随复用代码一起保留。
