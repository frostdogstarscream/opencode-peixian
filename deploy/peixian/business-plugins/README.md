# 沛县公安业务插件

本目录包含 5 个按数据域拆分的 PR7C V1 业务插件。插件只调用连接别名 `peixian_data`，不包含上游服务地址或凭据。

## 校验和测试

```powershell
python deploy\peixian\business-plugins\validate.py
$tests = Get-ChildItem deploy\peixian\business-plugins -Filter '*.test.mjs' -Recurse | Select-Object -ExpandProperty FullName
node --test $tests
```

## 打包

```powershell
python deploy\peixian\business-plugins\package.py
```

脚本拒绝覆盖已有 ZIP。修改代码、清单或配置表单后应先提升 `manifest.json` 和 `entry.mjs` 中的版本号，再重新打包。

在插件 ZIP 已生成后，可汇总完整、无凭据的服务器交付目录：

```powershell
python deploy\peixian\business-plugins\build_release.py --version 1.0.0
```

输出位于 `deploy/peixian/dist/release/peixian-data-plugins-1.0.0`，包含插件、5 个业务 Skill、OpenAPI、字段映射、连接要求、导入说明、测试报告、发布说明和全量 SHA-256 清单。脚本拒绝覆盖已有发布目录。

适配服务和部署说明分别见 `services/peixian-data-adapter` 与 `TEST_SERVER_IMPORT.md`。
