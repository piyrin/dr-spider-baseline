$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$config = Join-Path $root '.local/task2-rsi-data/spring-boot'
$starter = Join-Path $config 'backend/core-starter/src/main/java/com/horsecoder/common/whuTalent/core/flow'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'spring/CanvasExperimentController.java'), (Join-Path $PSScriptRoot 'spring/CanvasExperimentNode.java') -Destination $starter
$flowEntry = Join-Path $config 'backend/core-flow/src/main/java/com/horsecoder/common/whuTalent/core/flow/Run/code/FlowCodeRun.java'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'spring/FlowCodeRun.java') -Destination $flowEntry
$caseResources = Join-Path $config 'backend/core-starter/src/main/resources/task2-cases'
$null = New-Item -ItemType Directory -Force -Path $caseResources
Copy-Item -Path (Join-Path $root 'results/task2/submission/acceptance/backend/case*.json') -Destination $caseResources
& (Join-Path $root 'task2-rsi-data/spring-boot/build-course.ps1') -Offline
