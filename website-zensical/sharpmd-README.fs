module Dio.READMEmd

let file = """# Diogenes documentation source

This directory contains the F#-wrapped source for `dio.shel.sh`. Preview renders
the wrappers into Markdown, JavaScript, CSS, templates, and `zensical.toml` in a
temporary output directory.

## Run Preview

Open the Live Editor Zensical Preview GUI from fresh git clone:

```powershell
git clone https://github.com/CommanderTurtle/preview preview; `
git clone --branch clonable --single-branch https://github.com/CommanderTurtle/orc orc; `
git archive --remote=https://github.com/CommanderTurtle/orc main dio/ | tar.exe -x; `
cd preview && cargo build --release; `
cd target/release && explorer .
```

Or use the render directly from the F# project:

```powershell
git clone --branch clonable --single-branch https://github.com/CommanderTurtle/orc orc; `
git archive --remote=https://github.com/CommanderTurtle/orc main dio/ | tar.exe -x; `
dotnet fsi orc/GenerateConfig.fsx render-site "dio" "dio/output" --clean

# Recommended, for editing raw HTML find&replace >< with >\n< for readability
```

Restart the site after changing `zensical.fs`, an override, or navigation.
Content and asset wrappers are re-rendered by the normal Preview cycle.

## Add pages

Create a `sharpmd-<name>.fs` wrapper beneath `docs/<section>/`. A section landing
page uses `indexmd.fs` and renders to `index.md`.

For a batch of Markdown files, use the generator:

```powershell
$orc = 'C:\path\to\orc'
$dio = 'C:\path\to\dio'
Get-ChildItem "$dio\output" -Recurse -Filter *.html -File | Rename-Item -NewName { $_.BaseName + ".raw" }; `
dotnet run --project "$orc\src\generator\Generator.fsproj" -- wrap-batch '$dio\output' "$dio\output\rewrapped"; `
Get-ChildItem "$dio\output\rewrapped" -Recurse -File | Rename-Item -NewName { $_.Name.Replace("sharpraw", "sharphtml") }; `
Get-ChildItem "$dio\output\rewrapped" -Recurse -File | Rename-Item -NewName { $_.Name.Replace("sharpmd-index", "indexmd") }; `
Get-ChildItem "$dio\output\rewrapped" -Recurse -File | Rename-Item -NewName { $_.Name.Replace("sharpoml-zensical", "zensical") }; `
Get-ChildItem "$dio\output\rewrapped" -Recurse -Filter *.raw -File | Rename-Item -NewName { $_.BaseName + ".html" }
```

Add each rendered path to the navigation array in `zensical.fs` (`zensical.toml`)
"""

let render() = file