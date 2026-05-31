"""
Run this instead of daphne directly.
Usage: py run.py
"""
import os, sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nolaugh.settings')

from daphne.cli import CommandLineInterface

sys.argv = [
    'daphne',
    '-e', 'ssl:8443:privateKey=key.pem:certKey=cert.pem:interface=0.0.0.0',
    'nolaugh.asgi:application',
]

CommandLineInterface.entrypoint()
