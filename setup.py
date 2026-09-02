# -*- encoding: utf-8 -*-
from setuptools import setup, find_packages

with open('README.rst', 'r', encoding='utf-8') as fh:
    long_description = fh.read()

# Loads _version.py module without importing the whole package.
def get_version_and_cmdclass(pkg_path):
    import os
    from importlib.util import module_from_spec, spec_from_file_location
    spec = spec_from_file_location(
        'version', os.path.join(pkg_path, '_version.py'),
    )
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.__version__, module.get_cmdclass(pkg_path)

version, cmdclass = get_version_and_cmdclass('src/benji')

setup(
    name='benji',
    version=version,
    cmdclass=cmdclass,
    description='A block based deduplicating backup software for Ceph RBD, image files and devices ',
    long_description=long_description,
    long_description_content_type='text/x-rst',
    classifiers="""Development Status :: 3 - Alpha
Environment :: Console
Intended Audience :: System Administrators
License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)
Operating System :: POSIX
Programming Language :: Python :: 3.7
Programming Language :: Python :: 3.8
Programming Language :: Python :: 3.9
Programming Language :: Python :: 3.10
Programming Language :: Python :: 3.11
Topic :: System :: Archiving :: Backup
"""[:-1].split('\n'),
    keywords='backup',
    author='Lars Fenneberg <lf@elemental.net>, Daniel Kraft <daniel.kraft@d9t.de>',
    author_email='lf@elemental.net, daniel.kraft@d9t.de',
    url='https://benji-backup.me/',
    license='LGPL-3',
    packages=find_packages('src', exclude=['*.tests', '*.tests.*']),
    package_dir={
        '': 'src',
    },
    package_data={
        'benji': ['schemas/*/*.yaml', 'sql_migrations/alembic.ini'],
    },
    zip_safe=False,  # ONLY because of alembic.ini. The rest is zip-safe.
    install_requires=[
        'PrettyTable>=0.7.2,<1',
        'sqlalchemy>=2.0.7,<3',
        'setproctitle>=1.1.8,<2',
        'python-dateutil>=2.6.0,<3',
        'alembic>=1.10.2,<2',
        'ruamel.yaml>=0.18,<0.19',
        'psycopg2-binary>=2.7.4,<3',
        'argcomplete>=1.9.4,<2',
        # sparsebitfield 0.2.5 from PyPI does not build on Python 3.13
        # (Cython-generated cimpl/field.c uses removed CPython internals).
        # A patched, Cython-3-regenerated copy is vendored under vendor/.
        # The .post1 version marks the patched build; install it first:
        #   pip install vendor/sparsebitfield-0.2.5/ && pip install -e .
        # See docs/port/dependency-changes.md (C7) for details.
        'sparsebitfield>=0.2.5.post1,<1',
        'cerberus>=1.2,<2',  # Phase D: retained temporarily, will be removed
        'pydantic>=2.5,<3',
        'pycryptodome>=3.6.1,<4',
        'pyparsing>=3.1,<4',
        'semantic_version>=2.8.1,<3',
        'dateparser>=1.1.1,<2',
        'structlog>=19.1.0,<27',
        'colorama>=0.4.1,<1',
        'diskcache>=3.0.6,<6',
        'attrs>=23,<25',
    ],
    extras_require={
        's3': ['boto3>=1.15.0'],
        'b2': ['b2sdk>=1.4.0,<2'],
        'compression': ['zstandard>=0.9.0'],
        # For RBD support the packages supplied by the Linux distribution or the Ceph team should be used,
        # possible packages names include: python-rados, python-rbd or python3-rados, python3-rbd
        #'rbd': ['rados', 'rbd'],
        'dev': ['parameterized', 'wheel', 'yapf', 'mypy', 'pytest', 'build'],
        'doc': ['sphinx', 'sphinx_rtd_theme', 'sphinxcontrib-programoutput'],
        'helpers': ['blinker>=1.4,<2', 'prometheus_client>=0.7.0,<1'],
        'rest-api': ['bottle>=0.12.16,<0.13.0', 'gunicorn>=20.1.0,<21', 'webargs>=8.0.1,<8.1.0', 'requests>=2.27.1,<3'],
    },
    python_requires='~=3.6',
    entry_points="""
        [console_scripts]
            benji = benji.scripts.benji:main
    """,
)
