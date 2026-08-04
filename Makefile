.PHONY: help install data test plan api web mcp mcp-http lint fmt

PORT ?= 8000

help:
	@echo "Territory & Quota Designer"
	@echo "  make install   install Python deps"
	@echo "  make data      regenerate synthetic CSVs (seed 42) into data/"
	@echo "  make test      run the pytest suite"
	@echo "  make plan      print the baseline-vs-optimized scorecard"
	@echo "  make api       run the FastAPI app (uvicorn, reads \$$PORT)"
	@echo "  make web       run the React dashboard (Vite dev server)"
	@echo "  make mcp       run the MCP server over stdio (for Claude Desktop / claude mcp)"
	@echo "  make mcp-http  run the MCP server over HTTP on \$$PORT (MCP_AUTH_TOKEN bearer)"
	@echo "  make lint      ruff + black --check"
	@echo "  make fmt       ruff --fix + black format"

install:
	pip install -r requirements.txt

data:
	python generate_territory_data.py --accounts 800 --reps 12 --seed 42 --outdir data

test:
	python -m pytest -q

plan:
	python -m core.evaluate

api:
	uvicorn api.main:app --reload --host 0.0.0.0 --port $(PORT)

web:
	cd web && npm run dev

mcp:
	python mcp_server.py

mcp-http:
	MCP_TRANSPORT=http python mcp_server.py --http

SRC = core config.py api narrative.py mcp_server.py tests

lint:
	ruff check $(SRC) && black --check $(SRC)

fmt:
	ruff check --fix $(SRC) && black $(SRC)
