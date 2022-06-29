"""
    Setup launchy package.
"""

import ast
import re

from setuptools import setup, find_packages


def get_version():
    """Gets the current version"""
    _version_re = re.compile(r'__VERSION__\s+=\s+(.*)')
    with open('clash/__init__.py', 'rb') as init_file:
        version = str(ast.literal_eval(_version_re.search(
            init_file.read().decode('utf-8')).group(1)))
    return version


setup(
    name='clash',
    version=get_version(),
    license='LGPL',

    description='Collaboration Shell',

    url='https://github.com/neolynx/clash',

    packages=find_packages(),
    include_package_data=True,

    install_requires=[
    ],

    keywords=[
        'psutil',
    ],
    classifiers=[
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Operating System :: OS Independent',
        'License :: OSI Approved :: Apache 2.0',
        'Topic :: Utilities'
    ],

    entry_points={
        "console_scripts": [
            "clash = clash:main",
        ]
    }
)
