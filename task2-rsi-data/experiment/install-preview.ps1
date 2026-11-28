$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$platform = Join-Path $root '.local/platform-preview/rsi-data-platform'
$route = Join-Path $platform 'app/task2-experiment'
$null = New-Item -ItemType Directory -Force -Path $route
$shared = @('QueryResult.tsx', 'query-result.module.css', 'case-options.ts') | ForEach-Object { Join-Path $PSScriptRoot "web/$_" }
Copy-Item -LiteralPath (@((Join-Path $PSScriptRoot 'web/page.tsx'), (Join-Path $PSScriptRoot 'web/workbench.module.css')) + $shared) -Destination $route
$caseDir = Join-Path $platform 'public/task2-cases'
$null = New-Item -ItemType Directory -Force -Path $caseDir
Copy-Item -Path (Join-Path $root 'results/task2/submission/acceptance/frontend/case*.json') -Destination $caseDir
$loginDir = Join-Path $platform 'src/xpages/Login'
Copy-Item -LiteralPath (@((Join-Path $PSScriptRoot 'web/CourseCases.tsx'), (Join-Path $PSScriptRoot 'web/course-cases.module.css')) + $shared) -Destination $loginDir
$loginPath = Join-Path $loginDir 'index.tsx'
$login = Get-Content -LiteralPath $loginPath -Raw -Encoding UTF8
if (!$login.Contains("import CourseCases from './CourseCases';")) {
    $anchor = 'export default LoginPage;'
    if (!$login.Contains($anchor)) { throw 'Unable to locate the course canvas page export' }
    if (!$login.Contains('useSearchParams')) {
        $login = "import { useSearchParams } from 'next/navigation';`n$login"
    }
    $entry = @'
function CourseCanvasEntry(props: LoginProps) {
  const caseId = useSearchParams().get('case');
  return caseId && /^case(?:[1-9]|10)$/.test(caseId)
    ? <CourseCases key={caseId} initialCase={caseId} />
    : <LoginPage {...props} />;
}

export default CourseCanvasEntry;
'@
    $login = "import CourseCases from './CourseCases';`n" + $login.Replace($anchor, $entry)
    [IO.File]::WriteAllText($loginPath, $login, [Text.UTF8Encoding]::new($false))
}
$configPath = Join-Path $platform 'next.config.ts'
$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8
$originalConfig = $config
if ($config -notmatch '\bproxyTimeout\s*:') {
    $experimental = [regex]'(?m)^([ \t]*experimental\s*:\s*\{)'
    if ($experimental.IsMatch($config)) {
        $config = $experimental.Replace($config, '$1 proxyTimeout: 600000,', 1)
    } else {
        $declaration = [regex]'(?m)^(const nextConfig: NextConfig = \{)'
        if (!$declaration.IsMatch($config)) { throw 'Missing Next.js config declaration' }
        $config = $declaration.Replace($config, "`$1`n  experimental: { proxyTimeout: 600000 },", 1)
    }
}
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
}
if ($config -ne $originalConfig) {
    [IO.File]::WriteAllText($configPath, $config, [Text.UTF8Encoding]::new($false))
}
