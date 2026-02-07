#!/usr/bin/env python3
"""Detailed analysis of auth package imports."""

import os
from pathlib import Path

print("=" * 80)
print("DETAILED AUTH PACKAGE ANALYSIS")
print("=" * 80)

# Check what exists
print("\n📁 TOP-LEVEL auth/ files:")
top_auth = Path("/home/vini/scriptml/auth")
for f in sorted(top_auth.glob("*.py")):
    print(f"   - {f.name}")

print("\n�� NESTED mercadolivre_upload/auth/ files:")
nested_auth = Path("/home/vini/scriptml/mercadolivre_upload/auth")
for f in sorted(nested_auth.glob("*.py")):
    print(f"   - {f.name}")

print("\n" + "=" * 80)
print("FILES IMPORTING FROM TOP-LEVEL auth/")
print("=" * 80)

files_using_top = [
    "mercadolivre_upload/application/publish_product.py",
    "mercadolivre_upload/cli/__init__.py",
    "tests/test_authenticator.py",
]

for f in files_using_top:
    path = Path("/home/vini/scriptml") / f
    if path.exists():
        print(f"\n📄 {f}:")
        with open(path) as file:
            for i, line in enumerate(file, 1):
                if "from auth" in line or "import auth" in line:
                    print(f"   Line {i}: {line.rstrip()}")

print("\n" + "=" * 80)
print("FILES IMPORTING FROM NESTED mercadolivre_upload/auth/")
print("=" * 80)

files_using_nested = [
    "mercadolivre_upload/api/client.py",
    "mercadolivre_upload/cli/commands/upload.py",
    "mercadolivre_upload/cli/commands/doctor.py",
    "mercadolivre_upload/pipeline.py",
]

for f in files_using_nested:
    path = Path("/home/vini/scriptml") / f
    if path.exists():
        print(f"\n📄 {f}:")
        with open(path) as file:
            for i, line in enumerate(file, 1):
                if "mercadolivre_upload.auth" in line or "auth.manager" in line:
                    print(f"   Line {i}: {line.rstrip()}")

print("\n" + "=" * 80)
print("ISSUE: mercadolivre_upload/auth/manager.py does NOT exist!")
print("=" * 80)
print("\nThe import 'from mercadolivre_upload.auth.manager import AuthManager'")
print("in pipeline.py is BROKEN because there's no manager.py file.")
print("\nAvailable modules in mercadolivre_upload/auth/:")
print("   - authenticator.py")
print("   - exceptions.py") 
print("   - oauth.py")
print("   - secure_storage.py")
print("   - token_manager.py")
