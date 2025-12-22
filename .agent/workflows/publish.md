---
description: Steps to build and publish Logify to PyPI
---

### 1. Versioning
Make sure you increment the `version` in `pyproject.toml`.

### 2. Clean old builds
```bash
rm -rf dist/ build/ *.egg-info
```

### 3. Build the package
```bash
python3 -m pip install --upgrade build
python3 -m build
```

### 4. Upload to PyPI
// turbo
```bash
python3 -m pip install twine
python3 -m twine upload dist/*
```
