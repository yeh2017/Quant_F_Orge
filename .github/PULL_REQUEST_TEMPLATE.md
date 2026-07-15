# Pull Request

## 修改内容

请简要说明本次 PR 修改了什么。

## 修改原因

请说明为什么需要这个修改，解决了什么问题或增加了什么能力。

## 影响范围

请列出主要影响的模块或文件：

- 后端：
- 前端：
- 文档：
- 启动脚本：

## 测试情况

请填写实际运行过的测试命令和结果。

```bash
# 前端测试
cd frontend
npm test
```

```powershell
# 后端测试
cd backend
$tests = Get-ChildItem tests -Filter "test_*.py" | ForEach-Object { $_.FullName }
.venv\Scripts\python.exe -m pytest $tests
```

如果没有运行测试，请说明原因。

## 检查项

- [ ] 没有提交 `backend/.env`、数据库、虚拟环境、依赖目录或日志文件。
- [ ] README、配置说明和启动脚本说明与实际代码一致。
- [ ] 修改范围清楚，没有混入无关改动。
- [ ] 如涉及数据源、推送或外部 API，已说明需要的配置。
