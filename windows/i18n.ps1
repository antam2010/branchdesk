# Shared translation support for native Windows helpers.
if (!$BranchdeskCatalogJson) {
    $catalogFile = Join-Path $PSScriptRoot 'i18n.json'
    if (!(Test-Path -LiteralPath $catalogFile)) { $catalogFile = Join-Path $PSScriptRoot '..\web\i18n.json' }
    $BranchdeskCatalogJson = Get-Content -LiteralPath $catalogFile -Raw -Encoding UTF8
}
$script:BranchdeskTranslations = $BranchdeskCatalogJson | ConvertFrom-Json
$script:BranchdeskUiLanguage = 'ko'
try {
    $languageFile = Join-Path $env:LOCALAPPDATA 'Branchdesk\language.txt'
    $language = (Get-Content -LiteralPath $languageFile -Raw -Encoding ASCII -ErrorAction Stop).Trim()
    if ($language -in @('en','ja')) { $script:BranchdeskUiLanguage = $language }
} catch {}
function T([string]$Key) {
    $value = $Key
    if ($script:BranchdeskUiLanguage -ne 'ko') {
        $map = $script:BranchdeskTranslations.PSObject.Properties[$script:BranchdeskUiLanguage].Value
        $entry = $map.PSObject.Properties[$Key]
        if ($entry) { $value = [string]$entry.Value }
        elseif ($map.PSObject.Properties[$Key.Trim()]) {
            $value = $Key.Substring(0,$Key.Length-$Key.TrimStart().Length) + [string]$map.PSObject.Properties[$Key.Trim()].Value + $Key.Substring($Key.TrimEnd().Length)
        }
    }
    return $ExecutionContext.InvokeCommand.ExpandString($value)
}
