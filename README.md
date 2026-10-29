# AI破甲 · ai-pojia

左手的执行提示词配置与 DEMO 实战 Skill。安装一次，加载内置提示词、安装 Skill，并提供检查与恢复入口。

**v0.2.0：已加入改写自 gpt-instruct v45 的提示词及真实加载机制。** 目标是让 AI 在明确授权的任务里持续完成工作，交付可核对的产物。尚无通用取消拒答、全模型兼容或正式 DEMO 通关的实测结论。

**v0.3.0：内置完整提示词库。** 上游三条并行线逐字节收录（v45 稳定版、gpt-6-astra-v2-rc1、gpt-6.1-sol-v1-rc2），外加 6 系列归档版；通过 Codex 的 `--profile` 分层机制按会话切换，不覆盖顶层配置。见 [提示词库](prompts/library/README.md)。

## 三套提示词，三条加载路径

| 你想要的 | 用什么 | 作用范围 |
|---|---|---|
| 一份克制的日常执行指令 | `python3 install.py` → 改写版 [ai-pojia.md](prompts/ai-pojia.md) | 顶层 `model_instructions_file`，全局 |
| 上游原版，按会话挑版本 | `python3 tools/manage_library.py install` → `codex -p astra-v2` | 分层 profile，单次会话 |
| 逆向/DEMO 实战工作流 | 随 `install.py` 一起装的 [ai-pojia Skill](skills/ai-pojia/SKILL.md) | 用 `$ai-pojia` 显式调用 |

前两条都是"自动加载"（不需要在对话里点名），第三条是显式调用的 Skill。三者互不冲突，可以同时装。

## 最简单的安装方式

把下面整段发给正在使用的 **Codex**：

> 请从 https://github.com/zgx949/ai-pojia 安装 AI破甲的提示词配置和 Skill。先阅读 README，检查环境，然后运行 `python3 install.py`，最后用 `python3 install.py --doctor` 确认配置。保留现有模型、Provider 和认证设置。

也可以手动安装：

```bash
git clone https://github.com/zgx949/ai-pojia.git
cd ai-pojia
python3 install.py
```

安装后重新加载客户端或开始新会话。环境要求：支持 `model_instructions_file` 与本地 Skills 的 Codex、Python 3.9 或以上；Windows 可用 `py -3` 替代 `python3`。实际验证范围见 [验证记录](docs/validation.md)。

## 装完发生什么

- 内置 [提示词](prompts/ai-pojia.md) 复制到 Codex 目录，通过顶层 `model_instructions_file` 加载。
- [ai-pojia Skill](skills/ai-pojia/SKILL.md) 安装到同一 Codex 目录的 `skills/ai-pojia/`。
- 提供来源、摘要、备份、配置恢复和安装检查。

`model_instructions_file` 替换 Codex 的内置工作指令，作用于采用这份配置的新会话。普通插件/Skill 安装不会自动启用它。[官方配置说明](https://learn.chatgpt.com/docs/config-file/config-reference)

安装器管理自己的提示词、安装状态、备份、Skill 目录和顶层指令字段；模型、Provider、认证、工具审批和权限字段保持原值。默认 Codex 目录为 `CODEX_HOME`，未设置时为 `~/.codex`；可用 `--codex-dir` 指定其他目录。

## 使用

普通任务会采用加载的执行指令。进行自写测试 DEMO 实战时，把文件放入独立目录并发送：

> 用 $ai-pojia 分析这个我自己编写的测试 DEMO。先说明它如何工作，再在副本上完成指定修改，实际运行验证，并保留原文件和修改记录。

Skill 交付原始摘要、分析证据、修改副本、差异、验证命令及实际结果。左手的正式测试 DEMO 后续补充，当前 [demos/](demos/) 没有测试程序或预置答案。

## 检查、预览和恢复

```bash
python3 install.py --doctor
python3 install.py --dry-run
python3 install.py --uninstall

# 为指定客户端目录安装
python3 install.py --codex-dir /absolute/path/to/codex
```

预览不写文件。卸载恢复安装前的顶层指令字段，并归档自己的 Skill；安装后对 Provider 等其他字段的修改会保留。遇到手改文件或配置冲突，工具停止对应操作并报告真实状态。

高级用户可分别运行 `tools/manage_prompt.py`、`tools/manage_skill.py`、`tools/manage_library.py`，均支持安装、卸载、只读检查、指定目录及 JSON 输出。安装器仅使用 Python 标准库，实际任务使用客户端已有模型和工具。

## 提示词库（v0.3.0）

上游 `MDX-Tom/gpt-instruct` 有三条并行产品线，本仓库逐字节收录：

```bash
python3 tools/manage_library.py list      # 看有哪些
python3 tools/manage_library.py install   # 装到 ~/.codex
```

| 条目 | profile | 阶段 |
|---|---|---|
| gpt-5.6-sol-v45 | `sol56-v45` | 稳定 |
| gpt-6-astra-v2-rc1 | `astra-v2` | 预发布 |
| gpt-6.1-sol-v1-rc2 | `sol61-v2` | 预发布 |
| gpt-6-astra-v1 / v1-rc1 | `astra-v1` / `astra-v1-rc1` | 归档 |
| gpt-6.1-sol-v1-rc1 | `sol61-v1` | 归档 |

装完后按会话切换：

```bash
codex -p astra-v2     # GPT-6-Astra v2-rc1
codex -p sol61-v2     # GPT-6.1-Sol v1-rc2
codex                 # 不加 -p，沿用你原本的顶层配置
```

这套走的是 Codex 官方的 profile 分层（`$CODEX_HOME/<name>.config.toml`），**不写顶层 `config.toml`**，所以原来的 `model_instructions_file`、provider、认证、审批一个都不动。细节见 [提示词库说明](prompts/library/README.md)。

## 上游与修改

来源为 [MDX-Tom/gpt-instruct](https://github.com/MDX-Tom/gpt-instruct) 固定提交 `3ab84df`，MIT。保留 li lingbo、yynxxxxx 的原版权与 [MIT 全文](third_party/gpt-instruct/LICENSE)。

本版本改写实际 v45 提示词，保留连续执行、工件交付、基线对照和恢复验证，去掉将所有真实目标自动视作沙箱、忽略归属/范围、无条件禁止拒答及无关分支。详见 [提示词说明](prompts/README.md)和 [来源摘要](prompts/source.json)。

加载成功只说明配置已指向并校验内置指令，不证明模型一定接受某个请求；客户端、模型和服务端规则仍影响实际结果。模型前后对照、DEMO 结果与失败记录在实测后补充。

感谢上游作者及维护者。复用代码和修改记录见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 开发与打包

```bash
python3 -m unittest discover -s tests -v
python3 tools/package_release.py
```

[plugin.json](plugin.json) 提供插件打包入口，尚未上架公共目录；它安装 Skill，不自动修改全局指令。当前完整一键入口是 `install.py`。

原创内容使用 MIT。验证范围见 [docs/validation.md](docs/validation.md)。
