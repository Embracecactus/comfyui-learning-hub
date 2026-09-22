#!/usr/bin/env python3
"""Apply the narrowly scoped v1.1.1 enum hotfix to the verified v1.1 client.

No network, credentials, RunningHub submissions or user's result-directory writes.
The input directory must contain the exact previously delivered v1.1 scripts.
"""
from pathlib import Path
import hashlib
import sys

root = Path(sys.argv[1]).resolve()
p = root / 'rh-curl.ps1'
raw = p.read_bytes()
expected = '5c1e7e21f4c286d87dc82352da5a4e9448bb9873ce73fc55f10636b8f7d3d1a1'
if hashlib.sha256(raw).hexdigest() != expected:
    raise SystemExit('Unexpected v1.1 source hash; do not patch another version.')
(root / 'rh-curl-v1.1-original.ps1').write_bytes(raw)
s = raw.decode('utf-8-sig').replace('\r\n', '\n')
a = s.index('function Get-Choices($Row) {')
b = s.index('function Make-Nodes(', a)
s = s[:a] + r'''function Get-Choices($Row) {
    # fieldData is not necessarily an enumeration. For example, STRING uses
    # ["STRING", {"default":"", "multiline":true}] and IMAGE has upload metadata.
    # The declared fieldType is authoritative. Never special-case the name prompt:
    # a different app may legitimately expose a LIST whose fieldName is prompt.
    $kind = ([string](Get-Field $Row 'fieldType')).Trim().ToUpperInvariant()
    if ($kind -and $kind -ne 'LIST') { return @() }
    $fd = Get-Field $Row 'fieldData'
    if ($null -eq $fd -or ($fd -is [string] -and [string]::IsNullOrWhiteSpace($fd))) { return @() }
    if ($fd -is [string]) {
        try {
            # A wrapper preserves nested / singleton arrays on Windows PowerShell 5.1.
            $parsed = ('{"items":' + $fd + '}') | ConvertFrom-Json
            $items = $parsed.items
        } catch {
            if ($kind -eq 'LIST') { throw '[SCHEMA] LIST fieldData 不是有效JSON。未提交。' }
            return @()  # Unspecified type + unrecognized metadata is NOT an enum.
        }
    } else { $items = $fd }
    if ($items -isnot [array]) {
        if ($kind -eq 'LIST') { throw '[SCHEMA] LIST fieldData 不是选项数组。未提交。' }
        return @()
    }
    if ($items.Count -eq 0) { return @() }
    # Legacy responses may omit fieldType. Recognize the type-descriptor tuple
    # before processing actual lists. Do not turn default/min/max into options.
    $typeTokens = @('STRING','TEXT','INT','INTEGER','FLOAT','NUMBER','BOOLEAN','BOOL','IMAGE','VIDEO','AUDIO','ZIP','FILE')
    if (-not $kind -and $items[0] -is [string] -and $items[0].ToUpperInvariant() -in $typeTokens) {
        if ($items.Count -eq 1 -or ($items.Count -eq 2 -and
            ($items[1] -is [System.Collections.IDictionary] -or
             $items[1] -is [pscustomobject]))) { return @() }
    }
    # Also support a Comfy-style [[option1, option2], {default:...}] enum.
    if ($items[0] -is [array]) {
        if ($items.Count -gt 2 -or ($items.Count -eq 2 -and
            $items[1] -isnot [System.Collections.IDictionary] -and
            $items[1] -isnot [pscustomobject])) {
            throw '[SCHEMA] 无法解析嵌套选项数组。未提交。'
        }
        $items = $items[0]
    }
    $values = @()
    foreach ($v in $items) {
        if ($v -is [string] -or $v -is [ValueType]) {
            $values += [string]$v
            continue
        }
        $value = Get-Field $v 'index'
        if ($null -eq $value) { $value = Get-Field $v 'value' }
        if ($null -ne $value -and ($value -is [string] -or $value -is [ValueType])) {
            $values += [string]$value
            continue
        }
        # RunningHub's documented list ends with {default:..., description:...}.
        # It is UI metadata, not an extra choice and not the only permitted value.
        if ($null -ne $v -and (Has-Field $v 'default') -and
            -not (Has-Field $v 'index') -and -not (Has-Field $v 'value')) { continue }
        if ($kind -eq 'LIST') { throw '[SCHEMA] LIST中有无法识别的选项；不采用部分枚举。未提交。' }
        return @()  # Legacy unknown metadata must not become a partial allowlist.
    }
    return $values
}
''' + s[b:]
s = s.replace("$script:PackageVersion = '1.1.0'", "$script:PackageVersion = '1.1.1'")
old = "fieldName=(Get-Field $row 'fieldName');defaultValue=$value;choices="
new = "fieldName=(Get-Field $row 'fieldName');fieldType=(Get-Field $row 'fieldType');defaultValue=$value;choices="
if s.count(old) != 1:
    raise SystemExit('AppInfo marker mismatch')
s = s.replace(old, new)
p.write_bytes(b'\xef\xbb\xbf' + s.replace('\n', '\r\n').encode('utf-8'))
# Keep all 62 previous checks; report the version of the actual client under test.
t = root / '99-Check-Offline.ps1'
if hashlib.sha256(t.read_bytes()).hexdigest() != 'e24dfcf43852db05f9251eed2e45871cafff3a73b86021a6253893a23a29cabd':
    raise SystemExit('Unexpected original regression source hash')
text = t.read_text(encoding='utf-8-sig').replace("packageVersion='1.1.0'", 'packageVersion=$script:PackageVersion')
t.write_bytes(b'\xef\xbb\xbf' + text.replace('\n', '\r\n').encode('utf-8'))
for f in (p, t):
    print(f.name, hashlib.sha256(f.read_bytes()).hexdigest())
