"""
DIVISION 3: CREW REGISTRATION WIZARD
======================================
Interactive tool to register cleaning crews, inspectors, and maintenance staff.

Each registered crew member gets a numeric Crew ID they use to log in
to the Fortress Field Ops mobile app (/mobile).

Usage:
    python3 src/register_crew.py                 # Interactive wizard
    python3 src/register_crew.py --list          # Show all crew
    python3 src/register_crew.py --quick "Name" "Role" "Phone"  # One-shot

Module: CF-01 Guardian Ops — Division 3 Operations Kernel
"""

import sys
import json
import argparse
import requests

API_URL = "http://localhost:8000/ops/crew"


def register_interactive():
    """Interactive registration loop."""
    print("=" * 50)
    print("  FORTRESS CREW REGISTRATION")
    print("=" * 50)

    while True:
        print()
        name = input("  Name (or Enter to quit): ").strip()
        if not name:
            break

        role = input("  Role (Cleaner / Inspector / Maintenance / Manager): ").strip()
        if not role:
            role = "Cleaner"

        phone = input("  Phone: ").strip()
        location = input("  Location (e.g., Blue Ridge): ").strip()

        # Skills prompt
        skills = {}
        skill_input = input("  Skills (comma-separated, e.g., deep_clean,hot_tub): ").strip()
        if skill_input:
            for s in skill_input.split(","):
                skills[s.strip()] = True

        payload = {
            "name": name,
            "role": role,
            "phone": phone or None,
            "current_location": location or None,
            "skills": skills,
            "status": "ACTIVE",
        }

        try:
            res = requests.post(API_URL, json=payload, timeout=5)
            if res.status_code in (200, 201):
                data = res.json()
                print(f"\n  REGISTERED: {name}")
                print(f"  CREW ID:    {data['id']}  <-- Give this to them for the mobile app")
                print(f"  Role:       {data['role']}")
            else:
                print(f"  FAILED: {res.status_code} — {res.text[:200]}")
        except Exception as e:
            print(f"  ERROR: {e}")

        if input("\n  Register another? (y/n): ").strip().lower() != "y":
            break

    print("\n  Registration complete.")
    list_crew()


def register_quick(name, role, phone):
    """One-shot registration."""
    payload = {
        "name": name,
        "role": role,
        "phone": phone,
        "status": "ACTIVE",
    }
    try:
        res = requests.post(API_URL, json=payload, timeout=5)
        if res.status_code in (200, 201):
            data = res.json()
            print(f"  Registered: {name} | ID: {data['id']} | Role: {data['role']}")
            return data["id"]
        else:
            print(f"  Failed: {res.text[:200]}")
    except Exception as e:
        print(f"  Error: {e}")
    return None


def list_crew():
    """Display the current crew roster."""
    try:
        res = requests.get(API_URL, timeout=5)
        crew = res.json()
    except Exception as e:
        print(f"  Cannot reach API: {e}")
        return

    if not crew:
        print("\n  No crew registered. Run: python3 src/register_crew.py")
        return

    print(f"\n  {'ID':>4}  {'Name':<25} {'Role':<15} {'Phone':<15} {'Location':<20} {'Status'}")
    print("  " + "-" * 95)
    for c in crew:
        print(
            f"  {c['id']:>4}  {c['name']:<25} {c['role']:<15} "
            f"{(c['phone'] or '')::<15} {(c['current_location'] or '')::<20} {c['status']}"
        )
    print(f"\n  Total: {len(crew)} crew members")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fortress Crew Registration")
    parser.add_argument("--list", action="store_true", help="List all crew")
    parser.add_argument("--quick", nargs=3, metavar=("NAME", "ROLE", "PHONE"),
                        help="Quick registration: Name Role Phone")
    args = parser.parse_args()

    if args.list:
        list_crew()
    elif args.quick:
        register_quick(*args.quick)
    else:
        register_interactive()
