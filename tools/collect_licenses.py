"""Ship license text from installed distributions alongside the executable."""
from importlib import metadata
from pathlib import Path
import shutil
import sys
import zipfile

root = Path(__file__).resolve().parents[1]
target = root / 'dist' / 'THIRD_PARTY_LICENSES'
target.mkdir(parents=True, exist_ok=True)
qt_license_directory = target / 'Qt'
qt_license_directory.mkdir(exist_ok=True)
for license_file in (root / 'assets' / 'licenses').glob('*.txt'):
    shutil.copyfile(license_file, qt_license_directory / license_file.name)
python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if python_license.exists():
    shutil.copyfile(python_license, target / 'Python-LICENSE.txt')
for name in ['PySide6-Essentials', 'shiboken6', 'smartthings-local', 'cbor2', 'cryptography', 'pyOpenSSL', 'cffi', 'pycparser', 'typing-extensions', 'requests', 'urllib3', 'certifi', 'charset-normalizer', 'idna', 'tinytuya', 'colorama']:
    distribution = metadata.distribution(name)
    directory = target / name
    for file in distribution.files or []:
        if any(part.lower().startswith(('license', 'copying', 'copyright', 'notice')) for part in file.parts):
            source = Path(distribution.locate_file(file))
            if source.is_file():
                directory.mkdir(exist_ok=True)
                destination = directory / str(file).replace('/', '_').replace('\\', '_')
                shutil.copyfile(source, destination)
for name in ('THIRD_PARTY_NOTICES.md', 'README.md'):
    source = root / 'docs' / name
    if source.exists(): shutil.copyfile(source, root / 'dist' / name)
with zipfile.ZipFile(root / 'dist' / 'WindFreeTray-source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for directory in ['app', 'lamp', 'shared', 'windfree', 'tests', 'tools', 'docs', 'assets']:
        for file in (root / directory).rglob('*'):
            if file.is_file() and '__pycache__' not in file.parts:
                archive.write(file, file.relative_to(root))
    for name in ['main.py', 'requirements.txt', 'requirements-dev.txt', 'build.ps1']:
        archive.write(root / name, name)
print('Licenças, instruções e código-fonte incluídos em dist.')
