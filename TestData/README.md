# TestData 说明

- 来源：本地运行中的 API `http://127.0.0.1:8120`，采集时间：$(Get-Date -Format "yyyy-MM-dd HH:mm:ss K").
- 请求列表：
  - `health.json`：GET /health
  - `steels.json`：GET /api/steels?limit=5
  - `defects_seq12.json`：GET /api/defects/12
  - `meta.json`：GET /api/meta
  - `steel_meta_seq12.json`：GET /api/steel-meta/12
- 采集方式：PowerShell `Invoke-RestMethod`，随后使用 `ConvertTo-Json -Depth 10` 输出为 UTF-8。
- 注意：以上数据反映采集时刻的服务和数据库状态，若数据更新请重新运行下方命令。

## 复现命令（PowerShell）
```powershell
$base = "http://127.0.0.1:8120"
New-Item -ItemType Directory -Force "TestData" | Out-Null
Invoke-RestMethod "$base/health" | ConvertTo-Json -Depth 10 | Out-File -FilePath "TestData/health.json" -Encoding utf8
Invoke-RestMethod "$base/api/steels?limit=5" | ConvertTo-Json -Depth 10 | Out-File -FilePath "TestData/steels.json" -Encoding utf8
Invoke-RestMethod "$base/api/defects/12" | ConvertTo-Json -Depth 10 | Out-File -FilePath "TestData/defects_seq12.json" -Encoding utf8
Invoke-RestMethod "$base/api/meta" | ConvertTo-Json -Depth 10 | Out-File -FilePath "TestData/meta.json" -Encoding utf8
Invoke-RestMethod "$base/api/steel-meta/12" | ConvertTo-Json -Depth 10 | Out-File -FilePath "TestData/steel_meta_seq12.json" -Encoding utf8
```
