param([switch] $Offline, [switch] $Canvas)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).ProviderPath
$config = Join-Path $root '.local/task2-rsi-data/spring-boot'
$backend = Join-Path $config 'backend'
if (!(Test-Path -LiteralPath $backend)) {
    $source = Join-Path $root '.local/upstream/snapshots/rsi-data-spring-boot'
    if (!(Test-Path -LiteralPath (Join-Path $source 'pom.xml'))) { throw "Place the course backend source in $source" }
    $null = New-Item -ItemType Directory -Force -Path $config
    Copy-Item -LiteralPath $source -Destination $backend -Recurse
}

$starter = Join-Path $backend 'core-starter/src/main'
$nodes = Join-Path $starter 'java/com/horsecoder/common/whuTalent/core/flow'
$flows = Join-Path $starter 'resources/flow/task2'
$null = New-Item -ItemType Directory -Path $nodes, $flows -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Task2AgentNodes.java') -Destination $nodes
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'flow-task2-single.json'), (Join-Path $PSScriptRoot 'flow-task2-multi.json') -Destination $flows

if ($Canvas) {
    $experiment = Join-Path $root 'task2-rsi-data/experiment/spring'
    Copy-Item -LiteralPath (Join-Path $experiment 'CanvasExperimentController.java'), (Join-Path $experiment 'CanvasExperimentNode.java') -Destination $nodes
    $entry = Join-Path $backend 'core-flow/src/main/java/com/horsecoder/common/whuTalent/core/flow/Run/code/FlowCodeRun.java'
    Copy-Item -LiteralPath (Join-Path $experiment 'FlowCodeRun.java') -Destination $entry
    $resources = Join-Path $starter 'resources/task2-cases'
    $null = New-Item -ItemType Directory -Force -Path $resources
    Copy-Item -Path (Join-Path $root 'results/task2/submission/acceptance/backend/case*.json') -Destination $resources
}

$env:JAVA_HOME = Join-Path $config 'runtime/corretto8/jdk1.8.0_514'
$maven = Join-Path $config 'runtime/apache-maven-3.9.16/bin/mvn.cmd'
$repo = Join-Path $config 'maven-repository'
$settings = Join-Path $config 'settings.xml'
foreach ($file in @($settings, $maven, (Join-Path $env:JAVA_HOME 'bin/java.exe'))) {
    if (!(Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing course build prerequisite: $file" }
}
$arguments = @('-B', '-ntp', '-s', $settings, '-f', (Join-Path $backend 'pom.xml'),
               '-pl', 'core-starter', '-am', "-Dmaven.repo.local=$repo", '-DskipTests', 'package')
if ($Offline) { $arguments = @('-o') + $arguments }
& $maven @arguments
if ($LASTEXITCODE -ne 0) { throw "Course backend build failed (exit $LASTEXITCODE)" }
