.PHONY: help install data test plan api web lint fmt

PORT ?= 8000

help:
	@echo "Territory & Quota Designer"
	@echo "  make install   install Python deps"
	@echo "  make data      regenerate synthetic CSVs (seed 42) into data/"
	@echo "  make test      run the pytest suite"
	@echo "  make plan      print the baseline-vs-optimized scorecard"
	@echo "  make api       run the FastAPI app (uvicorn, reads \$$PORT)"
	@echo "  make web       run the React dashboard (Vite dev server)"
	@echo "  make lint      ruff + black --check"
	@echo "  make fmt       ruff --fix + black format"

install:
	pip install -r requirements.txt

data:
	python generate_territory_data.py --accounts 800 --reps 12 --seed 42 --outdir data

test:
	pytest -q

plan:
	python -m core.evaluate

api:
	uvicorn api.main:app --reload --host 0.0.0.0 --port $(PORT)

web:
	cd web && npm run dev

lint:
	ruff check core config.py api tests && black --check core config.py api tests

fmt:
	ruff check --fix core config.py api tests && black core config.py api tests
