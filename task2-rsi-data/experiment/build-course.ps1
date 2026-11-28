param([switch] $Offline)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot '../spring-boot/build-course.ps1') -Canvas -Offline:$Offline
