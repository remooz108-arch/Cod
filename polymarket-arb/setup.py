from setuptools import setup, find_packages

setup(
    name="polymarket-arb",
    version="1.0.0",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "py-clob-client-v2>=1.0.0",
        "aiohttp>=3.9",
        "websockets>=12.0",
        "rich>=13.0",
        "python-dotenv>=1.0",
        "eth-account>=0.11",
    ],
    entry_points={
        "console_scripts": [
            "polymarket-arb=src.main:cli_main",
        ],
    },
)
