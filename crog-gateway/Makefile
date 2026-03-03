# CROG Gateway - Makefile for common tasks

.PHONY: help install run test lint format docker-build docker-run clean

help:
	@echo "CROG Gateway - Available Commands:"
	@echo "  make install       - Install dependencies"
	@echo "  make run          - Run development server"
	@echo "  make test         - Run tests with coverage"
	@echo "  make lint         - Run linters (flake8, mypy)"
	@echo "  make format       - Format code (black, isort)"
	@echo "  make docker-build - Build Docker image"
	@echo "  make docker-run   - Run in Docker"
	@echo "  make clean        - Clean generated files"

install:
	pip install -r requirements.txt

run:
	python app/main.py

test:
	pytest tests/ -v --cov=app --cov-report=html

lint:
	@echo "Running flake8..."
	flake8 app/ --max-line-length=100 --extend-ignore=E203,W503
	@echo "Running mypy..."
	mypy app/ --ignore-missing-imports

format:
	@echo "Running black..."
	black app/ tests/ --line-length=100
	@echo "Running isort..."
	isort app/ tests/

docker-build:
	docker build -t crog-gateway:latest .

docker-run:
	docker-compose up -d

docker-logs:
	docker-compose logs -f

docker-stop:
	docker-compose down

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage
	rm -rf .mypy_cache
