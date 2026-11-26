$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$platform = Join-Path $project '.local/platform-preview/rsi-data-platform'
$configPath = Join-Path $platform 'next.config.ts'

$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8
$originalConfig = $config
$rewriteList = [regex]'(?m)^    return \[(?=\r?$)'
$routes = @(
    @{ Source = '/api/engine/flow'; Destination = 'http://127.0.0.1:3211/api/engine/flow' },
    @{ Source = '/api/task2/course-flow'; Destination = 'http://127.0.0.1:30845/api/engine/flow' }
)
$missingRoutes = @($routes | Where-Object { !$config.Contains(('source: "{0}"' -f $_.Source)) })
if ($missingRoutes.Count -and $rewriteList.Matches($config).Count -ne 1) {
    throw 'Next.js config does not have the expected development rewrite list.'
}
$route = Join-Path $platform 'app/task2'
$null = New-Item -ItemType Directory -Force -Path $route
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'web/page.tsx'), (Join-Path $PSScriptRoot 'web/task2.module.css') -Destination $route
if ($missingRoutes.Count) {
    $rewrite = '    return ['
    foreach ($proxy in $missingRoutes) {
        $rewrite += "`n      {`n        source: `"$($proxy.Source)`",`n        destination: `"$($proxy.Destination)`",`n      },"
    }
    $config = $rewriteList.Replace($config, $rewrite, 1)
}

# The course request can wait on three successive Agent nodes, each with a 190-second read timeout.
$proxyTimeout = [regex]'(?m)(\bproxyTimeout[ \t]*:[ \t]*)\d+'
$experimental = [regex]'(?m)^([ \t]*)experimental[ \t]*:[ \t]*\{'
if ($proxyTimeout.IsMatch($config)) {
    $config = $proxyTimeout.Replace($config, '${1}600000', 1)
} elseif ($experimental.IsMatch($config)) {
    $config = $experimental.Replace($config, '${0}' + "`n" + '${1}  proxyTimeout: 600000,', 1)
} else {
    $nextConfig = [regex]'(?m)^const nextConfig: NextConfig = \{'
    $config = $nextConfig.Replace($config, '${0}' + "`n  experimental: { proxyTimeout: 600000 },", 1)
}
if ($config -cne $originalConfig) {
    $config | Set-Content -LiteralPath $configPath -Encoding utf8NoBOM -NoNewline
}
