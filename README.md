# apiping

一句话检查任何 OpenAI-compatible 端点健不健康：地址进，健康卡出。

```bash
python -m apiping https://api.openai.com/v1
```

```
===== 端点健康检查 =====
地址：https://api.openai.com/v1
连通：✅ 可达
模型列表：✅ 40 个模型（gpt-4o-mini、gpt-4o、o3-mini…）
对话接口：✅ 正常（模型 gpt-4o-mini，延迟 812 ms）
结论：✅ 健康
```

## 为什么是双探针

只看 `GET /models` 返回 200 就宣布"服务正常"是自欺欺人——很多网关的模型列表是静态配置，
chat 链路挂了它照样 200。所以 apiping 永远再打一个真正的 `/chat/completions`
（`ping` + `max_tokens=1`，花不了几个 token），**只有 chat 通了才算健康**。

## 安装

零依赖，Python 3.10+，标准库 only：

```bash
git clone https://github.com/ljiang9/apiping.git
cd apiping
python -m apiping --help
```

## 用法

```bash
# 基本检查（key 可选）
python -m apiping https://api.openai.com/v1
python -m apiping http://localhost:11434/v1          # Ollama
python -m apiping http://localhost:8000/v1 --model qwen2.5  # 指定 ping 模型

# key 从环境变量读（只在 Authorization 头里发送，从不打印）
export OPENAI_API_KEY=sk-...
python -m apiping https://api.openai.com/v1

# 机器可读
python -m apiping http://localhost:11434/v1 --json

# 盯着它（每 60 秒一行，Ctrl-C 停）
python -m apiping https://api.openai.com/v1 --watch 60
```

401 的处理是诚实的：没给 key 就报"需要 key，不是服务故障"，
给了 key 还 401 就报"key 无效"——不会把鉴权问题伪装成服务宕机。

退出码：`0` 健康，`1` 不健康，`2` 用法错误。

## 诚实说明（局限）

- 延迟是**单次采样**，网络抖动一次就能让数字失真；要看趋势请用 `--watch` 多采几轮。
- `/models` 返回的模型列表在某些网关是静态配置的，实际能不能调用以 chat 探针为准。
- ping 只发 1 个 token，能证明链路通，证明不了长输出/流式/tool calling 正常。
- `--watch` 只是轮询打印，不是告警系统；真要告警请接你的监控。
- 超时默认 15 秒，`--timeout` 可调。

## License

MIT，Copyright (c) 2026 ljiang9
