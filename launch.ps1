param([string]$uri)
# Opens the 2014 client for a Play button press: rbx2014://join?u=<join script url>
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Add-Type -AssemblyName System.Web
$q = [System.Web.HttpUtility]::ParseQueryString(($uri -replace '^rbx2014://join\??', ''))
$join = $q['u']
if (-not $join) { exit 1 }
$base = ([System.Uri]$join).GetLeftPart([System.UriPartial]::Authority) + '/'
$xml = "<?xml version=`"1.0`" encoding=`"UTF-8`"?>`r`n<Settings>`r`n`t<ContentFolder>content</ContentFolder>`r`n`t<BaseUrl>$($base)www.civdefn.tk/</BaseUrl>`r`n</Settings>`r`n"
[IO.File]::WriteAllText((Join-Path $dir 'AppSettings.xml'), $xml)
Start-Process -FilePath (Join-Path $dir 'RobloxPlayerBeta.exe') -WorkingDirectory $dir -ArgumentList @('--play', '-a', "`"$($base)Login/Negotiate.ashx`"", '-t', '0', '-j', "`"$join`"")
