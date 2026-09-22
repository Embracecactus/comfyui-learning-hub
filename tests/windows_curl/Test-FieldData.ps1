#requires -Version 5.1
# Synthetic tests based on the official apiCallDemo example, not a live account.
# https://www.runninghub.cn/runninghub-api-doc-cn/api-425749011
$ErrorActionPreference='Stop'
$script:EnumPassed=0
$Client=Join-Path $PSScriptRoot 'rh-curl.ps1'
$OldClient=Join-Path $PSScriptRoot 'rh-curl-v1.1-original.ps1'
function Check-Enum([bool]$Condition,[string]$Name) {
    if (-not $Condition) { throw "FAIL: $Name" }
    $script:EnumPassed++;Write-Host "PASS: $Name"
}
function Throws-Enum([scriptblock]$Code,[string]$Pattern,[string]$Name) {
    $caught=$false
    try { & $Code | Out-Null } catch {
        if ($_.Exception.Message -notmatch $Pattern) { throw "FAIL: $Name unexpected: $($_.Exception.Message)" }
        $caught=$true
    }
    Check-Enum $caught $Name
}
$Rows=@'
[
 {"nodeId":"1","fieldName":"prompt","fieldType":"STRING","fieldValue":"应用默认长提示词","fieldData":"[\"STRING\", {\"default\":\"\",\"multiline\":true}]"},
 {"nodeId":"1","fieldName":"resolution","fieldType":"LIST","fieldData":"[{\"index\":\"768P\",\"name\":\"768P\"},{\"index\":\"2K\",\"name\":\"2K\"},{\"default\":\"2K\",\"description\":\"忽略\"}]"},
 {"nodeId":"1","fieldName":"duration","fieldType":"LIST","fieldData":"[{\"index\":\"5\"},{\"index\":\"15\"}]"},
 {"nodeId":"1","fieldName":"ratio","fieldType":"LIST","fieldData":"[{\"index\":\"16:9\"},{\"index\":\"9:16\"}]"}
]
'@ | ConvertFrom-Json
$Text='一只橙猫坐在窗边，雨滴缓慢滑过玻璃，镜头轻轻推进。'
# First reproduce the actual v1.1 bug with the documented STRING structure.
& {
    . $OldClient
    Check-Enum ((@(Get-Choices $Rows[0]) -join '|') -ceq 'STRING') 'v1.1 wrongly treated STRING metadata as an option'
    Throws-Enum {Assert-CustomNodes @(@{nodeId='1';fieldName='prompt';fieldValue=$Text}) $Rows} 'prompt.*枚举' 'v1.1 reproduction matches reported prompt preflight rejection'
}
. $Client
Check-Enum ($script:PackageVersion -eq '1.1.1') 'corrected client version'
Check-Enum (@(Get-Choices $Rows[0]).Count -eq 0) 'STRING descriptor is not an enum'
Assert-CustomNodes @(@{nodeId='1';fieldName='prompt';fieldValue=$Text}) $Rows
Check-Enum $true 'arbitrary Chinese prompt passes typed STRING preflight'
foreach ($type in @('STRING','TEXT','INT','FLOAT','BOOLEAN','IMAGE','AUDIO','VIDEO')) {
    $row=@{fieldType=$type;fieldData='["'+$type+'",{"default":"do not use as an enum","min":0,"max":99}]'}
    Check-Enum (@(Get-Choices $row).Count -eq 0) "non-LIST $type metadata is never an allowlist"
}
Check-Enum (@(Get-Choices @{fieldType='STRING';fieldData='not a JSON list'}).Count -eq 0) 'STRING does not depend on parsing enum JSON'
Check-Enum (@(Get-Choices @{fieldData='["STRING",{"multiline":true}]'}).Count -eq 0) 'legacy missing fieldType still recognizes STRING descriptor'
Check-Enum (@(Get-Choices @{fieldData='["INT",{"default":5,"min":5,"max":15}]'}).Count -eq 0) 'legacy numeric descriptor is not an enum'
Check-Enum (@(Get-Choices @{fieldData='"STRING"'}).Count -eq 0) 'JSON scalar is not treated as an option list'
Check-Enum ((@(Get-Choices $Rows[1]) -join '|') -ceq '768P|2K') 'LIST uses option index and ignores default metadata'
Check-Enum ((@(Get-Choices @{fieldData='[{"index":"2K"}]'}) -join '|') -ceq '2K') 'legacy index list preserved'
Check-Enum ((@(Get-Choices @{fieldType='LIST';fieldData='["2K"]'}) -join '|') -ceq '2K') 'singleton list preserved on PS5.1'
Check-Enum ((@(Get-Choices @{fieldType='LIST';fieldData='[["768P","2K"],{"default":"2K"}]'}) -join '|') -ceq '768P|2K') 'nested raw combo list supported'
Check-Enum ((@(Get-Choices @{fieldType='LIST';fieldData='[["2K"]]'}) -join '|') -ceq '2K') 'single nested combo array does not flatten into metadata'
Check-Enum ((@(Get-Choices @{fieldType='LIST';fieldData='["STRING","INT"]'}) -join '|') -ceq 'STRING|INT') 'explicit LIST string literals remain valid enum values'
Check-Enum ((@(Get-Choices @{fieldType='LIST';fieldData=@(@{index='768P'},@{index='2K'})}) -join '|') -ceq '768P|2K') 'already parsed array supported'
Throws-Enum {Assert-CustomNodes @(@{nodeId='1';fieldName='resolution';fieldValue='8K'}) $Rows} '枚举' 'invalid resolution still blocked'
Throws-Enum {Assert-CustomNodes @(@{nodeId='1';fieldName='resolution';fieldValue='2k'}) $Rows} '枚举' 'enum values still case sensitive'
Throws-Enum {Assert-CustomNodes @(@{nodeId='1';fieldName='duration';fieldValue='6'}) $Rows} '枚举' 'invalid duration enum still blocked'
Throws-Enum {Assert-CustomNodes @(@{nodeId='9';fieldName='prompt';fieldValue=$Text}) $Rows} '唯一确认' 'wrong node still blocked'
$PromptList=@{nodeId='2';fieldName='prompt';fieldType='LIST';fieldData='[{"index":"A"},{"index":"B"}]'}
Throws-Enum {Assert-CustomNodes @(@{nodeId='2';fieldName='prompt';fieldValue='C'}) @($PromptList)} '枚举' 'genuine LIST named prompt is not bypassed'
Throws-Enum {Get-Choices @{fieldType='LIST';fieldData='bad'}} 'SCHEMA' 'malformed LIST JSON stops preflight'
Throws-Enum {Get-Choices @{fieldType='LIST';fieldData='{"default":"2K"}'}} 'SCHEMA' 'LIST object cannot replace an array'
Throws-Enum {Get-Choices @{fieldType='LIST';fieldData='[{"index":"2K"},{"name":"missing-index"}]'}} 'SCHEMA' 'partial LIST is not silently accepted'
$work=Join-Path ([IO.Path]::GetTempPath()) ('RH enum 中文 '+[Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($work)
$oldEnv=$env:RH_TEST_KEY;$env:RH_TEST_KEY='SYNTHETIC_NOT_A_REAL_KEY'
try {
    foreach ($resolution in @('768P','2K')) {
        $name='legacy-'+$resolution
        # Create an actual v1.1 plan and reproduce its PREFLIGHT_BLOCKED state.
        & {
            . $OldClient -Action Plan -Resolution $resolution -Prompt $Text -RunName $name -OutputDirectory $work -KeyVariable RH_TEST_KEY
            function Invoke-RHCurl { throw 'Unexpected real request' }
            Main | Out-Null
        }
        $path=Join-Path (Join-Path $work $name) 'plan.json'
        $before=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
        & {
            . $OldClient -Action Submit -RunName $name -OutputDirectory $work -ConfirmConsoleBalance -Execute
            function Get-Account { return @{apiType='NORMAL';remainCoins=100;currentTaskCounts=0} }
            function Get-AppRows { return $Rows }
            function Invoke-RHCurl { throw 'Unexpected creation request before failed preflight' }
            Throws-Enum {Main} 'prompt.*枚举' "old $resolution full Submit reproduces bug before request"
            $state=Read-JsonFile (Join-Path (Join-Path $work $name) 'state.json')
            Check-Enum ($state.state -eq 'PREFLIGHT_BLOCKED' -and -not $state.generationRequestSent) "old $resolution failure did not submit"
            Check-Enum (-not (Test-Path (Join-Path (Join-Path $work $name) 'submit-once.lock'))) "old $resolution failure left no replay lock"
        }
        & {
            . $Client -Action Submit -RunName $name -OutputDirectory $work -ConfirmConsoleBalance -Execute
            $script:EnumCreates=0
            function Get-Account { return @{apiType='NORMAL';remainCoins=100;currentTaskCounts=0} }
            function Get-AppRows { return $Rows }
            function Invoke-RHCurl($Path,$Body) {
                if ($Path -ne '/task/openapi/ai-app/run') { throw 'unexpected endpoint' }
                $script:EnumCreates++
                Check-Enum ($Body.nodeInfoList[0].fieldValue -ceq $Text) "fixed $resolution preserves exact user prompt"
                Check-Enum ($Body.nodeInfoList[1].fieldValue -ceq $resolution) "fixed $resolution preserves saved resolution"
                return @{code=0;data=@{taskId='9000000000000000101'}}
            }
            Main | Out-Null
            Check-Enum ($script:EnumCreates -eq 1) "fixed $resolution submits once after corrected preflight"
            Check-Enum ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -eq $before) "fixed $resolution resumes unchanged v1.1 plan"
            Throws-Enum {Main} '一次生成提交' "fixed $resolution retains repeat-submit protection"
            Check-Enum ($script:EnumCreates -eq 1) "fixed $resolution duplicate sends no second request"
        }
    }
    $result=[ordered]@{packageVersion='1.1.1';powershell=$PSVersionTable.PSVersion.ToString();passed=$script:EnumPassed;liveRunningHubRequests=0;paidTasks=0;fixture='official STRING descriptor and synthetic LIST records';reproducesOriginal=$true;legacyPlansResumedWithoutRewrite=$true}
    if ($env:RH_ENUM_RESULT_PATH) {
        [IO.File]::WriteAllText($env:RH_ENUM_RESULT_PATH,($result|ConvertTo-Json),(New-Object Text.UTF8Encoding($false)))
    }
    $result|ConvertTo-Json|Write-Host
} finally {
    $env:RH_TEST_KEY=$oldEnv
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
