# Contributing to Condense Video Backend

This guide covers the development workflow for contributing to the Condense Video Python Backend project.

## Table of Contents

- [Development Environment Setup](#development-environment-setup)
- [Project Structure](#project-structure)
- [Available Scripts](#available-scripts)
- [Environment Configuration](#environment-configuration)
- [Testing](#testing)
- [Code Quality](#code-quality)
- [Commit Guidelines](#commit-guidelines)
- [Pull Request Process](#pull-request-process)

## Development Environment Setup

### Prerequisites

- Python 3.11+
- Redis 7+
- FFmpeg 4.4+
- Docker & Docker Compose (optional, for containerized development)

### Local Development Setup

```bash
# 1. Clone the repository
git clone <repo-url>
cd condense-video

# 2. Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -e ".[dev,api,worker]"

# 4. Copy environment template
cp .env.example .env

# 5. Configure required environment variables
# Edit .env and set DASHSCOPE_API_KEY

# 6. Start Redis (using Docker)
docker run -d -p 6379:6379 redis:7-alpine

# 7. Run database migrations (if applicable)
# (No migrations currently - Redis is stateless)
```

### Docker Compose Development

```bash
# Start all services
cd docker && docker-compose up -d

# View logs
docker-compose logs -f api
docker-compose logs -f worker

# Stop services
docker-compose down
```

## Project Structure

```
condense-video/
├── api/                      # FastAPI application layer
│   ├── main.py              # Application entry point
│   ├── routers/             # API route handlers
│   │   ├── health.py        # Health check endpoint
│   │   ├── tasks.py         # Task status queries
│   │   └── videos.py        # Video processing endpoints
│   └── schemas/             # Pydantic models for request/response
├── core/                     # Core application components
│   ├── config.py            # Configuration management (pydantic-settings)
│   ├── exceptions.py        # Custom exception classes
│   ├── logging.py           # Loguru logging configuration
│   ├── progress.py          # Progress tracking definitions
│   └── storage.py           # Storage abstraction (local/MinIO/S3)
├── services/                 # External service clients
│   ├── dashscope.py         # Alibaba DashScope AI services
│   └── redis_client.py      # Redis client wrapper
├── tasks/                    # Celery background tasks
│   ├── celery_app.py        # Celery application configuration
│   ├── workflows.py         # Main workflow orchestration
│   ├── asr/                 # Speech recognition tasks
│   ├── ppt/                 # PPT/OCR tasks
│   ├── llm/                 # LLM processing tasks
│   ├── tts/                 # Text-to-speech tasks
│   └── video/               # Video processing tasks
├── utils/                    # Utility functions
│   ├── ffmpeg.py            # FFmpeg command wrapper
│   ├── video.py             # Video processing utilities
│   ├── time.py              # Time/formatting utilities
│   └── text.py              # Text processing utilities
├── tests/                    # Test suite
│   ├── unit/                # Unit tests
│   ├── integration/         # Integration tests
│   └── e2e/                 # End-to-end tests
├── docker/                   # Docker configuration
│   ├── docker-compose.yml   # Service orchestration
│   ├── Dockerfile.api       # API container image
│   └── Dockerfile.worker    # Worker container image
├── requirements/             # Python dependencies
│   ├── base.txt             # Core dependencies
│   ├── api.txt              # API-specific dependencies
│   ├── worker.txt           # Worker-specific dependencies
│   ├── dev.txt              # Development dependencies
│   └── all.txt              # All dependencies combined
├── docs/                     # Project documentation
├── scripts/                  # Utility scripts
├── pyproject.toml            # Project configuration
├── .env.example              # Environment variables template
└── README.md                 # Project overview
```

## Available Scripts

The project uses [pyproject.toml] scripts section. Commands can be run via:

```bash
# Using pip-installed entry points
condense-api    # Start API server (equivalent to uvicorn api.main:app)
condense-worker # Start Celery worker (equivalent to celery -A tasks.celery_app worker)
```

### Manual Startup Commands

```bash
# Start API server (development mode with auto-reload)
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Start API server (production mode)
uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 4

# Start Celery worker
celery -A tasks.celery_app worker --loglevel=info --concurrency=2

# Start Flower monitoring
celery -A tasks.celery_app flower --port=5555

# Run tests
pytest tests/ -v

# Run tests with coverage
pytest tests/ --cov=. --cov-report=html

# Format code with Black
black .

# Lint with Ruff
ruff check .

# Type check with mypy
mypy .
```

## Environment Configuration

All configuration is managed through environment variables. See [`.env.example`] for complete list.

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DASHSCOPE_API_KEY` | Alibaba DashScope API key | `sk-xxxxx` |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379/0` |
| `CELERY_BROKER_URL` | Celery broker URL | `redis://localhost:6379/0` |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `API_HOST` | API server host | `127.0.0.1` |
| `API_PORT` | API server port | `8000` |
| `API_WORKERS` | Number of API workers | `1` |
| `API_RELOAD` | Enable auto-reload | `true` |
| `STORAGE_BACKEND` | Storage backend | `uuguu` |
| `STORAGE_PATH` | Local storage path | `./data` |
| `WORKER_CONCURRENCY` | Celery worker concurrency | `2` |
| `OCR_MODEL` | DashScope OCR model | `qwen3.5-plus` |
| `OCR_CONCURRENCY` | OCR parallel requests | `5` |
| `TTS_ENGINE` | TTS engine (dashscope/edgetts) | `dashscope` |
| `TTS_VOICE` | Voice name | `Cherry` |

## Testing

### Test Organization

- **Unit tests** (`tests/unit/`): Test individual functions and classes
- **Integration tests** (`tests/integration/`): Test API endpoints and external services
- **E2E tests** (`tests/e2e/`): Test complete video processing workflows

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/unit/test_ffmpeg.py

# Run by marker
pytest -m unit          # Unit tests only
pytest -m integration   # Integration tests only
pytest -m "not slow"    # Skip slow tests

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=. --cov-report=html --cov-report=term-missing
```

### Writing Tests

```python
# tests/unit/test_example.py
import pytest
from tasks.video.edit import VideoEditor

class TestVideoEditor:
    """Test suite for VideoEditor class."""

    @pytest.fixture
    def editor(self):
        """Fixture providing a VideoEditor instance."""
        return VideoEditor()

    def test_trim_video(self, editor, tmp_path):
        """Test video trimming functionality."""
        # Arrange
        input_file = "fixtures/sample.mp4"
        output_file = tmp_path / "output.mp4"

        # Act
        result = editor.trim(input_file, output_file, start=0, end=10)

        # Assert
        assert result.success
        assert output_file.exists()
```

## Code Quality

### Linting and Formatting

The project uses:
- **Black**: Code formatting (line length: 100)
- **Ruff**: Fast Python linter
- **mypy**: Static type checking

### Pre-commit Hooks

Install pre-commit hooks for automatic code quality checks:

```bash
pip install pre-commit
pre-commit install
```

### Running Checks

```bash
# Format code
black .

# Check linting
ruff check .

# Fix auto-fixable linting issues
ruff check . --fix

# Type checking
mypy .

# Run all quality checks
black . && ruff check . && mypy . && pytest
```

### Code Style Guidelines

- Follow [PEP 8] style guide
- Use type hints for all function signatures
- Write Google-style docstrings
- Keep functions under 50 lines
- Keep files under 800 lines
- Prefer composition over inheritance
- Use immutable data patterns

## Commit Guidelines

Follow [Conventional Commits] specification:

```
<type>: <description>

[optional body]
```

### Commit Types

| Type | Description |
|------|-------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `refactor` | Code refactoring |
| `docs` | Documentation changes |
| `test` | Test additions/modifications |
| `chore` | Maintenance tasks |
| `perf` | Performance improvements |
| `ci` | CI/CD changes |

### Examples

```bash
feat: add video trimming functionality
fix: resolve Redis connection timeout
refactor: extract storage interface to separate module
docs: update README with Docker setup instructions
test: add integration tests for API endpoints
```

## Pull Request Process

1. **Fork and branch**: Create a feature branch from `main`
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make changes**: Implement your feature with tests

3. **Run quality checks**:
   ```bash
   black . && ruff check . && mypy . && pytest
   ```

4. **Commit your changes**:
   ```bash
   git add .
   git commit -m "feat: add my new feature"
   ```

5. **Push to your fork**:
   ```bash
   git push origin feature/my-feature
   ```

6. **Create Pull Request**:
   - Fill in the PR template
   - Link related issues
   - Ensure CI checks pass

7. **Address review feedback**: Make requested changes

8. **Merge**: After approval, merge with squash commit

### Pull Request Checklist

- [ ] Code follows project style guidelines
- [ ] Tests added/updated and passing (>80% coverage)
- [ ] Documentation updated
- [ ] All quality checks pass
- [ ] No breaking changes (or clearly documented)

## Troubleshooting

### Common Issues

**Redis connection refused**
```bash
# Start Redis
docker run -d -p 6379:6379 redis:7-alpine
```

**FFmpeg not found**
```bash
# Ubuntu/Debian
apt install ffmpeg

# macOS
brew install ffmpeg

# Windows: Download from https://ffmpeg.org/
```

**Import errors**
```bash
# Reinstall dependencies
pip install -e ".[dev,api,worker]"
```

**Tests failing due to missing fixtures**
```bash
# Install test dependencies
pip install pytest pytest-mock pytest-cov
```

## Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Celery Documentation](https://docs.celeryq.dev/)
- [DashScope API Reference](https://help.aliyun.com/zh/dashscope/)
- [FFmpeg Documentation](https://ffmpeg.org/documentation.html)

[pyproject.toml]: ../pyproject.toml
[`.env.example`]: ../.env.example
[PEP 8]: https://peps.python.org/pep-0008/
[Conventional Commits]: https://www.conventionalcommits.org/
