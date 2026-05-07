"""
Salary Module Replacement Script
Replaces buggy salary files with fixed versions from fixed_files folder.
"""

import os
import shutil
import traceback
from datetime import datetime

PROJECT_ROOT = r"C:\Users\ASUS\OneDrive\Desktop\garage"
FIXED_FILES_DIR = os.path.join(PROJECT_ROOT, "fixed_files")
BACKUP_DIR = os.path.join(PROJECT_ROOT, "backup", f"salary_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

REPLACEMENTS = [
    ("models/salary_model.py",           "models/salary_model.py"),
    ("routes/admin_salary_routes.py",     "routes/admin_salary_routes.py"),
    ("services/salary_service.py",        "services/salary_service.py"),
    ("utils/pdf_generator.py",            "utils/pdf_generator.py"),
    ("templates/admin_salary.html",       "templates/admin_salary.html"),
    ("templates/salary_history_edit.html","templates/salary_history_edit.html"),
    ("templates/salary_history.html",     "templates/salary_history.html"),
]

def log(msg):
    print(f"  {msg}")

def replace_files():
    replaced = []
    errors = []

    os.makedirs(BACKUP_DIR, exist_ok=True)

    print(f"\nBackup folder: {BACKUP_DIR}\n")
    print("=" * 60)
    print("REPLACEMENT REPORT")
    print("=" * 60)

    for fixed_rel, dest_rel in REPLACEMENTS:
        fixed_path = os.path.join(FIXED_FILES_DIR, fixed_rel)
        dest_path  = os.path.join(PROJECT_ROOT, dest_rel)
        backup_path = os.path.join(BACKUP_DIR, dest_rel)

        if not os.path.exists(fixed_path):
            print(f"\n[-] SKIPPED (no fixed version): {dest_rel}")
            errors.append({"file": dest_rel, "reason": "No fixed version found"})
            continue

        if os.path.exists(dest_path):
            backup_dir = os.path.dirname(backup_path)
            os.makedirs(backup_dir, exist_ok=True)
            shutil.copy2(dest_path, backup_path)
            print(f"\n[+] BACKUP:  {dest_rel}  ->  {os.path.relpath(backup_path, PROJECT_ROOT)}")
        else:
            print(f"\n[!] NEW FILE (no existing to backup): {dest_rel}")

        try:
            shutil.copy2(fixed_path, dest_path)
            print(f"[OK] REPLACED: {dest_rel}")
            replaced.append(dest_rel)
        except Exception as e:
            print(f"[FAIL] {dest_rel} -> {e}")
            errors.append({"file": dest_rel, "reason": str(e)})

    print("\n" + "=" * 60)
    print(f"SUMMARY: {len(replaced)} replaced, {len(errors)} skipped/failed")
    print("=" * 60)

    if errors:
        print("\nSkipped/Failed files:")
        for e in errors:
            print(f"  - {e['file']} ({e['reason']})")

    return replaced, errors

def verify_structure():
    print("\n" + "=" * 60)
    print("STRUCTURE VERIFICATION")
    print("=" * 60)
    files_to_check = [
        "models/salary_model.py",
        "routes/admin_salary_routes.py",
        "services/salary_service.py",
        "utils/pdf_generator.py",
        "templates/admin_salary.html",
        "templates/salary_history_edit.html",
        "templates/salary_history.html",
    ]
    all_ok = True
    for f in files_to_check:
        path = os.path.join(PROJECT_ROOT, f)
        status = "EXISTS" if os.path.exists(path) else "MISSING"
        mark = "OK" if os.path.exists(path) else "FAIL"
        if "MISSING" in status:
            all_ok = False
        print(f"  [{mark}] {f}: {status}")
    return all_ok

def verify_imports():
    print("\n" + "=" * 60)
    print("IMPORT / ROUTE VERIFICATION")
    print("=" * 60)
    import_ok = True

    # Check if replaced files have valid Python syntax
    py_files = [
        os.path.join(PROJECT_ROOT, "models", "salary_model.py"),
        os.path.join(PROJECT_ROOT, "routes", "admin_salary_routes.py"),
        os.path.join(PROJECT_ROOT, "services", "salary_service.py"),
        os.path.join(PROJECT_ROOT, "utils", "pdf_generator.py"),
    ]
    for f in py_files:
        try:
            with open(f, "r", encoding="utf-8") as fp:
                compile(fp.read(), f, "exec")
            print(f"  [OK] Syntax: {os.path.relpath(f, PROJECT_ROOT)}")
        except SyntaxError as e:
            print(f"  [FAIL] Syntax error in {os.path.relpath(f, PROJECT_ROOT)}: {e}")
            import_ok = False

    return import_ok

if __name__ == "__main__":
    print("SALARY MODULE REPLACEMENT SCRIPT")
    print("Backup before replace: YES")
    print("Protected: data/, database files, uploads/")
    print()

    replaced, errors = replace_files()
    ok = verify_structure()
    import_ok = verify_imports()

    print("\n" + "=" * 60)
    print("ROLLBACK INSTRUCTIONS")
    print("=" * 60)
    print(f"If something breaks, run this in PowerShell to restore from backup:")
    print(f'  $backup = "{BACKUP_DIR}"')
    print(f'  $dest   = "{PROJECT_ROOT}"')
    print(f'  Get-ChildItem $backup -Recurse -File | ForEach-Object {{')
    print(f'      $rel = $_.FullName.Substring($backup.Length).TrimStart("\\")')
    print(f'      $dst = Join-Path $dest $rel')
    print(f'      New-Item -ItemType File -Path (Split-Path $dst) -Force | Out-Null')
    print(f'      Copy-Item $_.FullName -Destination $dst -Force')
    print(f'  }}')
    print()
    print(f"Backup location: {BACKUP_DIR}")
    print("=" * 60)

    print("\n" + "=" * 60)
    print("POST-REPLACEMENT CHECKLIST")
    print("=" * 60)
    print("  1. Salary save      -> admin_salary.html form submission")
    print("  2. Salary history    -> /admin/salary-history route")
    print("  3. Edit salary       -> salary_history_edit.html")
    print("  4. PDF download      -> /admin/salary/<id>/pdf route")
    print()
    print("To start Flask and test manually:")
    print('  set FLASK_APP=app.py && set FLASK_ENV=development && flask run --host=127.0.0.1 --port=5000')
    print("=" * 60)
