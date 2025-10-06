<# 
seed_skills_lessons.ps1
Bulk-import Skills then Lessons for all topics via Django management commands.

USAGE (PowerShell):
  # Activate your virtualenv first, then run:
  .\seed_skills_lessons.ps1 -ServerPath "D:\AI_LL\server" -DatasetPath "D:\AI_LL\dataset"

PARAMETERS:
  -ServerPath  : Folder containing manage.py
  -DatasetPath : Folder containing skills_*.json and lessons_*.json files
  -PythonExe   : Optional. Path to python executable (default: 'python' on PATH)
#>

param(
  [string]$ServerPath = ".",
  [string]$DatasetPath = "D:\AI_LL\dataset",
  [string]$PythonExe = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Topics list (slugs)
$slugs = @(
  'a1-greetings','a1-numbers-dates','a1-daily-activities',
  'a2-food-drinks','a2-shopping','a2-travel-directions',
  'b1-school-work','b1-hobbies-free-time','b1-health-emergencies',
  'b2-opinions-debates','b2-media-technology','b2-environment-society',
  'c1-academic-english','c1-business-english','c1-culture-politics',
  'c2-idioms-phrases','c2-advanced-writing','c2-fluency-masterclass'
)

function Invoke-Manage {
  param(
    [Parameter(Mandatory=$true)][string[]]$Args
  )
  & $PythonExe manage.py @Args
  if ($LASTEXITCODE -ne 0) {
    throw "manage.py $($Args -join ' ') failed with exit code $LASTEXITCODE"
  }
}

function Ensure-Path {
  param([string]$PathToCheck)
  if (-not (Test-Path -LiteralPath $PathToCheck)) {
    Write-Warning "Missing file: $PathToCheck"
    return $false
  }
  return $true
}

# Preflight checks
$managePy = Join-Path -Path $ServerPath -ChildPath "manage.py"
if (-not (Test-Path -LiteralPath $managePy)) {
  throw "manage.py not found at: $managePy"
}

Push-Location $ServerPath
try {
  Write-Host "=== Import SKILLS ==="
  foreach ($s in $slugs) {
    $skillsFile = Join-Path -Path $DatasetPath -ChildPath ("skills_{0}.json" -f $s)
    if (Ensure-Path $skillsFile) {
      Invoke-Manage -Args @("load_skills_flat", $skillsFile)
    } else {
      Write-Warning "Skipped SKILLS for topic '$s' (file not found)."
    }
  }

  Write-Host "`n=== Import LESSONS ==="
  foreach ($s in $slugs) {
    $lessonsFile = Join-Path -Path $DatasetPath -ChildPath ("lessons_{0}.json" -f $s)
    if (Ensure-Path $lessonsFile) {
      Invoke-Manage -Args @("load_lessons_flat", $lessonsFile, "--topic", $s)
    } else {
      Write-Warning "Skipped LESSONS for topic '$s' (file not found)."
    }
  }

  Write-Host "`nAll done."
}
finally {
  Pop-Location
}
