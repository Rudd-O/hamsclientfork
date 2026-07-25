import io
import os
import re

from setuptools import find_packages, setup


def read(filename: str):
    filename = os.path.join(os.path.dirname(__file__), filename)
    text_type = type("")
    with io.open(filename, mode="r", encoding="utf-8") as fd:
        return re.sub(text_type(r":[a-z]+:`~?(.*?)`"), text_type(r"``\1``"), fd.read())


setup(
    name="hamsclientfork",
    version=[
        ln
        for ln in read("hamsclientfork/__init__.py").splitlines()
        if ln.startswith("__version__")
    ][0]
    .partition(" = ")[2]
    .replace('"', ""),
    url="https://github.com/Rudd-O/hamsclientfork",
    license="MIT",
    author="websylv",
    author_email="div@webhu.org",
    description="Library to get data from meteo swiss",
    long_description=read("README.rst"),
    packages=find_packages(exclude=("tests",)),
    install_requires=[
        "requests>=2.22.0",
        "beautifulsoup4>=4.8.2",
        "geopy>=2.0.0",
    ],
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)
