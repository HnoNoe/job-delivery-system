# 求职批量投递系统（精简版）

依据专利技术交底书《一种主要面向大学毕业生的求职批量投递系统及方法》实现。
本版为**最小核心系统**：只保留「登录 → 检索岗位 → 建任务 → 投递」四步，
画像/匹配/公式/网页端/桌面端已全部移除（见 git 历史）。

## 快速开始

```bash
python setup_env.py          # 首次：建虚拟环境装依赖（可选）

# 1. 登录（在用户自己的日常浏览器里手动登录平台，然后把登录态读出来存盘）
python main.py login boss        # 打开你的默认浏览器去登录
python main.py grab boss         # 从本机 cookie 库读取登录态存盘（Edge 需管理员运行）

# 2. 检索岗位（高强度字段校验 + 去重入库）
python main.py search boss 后端 --pages 3
python mock_site.py              # 本地 mock 站（5001 端口）可代替真实平台演练

# 3. 建投递任务（在架岗位 → delivery_tasks，自动去重）
python main.py maketasks

# 4. 投递
python main.py status            # 登录态 + 岗位/任务概况
python main.py deliver           # 批量投递待投递任务
python main.py deliver --limit 5
```

## ⚠️ 安全模式

`config.SAFE_MODE = True`（默认）时投递**只提示不真发**；改为 `False` 才会真实投递，
封号风险自负。批量投递受每日上限/单批上限/间隔限速三重保护，检测到风控信号立即停止。

## 统一字段数据库

- 字段名全局唯一、字段值可核对（白名单/别名映射/格式校验），schema 见 `schema.py`。
- 完整字段表与生成规则：`docs/统一字段数据库-完整字段表.xlsx`（10 个 sheet）。
- 高强度回归：`python verify_db_strict.py`。

## 结构

| 模块 | 职责 |
|---|---|
| `main.py` | CLI 入口（login/grab/search/maketasks/deliver/status） |
| `crawler.py` + `loop.py` | 登录态检索岗位 |
| `jobstore.py` | 字段校验 + 去重入库 + 上下架 |
| `delivery.py` + `form_filler.py` + `greeting.py` | 批量投递（三重护栏 + 个性化招呼语） |
| `session.py` / `grab_login.py` / `login_status.py` | 登录态管理（用户自助登录，不对抗平台反爬） |
| `db.py` / `schema.py` | 统一字段数据库（本地 SQLite，兼容云端 MySQL） |
| `mock_site.py` | 本地高保真测试站 |
