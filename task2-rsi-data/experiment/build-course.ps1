$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$config = Join-Path $root '.local/task2-rsi-data/spring-boot'
$starter = Join-Path $config 'backend/core-starter/src/main/java/com/horsecoder/common/whuTalent/core/flow'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'spring/CanvasExperimentController.java'), (Join-Path $PSScriptRoot 'spring/CanvasExperimentNode.java') -Destination $starter
& (Join-Path $root 'task2-rsi-data/spring-boot/build-course.ps1') -Offline
