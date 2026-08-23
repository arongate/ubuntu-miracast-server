.PHONY: all clean build test lint format coverage install uninstall changelog help

# Default target
all: build

# Help message
help:
	@echo "Ubuntu Miracast Server - Make targets:"
	@echo "  make              Build the application"
	@echo "  make test         Run tests"
	@echo "  make lint         Run linting checks (ruff + mypy)"
	@echo "  make format       Format code with ruff"
	@echo "  make coverage     Run tests with coverage"
	@echo "  make changelog    Generate CHANGELOG.md from git history"
	@echo "  make install      Install the application"
	@echo "  make uninstall    Uninstall the application"
	@echo "  make clean        Clean build artifacts"

# Build the application
build:
	python3 -m pip install -e .

# Run tests
test:
	python3 -m pytest tests/ -v

# Run linting (ruff check + format check + mypy)
lint:
	ruff check src/ tests/
	ruff format --check src/ tests/
	mypy src/ --ignore-missing-imports

# Format code with ruff
format:
	ruff check --fix src/ tests/
	ruff format src/ tests/

# Run tests with coverage
coverage:
	python3 -m pytest tests/ -v --cov=miracast_server --cov-report=html --cov-report=term

# Generate changelog from conventional commits
changelog:
	git-cliff --config cliff.toml --output CHANGELOG.md

# Install the application
install:
	python3 -m pip install -e .

# Uninstall the application
uninstall:
	python3 -m pip uninstall -y ubuntu-miracast-server

# Clean build artifacts
clean:
	rm -rf build/ dist/ *.egg-info/ src/*.egg-info/
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -delete
	find . -name ".coverage" -delete
	rm -rf htmlcov/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
