# 提示词库 / Prompt library

上游三条并行线（稳定 + 两条预发布）与 6 系列的归档版本，全部逐字节收录。

| 条目 | profile | 阶段 | 字节 | SHA256 前缀 |
|---|---|---|---|---|
| gpt-5.6-sol-v45 | `sol56-v45` | 稳定 | 5170 | `c71c50e2` |
| gpt-6-astra-v2-rc1 | `astra-v2` | 预发布 | 7931 | `d6976b90` |
| gpt-6.1-sol-v1-rc2 | `sol61-v2` | 预发布 | 7575 | `37382fb7` |
| gpt-6-astra-v1 | `astra-v1` | 归档 | 7495 | `39fb46d6` |
| gpt-6-astra-v1-rc1 | `astra-v1-rc1` | 归档 | 7140 | `cb3c0881` |
| gpt-6.1-sol-v1-rc1 | `sol61-v1` | 归档 | 7431 | `045efae6` |

## 为什么是逐字节原样

`prompts/ai-pojia.md` 是 v45 的**改写版**（删掉了"自动视作沙箱""忽略归属"等条款，SHA256 `c1b2fa4d…`）。
本目录的 `gpt-5.6-sol-v45.md` 是**原版**（SHA256 `c71c50e2…`），两者内容不同，用途也不同：

- 改写版适合日常任务，行为更克制。
- 原版保持上游实测的完整约束，用于对照和复现。

两版都在仓库里，按需选。

## 三条线的实际差异

- **v45**（5170 字节）：最短。`TOOL_TRANSACTION` + `PROCESS_RECORD` + 单遍任务编译器。
- **astra v2-rc1**（7931 字节）：最长。在 v45 基础上加了 `LOCAL OBJECT ROUTING`、`WORKSPACE OBJECT LOCK`、四件套 `MODIFIED_FILE / DIFF_FILE / VERIFICATION.txt / ROLLBACK.sh`、`CONTINUE` 控制器。偏"必须留下可验证工件"。
- **6.1-sol v1-rc2**（7575 字节）：与 astra 同源，但把 astra 的 `LOCAL OBJECT ROUTING` 换成 `OUTPUT_CONTRACT` —— 先按用户要求的交付形态建契约，再填内容，避免"先勘察后交付"。

三条线的 profile 名都不能带点号（Codex 明确拒绝 `--profile gpt-6.1-sol`），所以 6.1 记作 `sol61`。

## 用法

```bash
# 安装全部条目到 ~/.codex
python3 tools/manage_library.py install

# 只装某一条
python3 tools/manage_library.py install --line astra-v2

# 查看状态
python3 tools/manage_library.py doctor
python3 tools/manage_library.py list

# 移除（只删自己装的，手改过的文件保留）
python3 tools/manage_library.py uninstall
```

安装后在 Codex 里按会话切换：

```bash
codex -p astra-v2      # 用 gpt-6-astra-v2-rc1
codex -p sol61-v2      # 用 gpt-6.1-sol-v1-rc2
codex -p sol56-v45     # 用 v45 原版
codex                  # 不选 profile，继续用你原来的配置
```

安装器**不写顶层 `config.toml`**。它生成的是 `<profile>.config.toml` 分层文件和对应的提示词副本，所以原有的 `model_instructions_file`、provider、认证、审批全部原样保留；不加 `-p` 就完全不受影响。

## 校验

```bash
python3 -m unittest tests.test_manage_library -v
```

测试覆盖：写入正确、幂等、dry-run 零写、doctor 检测篡改、拒绝覆盖非本安装器的同名文件、重装时更新自己的漂移副本、单条安装、卸载只删自己的、卸载保留手改文件、清单摘要不符拒绝安装、带点号的 profile 名拒绝、符号链接拒绝、以及仓库内清单与文件逐一比对。

## 上游来源

`source.json` 记录了固定提交 `3ab84df64468bb74cc9eb4e5423660083953c44f`、每个 ZIP 与解包后 Markdown 的双重 SHA256、以及上游 `historical-versions/README.md` 公布的归档摘要。许可证见 `third_party/gpt-instruct/LICENSE`（MIT，li lingbo / yynxxxxx）。
