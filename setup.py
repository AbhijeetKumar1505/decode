from setuptools import find_packages, setup

setup(
    name="decode",
    version="1.0.0",
    packages=find_packages(),
    python_requires=">=3.11",
    entry_points={
        "console_scripts": [
            "decode=decode.__main__:main",
        ],
    },
    install_requires=[
        "typer>=0.25.0",
        "rich>=13.0.0",
        "faiss-cpu>=1.8.0",
        "python-dotenv>=1.0.0",
        "langchain>=0.1.0",
        "python-nmap>=0.7.1",
        "requests>=2.32.0",
        "docker>=7.0.0",
        "numpy>=1.26.0",
        "psutil>=6.0.0",
        "jinja2>=3.1.3",
        "pyyaml>=6.0.3",
        "pydantic>=2.0.0",
        "openai>=1.0.0",
        "anthropic>=0.30.0",
        "defusedxml>=0.7.1",
    ],
    extras_require={
        # Real MCP transport (stdio only); the executor works with a fake client
        # otherwise. Install with `pip install .[mcp]`.
        "mcp": ["mcp>=1.0.0"],
    },
)
