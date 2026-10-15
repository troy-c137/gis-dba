"""Switch only host connection ports in .env; credentials are shared between the lab clusters."""
import argparse
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=['native', 'docker'])
args = parser.parse_args()
path = Path(__file__).resolve().parents[1] / '.env'
lines = path.read_text().splitlines()
ports = {'native': 5432, 'docker': 55432}
for index, line in enumerate(lines):
    if line.startswith(('ADMIN_DATABASE_URL=', 'DATABASE_URL=', 'INGEST_DATABASE_URL=',
                        'MONITOR_DATABASE_URL=')):
        key, value = line.split('=', 1)
        parts = urlsplit(value)
        credentials, host = parts.netloc.rsplit('@', 1)
        if host.split(':', 1)[0] != '127.0.0.1':
            parser.error('Refusing to modify a non-local database URL')
        lines[index] = key + '=' + urlunsplit(parts._replace(
            netloc=credentials + '@127.0.0.1:' + str(ports[args.mode])))
path.write_text('\n'.join(lines) + '\n')
print(f'Host clients now use {args.mode} on port {ports[args.mode]}; restart the host API')
