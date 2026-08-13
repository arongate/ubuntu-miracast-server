.PHONY: all clean build test lint format coverage install uninstall help

# Default target
all: build

# Help message
help:
	@echo "Ubuntu Miracast Server - Make targets:"
	@echo "  make              Build the application"
	@echo "  make test         Run tests"
	@echo "  make lint         Run linting checks"
	@echo "  make format       Format code with black and isort"
	@echo "  make coverage     Run tests with coverage"
	@echo "  make install      Install the application"
	@echo "  make uninstall    Uninstall the application"
	@echo "  make clean        Clean build artifacts"

# Build the application
build:
	python3 -m pip install -e .

# Run tests
test:
	python3 -m pytest tests/ -v

# Run linting
lint:
	flake8 src tests
	mypy src
	black --check src tests
	isort --check-only src tests

# Format code
format:
	black src tests
	isort src tests

# Run tests with coverage
coverage:
	python3 -m pytest tests/ -v --cov=miracast_server --cov-report=html --cov-report=term

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
