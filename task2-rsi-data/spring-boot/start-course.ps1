$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).ProviderPath
$config = Join-Path $root '.local/task2-rsi-data/spring-boot'
$java = Join-Path $config 'runtime/corretto8/jdk1.8.0_514/bin/java.exe'
$jar = Join-Path $config 'backend/core-starter/target/core-starter-1.0.0-executable.jar'
$resources = Join-Path $config 'backend/core-starter/target/classes'
$h2 = Join-Path $config 'runtime/h2-1.4.199.jar'
$temp = Join-Path $config 'runtime/tmp'
$null = New-Item -ItemType Directory -Path $temp -Force
$environment = ([Uri](Join-Path $PSScriptRoot 'application-task2.yaml')).AbsoluteUri
& $java "-Dloader.path=$resources,$h2" "-Djava.io.tmpdir=$temp" '-Dfile.encoding=UTF-8' -cp $jar `
    org.springframework.boot.loader.PropertiesLauncher '--spring.profiles.active=dev' `
    "--spring.config.location=$environment"
exit $LASTEXITCODE
