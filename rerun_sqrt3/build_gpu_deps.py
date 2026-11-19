from pathlib import Path
import subprocess
import tarfile

root = Path(__file__).resolve().parent
ram = root / 'vortex-source/third_party/ramulator'
for name, archive in [('yaml-cpp', 'yaml-cpp-0.7.0'), ('spdlog', 'spdlog-1.11.0'), ('argparse', 'argparse-2.9')]:
    dest = ram / 'ext' / name
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(root / 'downloads' / (archive + '.tar.gz')) as tf:
        members = tf.getmembers()
        for member in members:
            member.name = '/'.join(member.name.split('/')[1:])
            if member.name:
                tf.extract(member, dest, filter='data')
build = ram / 'build-offline'
subprocess.run(['cmake', '-S', str(ram), '-B', str(build), *[
    '-DFETCHCONTENT_SOURCE_DIR_' + name.upper() + '=' + str(ram / 'ext' / name)
    for name in ['yaml-cpp', 'spdlog', 'argparse']]], check=True)
subprocess.run(['cmake', '--build', str(build), '--target', 'ramulator', '-j2'], check=True)
