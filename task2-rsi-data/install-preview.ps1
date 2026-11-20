$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$platform = Join-Path $project '.local/platform-preview/rsi-data-platform'
$configPath = Join-Path $platform 'next.config.ts'
$homePath = Join-Path $platform 'app/page.tsx'

$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8
$homeSource = Get-Content -LiteralPath $homePath -Raw -Encoding UTF8
$rewriteList = [regex]'(?m)^    return \[(?=\r?$)'
$routes = @(
    @{ Source = '/api/engine/flow'; Destination = 'http://127.0.0.1:3211/api/engine/flow' },
    @{ Source = '/api/task2/course-flow'; Destination = 'http://127.0.0.1:30845/api/engine/flow' }
)
$entry = '<a href="/task2" style={{ position: "fixed", zIndex: 100, top: 16, right: 20, padding: "8px 12px", background: "#215840", color: "white", borderRadius: 4 }}>数据 Agent 编排</a>'
$missingRoutes = @($routes | Where-Object { !$config.Contains(('source: "{0}"' -f $_.Source)) })
if ($missingRoutes.Count -and $rewriteList.Matches($config).Count -ne 1) {
    throw 'Next.js config does not have the expected development rewrite list.'
}
if (!$homeSource.Contains('href="/task2"') -and !$homeSource.Contains('<LoginWrapper />')) {
    throw 'Next.js homepage does not have the expected canvas wrapper.'
}

$route = Join-Path $platform 'app/task2'
$null = New-Item -ItemType Directory -Force -Path $route
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'web/page.tsx'), (Join-Path $PSScriptRoot 'web/task2.module.css') -Destination $route
if ($missingRoutes.Count) {
    $rewrite = '    return ['
    foreach ($proxy in $missingRoutes) {
        $rewrite += "`n      {`n        source: `"$($proxy.Source)`",`n        destination: `"$($proxy.Destination)`",`n      },"
    }
    $rewriteList.Replace($config, $rewrite, 1) | Set-Content -LiteralPath $configPath -Encoding utf8NoBOM -NoNewline
}
if (!$homeSource.Contains('href="/task2"')) {
    $homeSource.Replace('<LoginWrapper />', "$entry`n      <LoginWrapper />") | Set-Content -LiteralPath $homePath -Encoding utf8NoBOM -NoNewline
}
