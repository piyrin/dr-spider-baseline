param([switch] $Offline)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).ProviderPath
$config = Join-Path $root '.local/task2-rsi-data/spring-boot'
$backend = Join-Path $config 'backend'
if (!(Test-Path -LiteralPath $backend)) {
    Copy-Item -LiteralPath (Join-Path $root '.local/upstream/snapshots/rsi-data-spring-boot') -Destination $backend -Recurse
}

$starter = Join-Path $backend 'core-starter/src/main'
$nodes = Join-Path $starter 'java/com/horsecoder/common/whuTalent/core/flow'
$flows = Join-Path $starter 'resources/flow/task2'
$null = New-Item -ItemType Directory -Path $nodes, $flows -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Task2AgentNodes.java') -Destination $nodes
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'flow-task2-single.json'), (Join-Path $PSScriptRoot 'flow-task2-multi.json') -Destination $flows

$env:JAVA_HOME = Join-Path $config 'runtime/corretto8/jdk1.8.0_514'
$maven = Join-Path $config 'runtime/apache-maven-3.9.16/bin/mvn.cmd'
$repo = Join-Path $config 'maven-repository'
$arguments = @('-B', '-ntp', '-s', (Join-Path $config 'settings.xml'), '-f', (Join-Path $backend 'pom.xml'),
               '-pl', 'core-starter', '-am', "-Dmaven.repo.local=$repo", '-DskipTests', 'package')
if ($Offline) { $arguments = @('-o') + $arguments }
& $maven @arguments
if ($LASTEXITCODE -ne 0) { throw "Course backend build failed (exit $LASTEXITCODE)" }
