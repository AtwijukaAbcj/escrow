This folder contains a minimal Django + Django REST Framework backend scaffold to replace the existing Express backend.

Quick start (Windows / Powershell):

1. Create and activate a virtualenv

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Run migrations and start server

```powershell
cd django_backend
python manage.py migrate
python manage.py runserver
```

3. Import existing JSON data (optional)

```powershell
python manage.py shell --command "from scripts.import_json import run_import; run_import()"
```

4. Load complete local demo data (optional)

```powershell
python manage.py seed_demo_data
```

This command is idempotent and populates demo users, transactions, milestones, documents,
contracts, signatures, payments, ledger entries, disputes, and KYC/KYB compliance records.
Demo accounts use the password `DemoPass123!` by default:
`admin.demo`, `staff.demo`, `buyer.demo`, `seller.demo`, `business.demo`, and `verifier.demo`.
Use `--password` to set a different local demo password.

Notes:
- Media (uploads) path is configured to point at `../backend/data/uploads` so existing uploaded files are usable.
- JWT auth is provided by `djangorestframework-simplejwt`.
- This scaffold implements basic models and endpoints for parties, transactions, documents, and KYC pending list. Extend as needed to fully match business logic.
