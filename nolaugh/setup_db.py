import os, django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nolaugh.settings')
django.setup()

from django.core.management import call_command
call_command('makemigrations', 'game')
call_command('migrate')
call_command('collectstatic', '--noinput')
print("Done.")
