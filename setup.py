from setuptools import find_packages, setup

setup(
    name="django-common-migration",
    version="0.1.0",
    zip_safe=True,
    py_modules=['common_migration'],
    install_requires=[
    ],
    packages=find_packages(
        exclude=['tests'],
    ),
)
