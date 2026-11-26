$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$platform = Join-Path $root '.local/platform-preview/rsi-data-platform'
$route = Join-Path $platform 'app/task2-experiment'
$null = New-Item -ItemType Directory -Force -Path $route
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'web/page.tsx'), (Join-Path $PSScriptRoot 'web/workbench.module.css') -Destination $route
$configPath = Join-Path $platform 'next.config.ts'
$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8
if (!$config.Contains('/api/task2-experiment/catalog')) {
    $new = @'
    return [
      {
        source: "/api/task2-experiment/catalog",
        destination: "http://127.0.0.1:3213/catalog",
      },
      {
        source: "/api/task2-experiment/run",
        destination: "http://127.0.0.1:30845/api/task2-experiment/run",
      },
'@
    $rewrites = [regex]'(?m)^    return \[(?=\r?$)'
    if ($rewrites.Matches($config).Count -ne 1) { throw 'Missing Next.js development rewrite list' }
    $config = $rewrites.Replace($config, $new, 1)
    [IO.File]::WriteAllText($configPath, $config, [Text.UTF8Encoding]::new($false))
}
