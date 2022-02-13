from setuptools import setup


setup(
    name='stale-issues',
    version='0.1',
    author='Trey Tabner',
    author_email='trey@tabner.com',
    url='https://github.com/treytabner/stale-issues',
    packages=['stale'],
    entry_points={
        'console_scripts': [
            'stale-issues=stale:main',
        ],
    },
    install_requires=[
        'PyGithub',
        'PyYAML',
    ],
    license='GPLv3',
    description='Closes abandoned Github issues after a period of inactivity.'
)
