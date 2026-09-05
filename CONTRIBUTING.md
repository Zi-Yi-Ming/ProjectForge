# Contributing

感谢你对 ProjectForge 感兴趣。以下是参与本项目的最小指引。

## 开发环境

```bash
git clone https://github.com/Zi-Yi-Ming/ProjectForge.git
cd ProjectForge
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 运行测试

```bash
python -m compileall app
pytest
```

## 代码风格

- 保持现有模块结构，不要引入新的顶层目录。
- 修改业务代码时，同步检查 `README.md` 是否仍与真实行为一致。
- 不要为了测试通过而修改既有生命周期语义。

## 提交建议

- 建议按独立问题拆分提交：
  - Product Core 修复
  - Workspace isolation
  - CLI/API wiring
  - 文档/开源卫生
- commit message 请使用祈使句、英文、简明。

## 注意

- 本项目当前不维护 `pip install projectforge` 安装路径，先以仓库 clone 方式验证。
- Hermes / bwrap 相关改动请单独标注，便于后续做 runtime verification。
