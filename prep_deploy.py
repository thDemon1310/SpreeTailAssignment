import os
import re

# 1. Update requirements.txt
reqs = []
with open('backend/requirements.txt', 'r') as f:
    reqs = f.read().splitlines()

new_reqs = ['gunicorn', 'dj-database-url', 'whitenoise']
for req in new_reqs:
    if not any(req in r for r in reqs):
        reqs.append(req)

with open('backend/requirements.txt', 'w') as f:
    f.write('\n'.join(reqs) + '\n')

# 2. Update settings.py
with open('backend/spreetail_backend/settings.py', 'r') as f:
    settings = f.read()

# Add import dj_database_url
if 'import dj_database_url' not in settings:
    settings = settings.replace('from dotenv import load_dotenv', 'from dotenv import load_dotenv\nimport dj_database_url')

# Replace DATABASES
db_pattern = re.compile(r"DATABASES = \{.*?\n\}", re.DOTALL)
new_db = """DATABASES = {
    'default': dj_database_url.config(
        default=os.getenv('DATABASE_URL', f"postgresql://{os.getenv('DB_USER', 'utplaksh')}:{os.getenv('DB_PASSWORD', '')}@{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/{os.getenv('DB_NAME', 'spreetail')}"),
        conn_max_age=600,
        conn_health_checks=True,
    )
}"""
settings = db_pattern.sub(new_db, settings)

# Add whitenoise to MIDDLEWARE
if 'whitenoise.middleware.WhiteNoiseMiddleware' not in settings:
    settings = settings.replace(
        "'django.middleware.security.SecurityMiddleware',",
        "'django.middleware.security.SecurityMiddleware',\n    'whitenoise.middleware.WhiteNoiseMiddleware',"
    )

# Add STATIC_ROOT and STATICFILES_STORAGE
if 'STATIC_ROOT' not in settings:
    settings = settings.replace(
        "STATIC_URL = 'static/'",
        "STATIC_URL = 'static/'\nSTATIC_ROOT = BASE_DIR / 'staticfiles'\nSTATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'"
    )

with open('backend/spreetail_backend/settings.py', 'w') as f:
    f.write(settings)

# 3. Create build.sh
build_sh = '''#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate
'''
with open('backend/build.sh', 'w') as f:
    f.write(build_sh)
os.chmod('backend/build.sh', 0o755)
