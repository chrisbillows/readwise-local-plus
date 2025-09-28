# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Readwise Local Plus** is a Python application that synchronizes Readwise highlights to a local SQLite database and exports them to Roam Research. The project follows a pipeline architecture that fetches, validates, flattens, and stores Readwise data.

### Core Architecture

- **Pipeline-based processing**: Data flows through `fetch → validate nested → flatten → validate flattened → store` stages in `pipeline.py:408`
- **SQLAlchemy ORM**: All data models are in `models.py` with extensive relationships and validation mixins
- **Pydantic validation**: Schema validation occurs in two layers - nested objects first, then flattened objects
- **Dependency injection**: All pipeline functions accept injectable dependencies for testing

### Key Components

1. **Data Pipeline** (`pipeline.py`): Core orchestration of the sync process
2. **Database Operations** (`db_operations.py`): Database session management and population
3. **Models** (`models.py`): SQLAlchemy ORM classes with versioning support
4. **Integrations** (`integrations/`): External service integrations (Readwise, Roam)
5. **CLI** (`cli.py`): Command-line interface with subcommands

## Development Commands

### Setup and Installation
```bash
# Install package in development mode with dev dependencies
pip install -e ".[dev]"
```

### Code Quality and Testing
```bash
# Run all linting and formatting
ruff check                    # Lint code  
ruff format                   # Format code
ruff check --fix              # Auto-fix issues

# Type checking
mypy readwise_local_plus --strict --config-file=pyproject.toml

# Testing
pytest                        # Run all tests
pytest tests/unit/            # Run unit tests only
pytest tests/integration/     # Run integration tests only
pytest -m "not e2e"          # Skip end-to-end tests
pytest --cov=readwise_local_plus tests/  # Run with coverage

# Pre-commit hooks (runs ruff, mypy, pytest automatically)
pre-commit run --all-files
```

### Building and Installation
```bash
# Build package
python -m build              # Creates wheel and sdist in dist/

# Install locally built package
pip install dist/*.whl
```

### Application Usage
```bash
# Main commands (installed as rwlp or readwise-local-plus)
rwlp sync --delta            # Sync new highlights (default)
rwlp sync --all              # Full sync of all highlights
rwlp list-invalids           # Show validation errors
rwlp rw-api --datetime 2024-01-01T00:00Z  # Fetch since specific date
```

## Configuration

- Environment file: `~/.config/readwise-local-plus/.env`
- Required environment variables: `READWISE_API_TOKEN`, `ROAM_API_TOKEN`
- Database location: `~/readwise-local-plus/readwise-local-plus.db`
- Roam graph name is hardcoded to "Billowz" in `config.py:51`

## Database Schema

The database uses versioning for highlights and books. Key tables:
- `books`, `highlights`, `highlight_tags`, `book_tags` - Core Readwise data
- `book_versions`, `highlight_versions` - Change tracking
- `readwise_batches` - Batch metadata for sync operations
- `roam_*` tables - Roam Research integration tracking

## Testing Strategy

- **Unit tests**: `tests/unit/` - Test individual functions and classes
- **Integration tests**: `tests/integration/` - Test database and CLI integration  
- **End-to-end tests**: `tests/e2e/` - Full workflow tests (marked with `e2e` marker)
- Mock environment file is created at `$HOME/.config/readwise-local-plus/.env` for CI

## Integration Development

When working on Roam integration:
- See `readwise_local_plus/integrations/roam.py` for the main integration
- Roam query examples in `readwise_local_plus/integrations/README.md`
- Database models for Roam exports are in `models.py` (lines 615-751)